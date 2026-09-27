"""`ht lint`: checagens pré-compile de um VMF.

Checagens (nome usado em --only / --skip):
  markers     marcadores ht_* sem par                                    (erro)
  outputs     output mirando targetname inexistente                      (erro)
  textures    material inexistente no jogo/BSP                           (erro)   precisa dos arquivos do jogo
  models      modelo inexistente (erro) / prop_static com modelo não-static (aviso)   idem
  leak        entidade alcançável a partir do vazio (voxel flood-fill)   (erro)   precisa numpy+scipy
  nodraw      face toolsnodraw virada pra área jogável                   (aviso)  idem; heurística: "jogável"
              = ar conectado a uma entidade, não linha de visão (nodraw em topo de telhado pode ser intencional)
  duplicates  brushes idênticos                                          (aviso)
  overlaps    brushes de mundo se sobrepondo                             (aviso)
  grid        vértices fora do grid                                      (aviso)

Recursos do jogo (materiais/modelos) vêm de `Resources`: ou dos VPKs do jogo (`--game`, HT_GAME, ou a
instalação padrão do GMod), ou injetados nos testes.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from srctools import VMF, Vec
from srctools.vmf import Entity, Solid

from hammertools.core import geom
from hammertools.core import vmf as vmfio

MAX_EXAMPLES = 5
ALL_CHECKS = ("markers", "outputs", "textures", "models", "leak", "nodraw", "duplicates", "overlaps", "grid")

# texturas de ferramenta que NÃO selam o mapa (brush com qualquer face dessas não conta pro selo)
NONSEAL_TOOLS = {
    "tools/toolsclip", "tools/toolsplayerclip", "tools/toolsnpcclip", "tools/toolstrigger", "tools/toolshint",
    "tools/toolsskip", "tools/toolsareaportal", "tools/toolsoccluder", "tools/toolsfog", "tools/toolsinvisible",
    "tools/toolsinvisibleladder", "tools/toolsblock_los", "tools/toolsblockbullets", "tools/toolsblockbullets2",
    "tools/toolsgrenadeclip", "tools/toolsdotted", "tools/toolsorigin", "tools/toolscontrolclip",
}
NODRAW = "tools/toolsnodraw"

DEFAULT_GAME_DIRS = [
    Path.home() / ".local/share/Steam/steamapps/common/GarrysMod/garrysmod",
    Path("C:/Program Files (x86)/Steam/steamapps/common/GarrysMod/garrysmod"),
]


# --------------------------------------------------------------------------- recursos do jogo
@dataclass
class Resources:
    """Consultas sobre arquivos do jogo. Tudo opcional: sem fonte, as checagens dependentes são puladas."""
    material_exists: Callable[[str], bool] | None = None
    material_seals: Callable[[str], bool] | None = None   # False = translúcido/água (não sela)
    model_info: Callable[[str], dict | None] | None = None  # None = não existe; {"static": bool}
    source: str = ""

    @classmethod
    def from_game(cls, gamedir: str | Path | None, bsp: str | Path | None = None, extra: Iterable[str | Path] = (),
                  addons: bool = True) -> "Resources":
        """Fontes, em ordem: BSP (pakfile), pastas extras, VPKs/pastas do jogo (gameinfo), addons .gma
        (addons/, cache/workshop/, Workshop do Steam)."""
        import logging
        logging.getLogger("srctools").setLevel(logging.ERROR)
        gd = _find_game(gamedir)
        if gd is None:
            return cls(source="sem arquivos do jogo")
        from srctools.game import Game
        from srctools.filesys import RawFileSystem
        from hammertools.core.gma import AddonIndex, find_addons
        fs = Game(gd).get_filesystem()
        extra = list(extra)
        for d in extra:
            fs.add_sys(RawFileSystem(str(d)))
        mounted = []
        for mdir in _mountable_games(gd):
            try:
                for sub in Game(mdir).get_filesystem().systems:
                    fs.add_sys(sub[0] if isinstance(sub, tuple) else sub)
                mounted.append(mdir.name)
            except Exception:  # noqa: BLE001  (gameinfo exótico: ignora)
                pass
        pak: dict[str, str] = {}
        pakfile = None
        if bsp:
            from srctools.bsp import BSP
            pakfile = BSP(str(bsp)).pakfile
            pak = {n.lower().replace("\\", "/"): n for n in pakfile.namelist()}
        gmas = AddonIndex(find_addons(gd)) if addons else None

        def read(path: str, limit: int | None = None) -> bytes | None:
            p = path.lower().replace("\\", "/")
            if p in pak:
                data = pakfile.read(pak[p])
                return data[:limit] if limit else data
            try:
                with fs[p].open_bin() as f:
                    return f.read(limit) if limit else f.read()
            except (FileNotFoundError, KeyError, OSError):
                pass
            if gmas is not None and p in gmas:
                return gmas.read(p, limit)
            return None

        def exists(path: str) -> bool:
            p = path.lower().replace("\\", "/")
            if p in pak or (gmas is not None and p in gmas):
                return True
            try:
                fs[p]
                return True
            except FileNotFoundError:
                return False

        seal_cache: dict[str, bool] = {}

        def material_seals(mat: str) -> bool:
            m = mat.lower()
            if m not in seal_cache:
                t = (read(f"materials/{m}.vmt") or b"").decode("utf-8", "replace").lower()
                shader = re.match(r'\s*"?([a-z_0-9]+)"?', t)
                translucent = bool(re.search(r'"?\$(translucent|alphatest)"?\s+"?1', t)) or bool(re.search(r'"?\$alpha"?\s+"?0?\.\d', t))
                water = bool(shader and shader.group(1) in ("water", "refract")) or '"$abovewater"' in t
                seal_cache[m] = not (translucent or water)
            return seal_cache[m]

        model_cache: dict[str, dict | None] = {}

        def model_info(model: str) -> dict | None:
            key = model.lower().replace("\\", "/")
            if key not in model_cache:
                head = read(key, 160)
                if head is None:
                    model_cache[key] = None
                elif len(head) >= 156 and head[:4] == b"IDST":
                    flags = int.from_bytes(head[152:156], "little")  # studiohdr_t.flags
                    model_cache[key] = {"static": bool(flags & 0x10)}  # STUDIOHDR_FLAGS_STATIC_PROP
                else:
                    model_cache[key] = {"static": True, "unknown": True}
            return model_cache[key]

        extra = list(extra)
        src = str(gd) + (f" + {len(extra)} pasta(s) extra(s)" if extra else "") + (f" + jogos montados: {', '.join(mounted)}" if mounted else "") + (f" + {gmas.count} addons" if gmas else "") + (f" + BSP" if bsp else "")
        return cls(lambda m: exists(f"materials/{m.lower()}.vmt"), material_seals, model_info, source=src)


# jogos que o GMod monta sozinho quando instalados (pasta em steamapps/common, subpasta do jogo)
MOUNTABLE = [
    ("Counter-Strike Source", "cstrike"), ("Half-Life 2", "episodic"), ("Half-Life 2", "ep2"),
    ("Half-Life 2", "lostcoast"), ("Half-Life 2", "hl2"), ("Team Fortress 2", "tf"), ("Portal", "portal"),
    ("Day of Defeat Source", "dod"), ("Half-Life 2 Deathmatch", "hl2mp"), ("Portal 2", "portal2"),
    ("Left 4 Dead 2", "left4dead2"),
]


def _steam_libraries(gamedir: Path) -> list[Path]:
    """Bibliotecas do Steam (libraryfolders.vdf) a partir da instalação do jogo."""
    steamapps = gamedir.parent.parent.parent
    libs = [steamapps]
    vdf = steamapps / "libraryfolders.vdf"
    if vdf.exists():
        for m in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(errors="ignore")):
            p = Path(m.group(1).replace("\\\\", "/")) / "steamapps"
            if p.is_dir() and p not in libs:
                libs.append(p)
    return libs


def _mountable_games(gamedir: Path) -> list[Path]:
    out = []
    for lib in _steam_libraries(gamedir):
        for folder, sub in MOUNTABLE:
            d = lib / "common" / folder / sub
            if (d / "gameinfo.txt").exists() and d not in out:
                out.append(d)
    return out


def _find_game(gamedir) -> Path | None:
    for cand in [gamedir, os.environ.get("HT_GAME"), *DEFAULT_GAME_DIRS]:
        if cand and (Path(cand) / "gameinfo.txt").exists():
            return Path(cand)
    return None


# --------------------------------------------------------------------------- resultado
@dataclass
class Issue:
    level: str          # "erro" | "aviso"
    check: str
    msg: str
    pos: Vec | None = None
    group: str = ""     # pra resumo (ex.: pasta do material/modelo)
    name: str = ""      # recurso (material/modelo) a que se refere
    count: int = 0      # quantas vezes é usado
    examples: list = field(default_factory=list)  # [(Vec, "descrição")], no máximo MAX_EXAMPLES


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)   # checagem -> motivo
    leak_path: list[Vec] = field(default_factory=list)
    stats: dict[str, object] = field(default_factory=dict)

    def add(self, level, check, msg, pos=None, group="", **kw):
        self.issues.append(Issue(level, check, msg, pos, group, **kw))

    @property
    def errors(self):
        return [i for i in self.issues if i.level == "erro"]


# --------------------------------------------------------------------------- execução
def run(v: VMF, res: Resources | None = None, checks: Iterable[str] = ALL_CHECKS, grid: float = 1.0,
        detail_grid: bool = False, voxel: float | None = None, overlap_min: float = 1.0) -> Report:
    from hammertools.generators import REGISTRY, SINGLE
    res = res or Resources(source="sem arquivos do jogo")
    checks = set(checks)
    rep = Report()
    rep.stats["recursos"] = res.source

    if "markers" in checks:
        for g in vmfio.group_markers(vmfio.markers(v)).values():
            if g.classname not in REGISTRY:
                continue
            if g.classname in SINGLE:
                if g.by_role("start") is None:
                    rep.add("erro", "markers", f"{g.name} ({g.classname}) sem o marcador principal")
            elif g.by_role("start") is None or g.by_role("end") is None:
                rep.add("erro", "markers", f"{g.name} ({g.classname}) sem par início/fim")

    if "outputs" in checks:
        names = {e["targetname"].lower() for e in v.entities if e.get("targetname")}
        classnames = {e["classname"].lower() for e in v.entities}
        for e in v.entities:
            for o in e.outputs:
                t = o.target
                if not t or t.startswith("!") or "*" in t or t.lower() in names or t.lower() in classnames:
                    continue
                rep.add("erro", "outputs", f"{e['classname']} '{e.get('targetname', '?')}' -> {o.output} mira '{t}' que não existe", _origin(e))

    all_solids = [(s, None) for s in v.brushes] + [(s, e) for e in v.entities for s in e.solids]

    if "textures" in checks:
        if res.material_exists is None:
            rep.skipped["textures"] = "arquivos do jogo não encontrados (use --game)"
        else:
            # uso = (solid, face, dono) ou (entidade, None, None) pra overlay/decal
            uses: dict[str, list] = defaultdict(list)
            for s, e in all_solids:
                for side in s.sides:
                    uses[side.mat.lower()].append((s, side, e))
            for e in v.entities:
                if e["classname"] in ("info_overlay", "info_overlay_transition") and e.get("material"):
                    uses[e["material"].lower()].append((e, None, None))
                if e["classname"] == "infodecal" and e.get("texture"):
                    uses[e["texture"].lower()].append((e, None, None))
            for mat, users in sorted(uses.items()):
                if mat and not res.material_exists(mat):
                    ex = _texture_examples(users)
                    rep.add("erro", "textures", f"material inexistente '{mat}' ({len(users)} uso(s))",
                            ex[0][0] if ex else None, group=_folder(mat), name=mat, count=len(users), examples=ex)

    if "models" in checks:
        if res.model_info is None:
            rep.skipped["models"] = "arquivos do jogo não encontrados (use --game)"
        else:
            for e in v.entities:
                mdl = e.get("model", "")
                if not mdl.lower().endswith(".mdl"):
                    continue
                info = res.model_info(mdl)
                if info is None:
                    rep.add("erro", "models", f"{e['classname']}: modelo inexistente '{mdl}'", _origin(e), group=_folder(mdl.lower().removeprefix("models/"), 2))
                elif e["classname"] == "prop_static" and not info.get("static", True):
                    rep.add("aviso", "models", f"prop_static com modelo que não é static prop '{mdl}' (vira prop_dynamic ou some)", _origin(e))

    if "duplicates" in checks:
        seen: dict[frozenset, Solid] = {}
        for s, e in all_solids:
            k = (geom.plane_key(s), id(e) if e is not None and e["classname"] not in ("func_detail",) else None)
            if k in seen:
                rep.add("aviso", "duplicates", f"solid {s.id} idêntico ao solid {seen[k].id}", _center(s))
            else:
                seen[k] = s

    if "overlaps" in checks:
        _overlaps(v, rep, overlap_min)

    if "grid" in checks:
        for s, e in all_solids:
            if e is not None and e["classname"] == "func_detail" and not detail_grid:
                continue
            bad = [side for side in s.sides if any(not vmfio.is_on_grid(c, grid) for p in side.planes for c in (p.x, p.y, p.z))]
            if bad:
                owner = "mundo" if e is None else e["classname"]
                kind = "displacement" if any(side.is_disp for side in s.sides) else "brush"
                rep.add("aviso", "grid", f"{owner} solid {s.id} ({kind}): {len(bad)} face(s) fora do grid {grid}", _center(s))

    if "leak" in checks or "nodraw" in checks:
        try:
            import numpy  # noqa: F401
            import scipy  # noqa: F401
        except ImportError:
            for c in ("leak", "nodraw"):
                if c in checks:
                    rep.skipped[c] = "precisa de numpy e scipy (pip install numpy scipy)"
        else:
            _voxel_checks(v, res, rep, checks, voxel)
    return rep


def _texture_examples(users: list) -> list:
    """Até MAX_EXAMPLES localizações, uma por solid/entidade distinta: centro da FACE que usa o material."""
    out, seen = [], set()
    for obj, side, owner in users:
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        if side is None:
            p = _origin(obj)
            desc = f"{obj['classname']} (id {obj.id})"
        else:
            poly = next((pl for sd, pl in geom.face_polys(obj) if sd is side), None)
            p = geom.centroid(poly) if poly else _center(obj)
            desc = f"{'mundo' if owner is None else owner['classname']} · solid {obj.id} · face {side.id}"
        if p is not None:
            out.append((p, desc))
        if len(out) >= MAX_EXAMPLES:
            break
    return out


def _folder(path: str, depth: int = 1) -> str:
    """Pasta (até `depth` níveis) que contém o arquivo; resume o 'pacote de conteúdo' faltando."""
    dirs = path.replace("\\", "/").split("/")[:-1]
    return "/".join(dirs[:depth]) + "/" if dirs else "(raiz)"


def _origin(e: Entity) -> Vec | None:
    try:
        return Vec.from_str(e["origin"]) if e.get("origin") else None
    except ValueError:
        return None


def _center(s: Solid) -> Vec:
    lo, hi = s.get_bbox()
    return (lo + hi) / 2


# --------------------------------------------------------------------------- sobreposição
def _generated_groups(v: VMF) -> dict[int, int]:
    """solid.id -> id do visgroup gerado (ht_generated/<x> ou ht_preview/<x>) a que pertence."""
    gen_ids = set()
    for vg in v.vis_tree:
        if vg.name in (vmfio.GENERATED_VISGROUP, vmfio.PREVIEW_VISGROUP):
            gen_ids |= {c.id for c in vg.child_groups}
    out = {}
    for s in v.brushes:
        hit = s.visgroup_ids & gen_ids
        if hit:
            out[s.id] = min(hit)
    return out


def _visible(s: Solid) -> bool:
    return any(not side.mat.lower().startswith("tools/") for side in s.sides)


def _overlaps(v: VMF, rep: Report, min_depth: float) -> None:
    """Brushes que se interpenetram mais que `min_depth`. Entre brushes de MUNDO o vbsp faz CSG e corta as
    faces escondidas, então só entra na estatística. Reporta quando envolve func_detail ou entidade de
    brush (faces não são cortadas contra o mundo: face escondida desperdiçada ou z-fighting). Ignora peças
    do mesmo gerador, da mesma entidade, e brushes só de ferramenta (trigger, clip...)."""
    gen = _generated_groups(v)
    items = []
    for s in v.brushes:
        if not any(side.is_disp for side in s.sides) and _visible(s):
            items.append((*s.get_bbox(), s, None))
    for e in v.entities:
        for s in e.solids:
            if _visible(s):
                items.append((*s.get_bbox(), s, e))
    items.sort(key=lambda t: t[0].x)
    cache: dict[int, tuple] = {}

    def data(s):
        if s.id not in cache:
            cache[s.id] = (geom.vertices(s), [geom.outward(sd)[0] for sd in s.sides], geom.edges(s))
        return cache[s.id]

    active: list = []
    world_pairs = 0
    for lo, hi, s, e in items:
        active = [t for t in active if t[1].x > lo.x + min_depth]
        for lo2, hi2, s2, e2 in active:
            if min(hi.y, hi2.y) - max(lo.y, lo2.y) <= min_depth or min(hi.z, hi2.z) - max(lo.z, lo2.z) <= min_depth:
                continue
            if e is not None and e is e2:
                continue
            if s.id in gen and gen.get(s2.id) == gen[s.id]:
                continue
            va, na, ea = data(s)
            vb, nb, eb = data(s2)
            depth = geom.penetration(va, na, vb, nb, ea, eb)
            if depth <= min_depth:
                continue
            if e is None and e2 is None:
                world_pairs += 1
                continue
            what = lambda ent, sol: f"{ent['classname']} solid {sol.id}" if ent is not None else f"mundo solid {sol.id}"
            rep.add("aviso", "overlaps", f"{what(e2, s2)} e {what(e, s)} se sobrepõem ({depth:.1f}u): face escondida não é cortada, possível z-fighting", _center(s))
        active.append((lo, hi, s, e))
    rep.stats["sobreposições mundo x mundo (inofensivas)"] = world_pairs


# --------------------------------------------------------------------------- voxel: leak e nodraw
def _seals(s: Solid, res: Resources) -> bool:
    if any(side.is_disp for side in s.sides):
        return False
    for side in s.sides:
        m = side.mat.lower()
        if m in NONSEAL_TOOLS:
            return False
        if res.material_seals is not None and not m.startswith("tools/") and not res.material_seals(m):
            return False
    return True


def _rasterize(grid, origin, vs, solids: list[Solid], expand: bool) -> None:
    """Marca em `grid` os voxels ocupados por cada solid. expand=True: voxel conta se o CUBO do voxel
    toca o brush (fecha frestas menores que o voxel, evita falso leak em parede fina/rotacionada);
    False: só se o CENTRO está dentro."""
    import numpy as np
    shape = np.array(grid.shape)
    for s in solids:
        lo, hi = s.get_bbox()
        i0 = np.maximum(np.floor((np.array([lo.x, lo.y, lo.z]) - origin) / vs).astype(int) - 1, 0)
        i1 = np.minimum(np.ceil((np.array([hi.x, hi.y, hi.z]) - origin) / vs).astype(int) + 1, shape)
        if np.any(i1 <= i0):
            continue
        xs = origin[0] + (np.arange(i0[0], i1[0]) + 0.5) * vs
        ys = origin[1] + (np.arange(i0[1], i1[1]) + 0.5) * vs
        zs = origin[2] + (np.arange(i0[2], i1[2]) + 0.5) * vs
        X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
        inside = np.ones(X.shape, dtype=bool)
        for side in s.sides:
            n, p = geom.outward(side)
            slack = (abs(n.x) + abs(n.y) + abs(n.z)) * vs / 2 - 0.01 if expand else 0.01
            inside &= (X * n.x + Y * n.y + Z * n.z) <= (n.dot(p) + slack)
        grid[i0[0]:i1[0], i0[1]:i1[1], i0[2]:i1[2]] |= inside


def _voxel_checks(v: VMF, res: Resources, rep: Report, checks: set, voxel: float | None) -> None:
    import numpy as np
    from scipy import ndimage

    sealing = [s for s in v.brushes if _seals(s, res)]
    if not sealing:
        for c in ("leak", "nodraw"):
            if c in checks:
                rep.skipped[c] = "nenhum brush de mundo que sele"
        return
    lo = Vec(min(s.get_bbox()[0].x for s in sealing), min(s.get_bbox()[0].y for s in sealing), min(s.get_bbox()[0].z for s in sealing))
    hi = Vec(max(s.get_bbox()[1].x for s in sealing), max(s.get_bbox()[1].y for s in sealing), max(s.get_bbox()[1].z for s in sealing))
    ext = max(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z)
    vs = float(voxel) if voxel else max(8.0, 8.0 * -(-ext // (8 * 320)))  # ~320 voxels no eixo maior, múltiplo de 8
    pad = 2
    origin = np.array([lo.x, lo.y, lo.z]) - pad * vs
    shape = tuple(int(np.ceil((b - a) / vs)) + 2 * pad for a, b in zip((lo.x, lo.y, lo.z), (hi.x, hi.y, hi.z)))
    solid = np.zeros(shape, dtype=bool)
    _rasterize(solid, origin, vs, sealing, expand=True)
    labels, _ = ndimage.label(~solid)
    outside = labels[0, 0, 0]
    rep.stats["voxel"] = vs
    rep.stats["grade"] = "x".join(map(str, shape))

    def idx(p: Vec):
        i = np.floor((np.array([p.x, p.y, p.z]) - origin) / vs).astype(int)
        if np.any(i < 0) or np.any(i >= np.array(shape)):
            return None
        return tuple(i)

    playable = set()
    leaked = []
    for e in v.entities:
        if e.solids or e["classname"].startswith("ht_"):
            continue
        p = _origin(e)
        if p is None:
            continue
        i = idx(p)
        if i is None:
            leaked.append((e, p, None))
            continue
        lab = labels[i]
        if lab == 0:
            continue  # origem dentro de sólido
        if lab == outside:
            leaked.append((e, p, i))
        else:
            playable.add(lab)

    if "leak" in checks:
        for e, p, i in leaked[:1]:
            rep.leak_path = _bfs_out(labels, outside, i, origin, vs) if i is not None else [p]
        for e, p, _ in leaked:
            rep.add("erro", "leak", f"{e['classname']} '{e.get('targetname', '')}' alcança o vazio (leak)", p)
        rep.stats["entidades no vazio"] = len(leaked)

    if "nodraw" in checks:
        n = _nodraw(v, rep, labels, playable, idx, vs)
        rep.stats["nodraw visíveis"] = n


def _nodraw(v: VMF, rep: Report, labels, playable: set, idx, vs: float) -> int:
    """Face nodraw é 'visível' se o ponto 1u à frente do centro dela não está dentro de outro brush
    visível (mundo, detail ou entidade) e o primeiro voxel vazio à frente pertence a área jogável."""
    coverers = [s for s in v.brushes if _visible(s)] + [s for e in v.entities for s in e.solids if _visible(s)]
    B = 256.0
    buckets: dict[tuple, list] = defaultdict(list)
    for s in coverers:
        lo, hi = s.get_bbox()
        for bx in range(int(lo.x // B), int(hi.x // B) + 1):
            for by in range(int(lo.y // B), int(hi.y // B) + 1):
                for bz in range(int(lo.z // B), int(hi.z // B) + 1):
                    buckets[(bx, by, bz)].append(s)
    owners = list(v.brushes) + [s for e in v.entities for s in e.solids if e["classname"] == "func_detail"]
    n = 0
    for s in owners:
        if not any(side.mat.lower() == NODRAW for side in s.sides):
            continue
        for side, poly in geom.face_polys(s):
            if side.mat.lower() != NODRAW or len(poly) < 3:
                continue
            nrm, _ = geom.outward(side)
            c = geom.centroid(poly)
            q = c + nrm * 1.0
            key = (int(q.x // B), int(q.y // B), int(q.z // B))
            if any(o is not s and o.point_inside(q) for o in buckets.get(key, ())):
                continue
            lab = 0
            for k in (0.6, 1.2, 1.8, 2.4):
                i = idx(c + nrm * (vs * k))
                if i is None:
                    break
                lab = labels[i]
                if lab:
                    break
            if lab and lab in playable:
                n += 1
                ori = "topo" if nrm.z > 0.7 else "fundo" if nrm.z < -0.7 else "lateral"
                rep.add("aviso", "nodraw", f"face nodraw ({ori}) dá pra área jogável (solid {s.id}, face {side.id})", c, group=ori)
    return n


def _bfs_out(labels, outside, start, origin, vs) -> list[Vec]:
    """Caminho em voxels da entidade até a borda da grade (pointfile)."""
    import numpy as np
    from collections import deque
    shape = labels.shape
    prev = {start: None}
    dq = deque([start])
    end = None
    while dq:
        c = dq.popleft()
        if 0 in c or any(c[k] == shape[k] - 1 for k in range(3)):
            end = c
            break
        for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
            nb = (c[0] + d[0], c[1] + d[1], c[2] + d[2])
            if nb in prev or labels[nb] != outside:
                continue
            prev[nb] = c
            dq.append(nb)
    path = []
    c = end
    while c is not None:
        path.append(Vec(*(np.array(c) + 0.5) * vs + origin))
        c = prev[c]
    return list(reversed(path))


# --------------------------------------------------------------------------- saída
LABELS = {
    "markers": "marcadores incompletos", "outputs": "outputs órfãos", "textures": "texturas inexistentes",
    "models": "modelos", "leak": "leak", "nodraw": "nodraw visível", "duplicates": "brushes duplicados",
    "overlaps": "brushes sobrepostos", "grid": "fora do grid",
}


def format_report(rep: Report, max_per: int = 15) -> str:
    out = []
    for level in ("erro", "aviso"):
        items = [i for i in rep.issues if i.level == level]
        if not items:
            continue
        out.append(f"{'ERROS' if level == 'erro' else 'AVISOS'} ({len(items)})")
        by = defaultdict(list)
        for i in items:
            by[i.check].append(i)
        for chk in ALL_CHECKS:
            if chk not in by:
                continue
            lst = by[chk]
            out.append(f"  [{LABELS[chk]}] {len(lst)}")
            groups = defaultdict(int)
            for i in lst:
                if i.group:
                    groups[i.group] += 1
            if len(lst) > max_per and groups:
                top = sorted(groups.items(), key=lambda kv: -kv[1])
                out.append("    por pasta: " + ", ".join(f"{g} ({c})" for g, c in top[:12]) + (f", +{len(top) - 12} pastas" if len(top) > 12 else ""))
            for i in lst[:max_per]:
                where = f"  @ {round(i.pos.x)} {round(i.pos.y)} {round(i.pos.z)}" if i.pos is not None else ""
                out.append(f"    - {i.msg}{where}")
            if len(lst) > max_per:
                out.append(f"    ... +{len(lst) - max_per}")
    for chk, why in rep.skipped.items():
        out.append(f"(pulado: {LABELS[chk]} — {why})")
    if rep.stats:
        out.append("(" + ", ".join(f"{k}: {v}" for k, v in rep.stats.items()) + ")")
    out.append(f"{len(rep.errors)} erro(s), {len(rep.issues) - len(rep.errors)} aviso(s)")
    return "\n".join(out)


def write_pointfile(path: Path, pts: list[Vec]) -> None:
    """Formato .lin do vbsp (Hammer: Map > Load Pointfile)."""
    path.write_text("".join(f"{p.x:.6f} {p.y:.6f} {p.z:.6f}\n" for p in pts))


# --------------------------------------------------------------------------- relatório HTML
def write_html(rep: Report, path: Path, map_name: str) -> Path:
    """Página com as texturas faltando: uso, pasta e até MAX_EXAMPLES localizações (com botão de copiar
    `setpos` pro console do jogo e as coordenadas pro Hammer: Ctrl+Shift+G)."""
    from html import escape
    from datetime import datetime
    items = sorted((i for i in rep.issues if i.check == "textures"), key=lambda i: (-i.count, i.name))
    folders = defaultdict(lambda: [0, 0])
    for i in items:
        folders[i.group][0] += 1
        folders[i.group][1] += i.count
    total_uses = sum(i.count for i in items)

    def coord(p):
        return f"{p.x:.0f} {p.y:.0f} {p.z:.0f}"

    rows = []
    for i in items:
        ex = "".join(
            f'<li><code>{escape(coord(p))}</code><span class="d">{escape(d)}</span>'
            f'<button data-copy="setpos {escape(coord(p + Vec(0, 0, 64)))}" title="copiar setpos (64u acima)">setpos</button>'
            f'<button data-copy="{escape(coord(p))}" title="copiar coordenadas (Hammer: Ctrl+Shift+G)">xyz</button></li>'
            for p, d in i.examples)
        more = f'<li class="more">+{i.count - len(i.examples)} uso(s)</li>' if i.count > len(i.examples) else ""
        rows.append(
            f'<tr data-folder="{escape(i.group)}" data-name="{escape(i.name)}">'
            f'<td class="mat"><code>{escape(i.name)}</code></td><td class="folder">{escape(i.group)}</td>'
            f'<td class="n">{i.count}</td><td><ul>{ex}{more}</ul></td></tr>')
    chips = "".join(
        f'<button class="chip" data-folder="{escape(f)}">{escape(f)} <b>{n}</b></button>'
        for f, (n, u) in sorted(folders.items(), key=lambda kv: -kv[1][1]))
    skipped = f'<p class="warn">Checagem pulada: {escape(rep.skipped["textures"])}</p>' if "textures" in rep.skipped else ""
    body = (f'<table><thead><tr><th>Material</th><th>Pasta</th><th class="n">Usos</th><th>Onde (até {MAX_EXAMPLES})</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>') if items else '<p class="ok">Nenhuma textura faltando.</p>'
    html = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Texturas faltando</title>
<style>
:root {{ --bg:#f7f7f5; --fg:#1d1d1b; --muted:#6b6b66; --card:#fff; --line:#e3e2de; --accent:#c2410c; --chip:#efeeea; --code:#f1f0ec; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#161615; --fg:#ecebe7; --muted:#9a9993; --card:#1f1f1d; --line:#2e2e2b; --accent:#fb923c; --chip:#2a2a27; --code:#262624; }} }}
:root[data-theme="dark"] {{ --bg:#161615; --fg:#ecebe7; --muted:#9a9993; --card:#1f1f1d; --line:#2e2e2b; --accent:#fb923c; --chip:#2a2a27; --code:#262624; }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:1200px; margin:0 auto; padding:24px 16px 48px; }}
h1 {{ font-size:22px; margin:0 0 4px }} .sub {{ color:var(--muted); margin:0 0 20px }}
.stats {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:16px }}
.stat {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 14px }}
.stat b {{ display:block; font-size:22px; color:var(--accent) }} .stat span {{ color:var(--muted); font-size:13px }}
.tools {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin:8px 0 14px }}
input[type=search] {{ flex:1 1 240px; padding:8px 10px; border-radius:8px; border:1px solid var(--line); background:var(--card); color:var(--fg); font:inherit }}
.chips {{ display:flex; gap:6px; flex-wrap:wrap; margin-bottom:14px }}
.chip {{ border:1px solid var(--line); background:var(--chip); color:var(--fg); border-radius:999px; padding:4px 10px; cursor:pointer; font:inherit; font-size:13px }}
.chip.on {{ border-color:var(--accent); color:var(--accent) }}
.tablewrap {{ overflow-x:auto; background:var(--card); border:1px solid var(--line); border-radius:10px }}
table {{ width:100%; border-collapse:collapse; min-width:720px }}
th, td {{ text-align:left; padding:10px 12px; border-bottom:1px solid var(--line); vertical-align:top }}
th {{ font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); position:sticky; top:0; background:var(--card) }}
td.n, th.n {{ text-align:right; font-variant-numeric:tabular-nums; width:70px }}
td.mat code {{ font-weight:600 }} td.folder {{ color:var(--muted); white-space:nowrap }}
code {{ font-family:ui-monospace,"JetBrains Mono",monospace; font-size:13px; background:var(--code); padding:1px 5px; border-radius:4px }}
ul {{ list-style:none; margin:0; padding:0; display:grid; gap:4px }}
li {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap }}
li .d {{ color:var(--muted); font-size:12px }} li.more {{ color:var(--muted); font-size:12px }}
li button {{ border:1px solid var(--line); background:transparent; color:var(--fg); border-radius:6px; padding:1px 7px; font-size:12px; cursor:pointer }}
li button:hover {{ border-color:var(--accent); color:var(--accent) }}
.ok {{ padding:16px }} .warn {{ color:var(--accent) }}
#toast {{ position:fixed; bottom:16px; left:50%; transform:translateX(-50%); background:var(--fg); color:var(--bg); padding:6px 12px; border-radius:8px; opacity:0; transition:opacity .2s; font-size:13px }}
</style></head><body><main>
<h1>Texturas faltando</h1>
<p class="sub"><code>{escape(map_name)}</code> · {escape(datetime.now().strftime("%d/%m/%Y %H:%M"))} · fontes: {escape(str(rep.stats.get("recursos", "")))}</p>
{skipped}
<div class="stats"><div class="stat"><b>{len(items)}</b><span>materiais faltando</span></div>
<div class="stat"><b>{total_uses}</b><span>usos (faces, overlays, decals)</span></div>
<div class="stat"><b>{len(folders)}</b><span>pastas</span></div></div>
<div class="tools"><input type="search" id="q" placeholder="Filtrar por nome ou pasta"></div>
<div class="chips">{chips}</div>
<div class="tablewrap">{body}</div>
<p class="sub" style="margin-top:14px">Em cada localização: <b>setpos</b> copia um comando pro console do jogo (64u acima da face); <b>xyz</b> copia as coordenadas pro Hammer++ (Ctrl+Shift+G, "Go to coordinates").</p>
</main><div id="toast">copiado</div>
<script>
const q = document.getElementById('q'), rows = [...document.querySelectorAll('tbody tr')];
let folder = '';
function apply() {{
  const t = q.value.toLowerCase();
  rows.forEach(r => r.hidden = !((!folder || r.dataset.folder === folder) && (!t || r.dataset.name.includes(t) || r.dataset.folder.includes(t))));
}}
q.addEventListener('input', apply);
document.querySelectorAll('.chip').forEach(c => c.addEventListener('click', () => {{
  folder = folder === c.dataset.folder ? '' : c.dataset.folder;
  document.querySelectorAll('.chip').forEach(x => x.classList.toggle('on', x.dataset.folder === folder)); apply();
}}));
const toast = document.getElementById('toast');
document.addEventListener('click', e => {{
  const b = e.target.closest('button[data-copy]'); if (!b) return;
  const txt = b.dataset.copy;
  const done = () => {{ toast.textContent = 'copiado: ' + txt; toast.style.opacity = 1; setTimeout(() => toast.style.opacity = 0, 1400); }};
  (navigator.clipboard ? navigator.clipboard.writeText(txt) : Promise.reject()).then(done).catch(() => {{
    const a = document.createElement('textarea'); a.value = txt; document.body.appendChild(a); a.select();
    try {{ document.execCommand('copy'); done(); }} catch (_) {{}} a.remove();
  }});
}});
</script></body></html>"""
    path = Path(path)
    path.write_text(html, encoding="utf-8")
    return path

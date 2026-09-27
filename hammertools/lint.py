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
  tjunctions  ranking das faces com mais t-junctions (as que mais gastam índices quando o vbsp corrige;
              limite 65536 -> "Too many t-junctions to fix up!")                    (aviso)

Recursos do jogo (materiais/modelos) vêm de `Resources`: ou dos VPKs do jogo (`--game`, HT_GAME, ou a
instalação padrão do GMod), ou injetados nos testes.
"""
from __future__ import annotations

import os
import re
import struct
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from srctools import VMF, Vec
from srctools.vmf import Entity, Solid

from hammertools.core import geom
from hammertools.core import vmf as vmfio

MAX_EXAMPLES = 5
ALL_CHECKS = ("markers", "outputs", "textures", "models", "leak", "nodraw", "duplicates", "overlaps", "grid", "tjunctions")

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
                    info = {"static": bool(flags & 0x10)}  # STUDIOHDR_FLAGS_STATIC_PROP
                    # studiohdr_t: hull_min/max em 104/116, view_bbmin/max em 128/140 (view zerado = usa o hull)
                    hull = struct.unpack_from("<6f", head, 104)
                    view = struct.unpack_from("<6f", head, 128)
                    box = view if any(view) else hull
                    if any(box):
                        info["mins"], info["maxs"] = Vec(*box[:3]), Vec(*box[3:])
                    model_cache[key] = info
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
    locations: list = field(default_factory=list)  # todas as ocorrências [(Vec, "descrição")] (pra agrupar por região)


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)   # checagem -> motivo
    leak_path: list[Vec] = field(default_factory=list)
    stats: dict[str, object] = field(default_factory=dict)
    data: dict[str, object] = field(default_factory=dict)      # dados estruturados pro relatório HTML
    ran: set = field(default_factory=set)                      # checagens que rodaram

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
    rep.ran = set(checks)

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
                            ex[0][0] if ex else None, group=_folder(mat), name=mat, count=len(users), examples=ex,
                            locations=_texture_locations(users))

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
                    rep.add("erro", "models", f"{e['classname']}: modelo inexistente '{mdl}'", _origin(e), group=_folder(mdl.lower().removeprefix("models/"), 2), name=mdl.lower())
                elif e["classname"] == "prop_static" and not info.get("static", True):
                    rep.add("aviso", "models", f"prop_static com modelo que não é static prop '{mdl}' (vira prop_dynamic ou some)", _origin(e), name=mdl.lower())

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

    if "tjunctions" in checks:
        _tjunctions(v, rep)

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


def _texture_locations(users: list) -> list:
    """Todas as ocorrências: centro de cada face (ou origem do overlay/decal)."""
    out = []
    polys: dict[int, dict] = {}
    for obj, side, owner in users:
        if side is None:
            p = _origin(obj)
            if p is not None:
                out.append((p, f"{obj['classname']} (id {obj.id})"))
            continue
        if id(obj) not in polys:
            polys[id(obj)] = {id(sd): pl for sd, pl in geom.face_polys(obj)}
        poly = polys[id(obj)].get(id(side))
        p = geom.centroid(poly) if poly else _center(obj)
        out.append((p, f"{'mundo' if owner is None else owner['classname']} · solid {obj.id} · face {side.id}"))
    return out


def cluster_locations(items: list, radius: float = 256.0) -> list[dict]:
    """Agrupa ocorrências próximas (ligação simples: dois pontos a <= radius ficam no mesmo grupo), misturando
    materiais diferentes. items = [(nome, Vec, desc)]. Devolve grupos ordenados por quantidade."""
    from collections import Counter
    n = len(items)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    cells: dict[tuple, list[int]] = defaultdict(list)
    for i, (_, p, _) in enumerate(items):
        cells[(int(p.x // radius), int(p.y // radius), int(p.z // radius))].append(i)
    r2 = radius * radius
    for (cx, cy, cz), idxs in cells.items():
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    other = cells.get((cx + dx, cy + dy, cz + dz))
                    if not other:
                        continue
                    for i in idxs:
                        pi = items[i][1]
                        for j in other:
                            if j <= i:
                                continue
                            pj = items[j][1]
                            if (pi.x - pj.x) ** 2 + (pi.y - pj.y) ** 2 + (pi.z - pj.z) ** 2 <= r2:
                                a, b = find(i), find(j)
                                if a != b:
                                    parent[a] = b
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)
    out = []
    for idxs in groups.values():
        pts = [items[i][1] for i in idxs]
        center = sum(pts, Vec()) / len(pts)
        lo = Vec(min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))
        hi = Vec(max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))
        mats = Counter(items[i][0] for i in idxs)
        near = sorted(idxs, key=lambda i: (items[i][1] - center).mag())  # exemplos: os mais próximos do centro
        out.append({"count": len(idxs), "center": center, "lo": lo, "hi": hi, "materials": mats.most_common(),
                    "examples": [(items[i][1], f"{items[i][0]} · {items[i][2]}") for i in near[:MAX_EXAMPLES]]})
    out.sort(key=lambda g: (-g["count"], -len(g["materials"])))
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


# --------------------------------------------------------------------------- t-junctions
MAX_PRIMINDICES = 65536


def _tjunctions(v: VMF, rep: Report, top: int = 40, eps: float = 0.1) -> None:
    """Estimativa: vértice de uma face que cai no MEIO da aresta de outra face é uma t-junction; o vbsp
    divide essa face em triângulos (primitivas) e gasta (n_vértices - 2) * 3 índices. Soma o total e lista
    as faces que mais gastam. É uma aproximação (o vbsp faz CSG antes), mas a ordem das piores é o que
    importa pra decidir onde simplificar."""
    faces = []   # (solid, side, poly, dono)
    for s in v.brushes:
        if any(sd.is_disp for sd in s.sides):
            continue
        for side, poly in geom.face_polys(s):
            if len(poly) >= 3 and not side.mat.lower().startswith("tools/"):
                faces.append((s, side, poly, "mundo"))
    for e in v.entities:
        if e["classname"] != "func_detail":
            continue
        for s in e.solids:
            for side, poly in geom.face_polys(s):
                if len(poly) >= 3 and not side.mat.lower().startswith("tools/"):
                    faces.append((s, side, poly, "func_detail"))
    C = 64.0
    cells: dict[tuple, dict] = defaultdict(dict)   # célula -> {vértice: (solid id, dono)}
    for s, _, poly, owner in faces:
        for p in poly:
            q = (round(p.x, 1), round(p.y, 1), round(p.z, 1))
            cells[(int(q[0] // C), int(q[1] // C), int(q[2] // C))].setdefault(q, (s.id, owner))
    total = 0
    scored = []
    for s, side, poly, owner in faces:
        corners = {(round(p.x, 1), round(p.y, 1), round(p.z, 1)) for p in poly}
        extra = 0
        points = []
        for k in range(len(poly)):
            a, b = poly[k], poly[(k + 1) % len(poly)]
            d = b - a
            L = d.mag()
            if L < 1:
                continue
            u = d / L
            lo = (min(a.x, b.x), min(a.y, b.y), min(a.z, b.z))
            hi = (max(a.x, b.x), max(a.y, b.y), max(a.z, b.z))
            for cx in range(int(lo[0] // C), int(hi[0] // C) + 1):
                for cy in range(int(lo[1] // C), int(hi[1] // C) + 1):
                    for cz in range(int(lo[2] // C), int(hi[2] // C) + 1):
                        for q, (sid, own) in cells.get((cx, cy, cz), {}).items():
                            if q in corners:
                                continue
                            w = Vec(*q) - a
                            t = w.dot(u)
                            if eps < t < L - eps and (w - u * t).mag() < eps:
                                extra += 1
                                if len(points) < MAX_EXAMPLES:
                                    points.append((Vec(*q), f"vértice do {own} solid {sid}"))
        if extra:
            idx = (len(poly) + extra - 2) * 3
            total += idx
            scored.append((idx, extra, s, side, poly, owner, points))
    scored.sort(key=lambda t: -t[0])
    # a soma é teto (o vbsp faz CSG e só triangula o que não fecha em leque), então vale como ranking, não
    # como veredito. O "N indices" do erro do vbsp é onde ele parou ao estourar, não o total do mapa.
    rep.stats["t-junctions: índices estimados (teto)"] = f"{total} (limite do vbsp {MAX_PRIMINDICES})"
    rep.stats["faces com t-junction"] = len(scored)
    rep.data["tjunctions"] = [{"idx": idx, "extra": extra, "solid": s.id, "face": side.id, "mat": side.mat, "owner": owner,
                               "center": geom.centroid(poly), "points": pts} for idx, extra, s, side, poly, owner, pts in scored]
    rep.data["tjunctions_total"] = total
    for idx, extra, s, side, poly, owner, _ in scored[:top]:
        rep.add("aviso", "tjunctions", f"{owner} solid {s.id} face {side.id} ({side.mat}): {extra} vértice(s) de vizinhos nas arestas, ~{idx} índices",
                geom.centroid(poly), group=owner)


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
        n = _nodraw(v, rep, labels, playable, idx, vs, res)
        rep.stats["nodraw visíveis"] = n


def _ray_entry(planes, o: Vec, d: Vec) -> float | None:
    """Distância em que o raio o + t·d (t > 0) entra no convexo dado pelos planos (normal pra fora, ponto)."""
    t0, t1 = 0.0, float("inf")
    for n, p in planes:
        den = n.dot(d)
        dist = n.dot(o - p)
        if abs(den) < 1e-9:
            if dist > 1e-4:
                return None
            continue
        t = -dist / den
        if den < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return None
    return t0


# entidades que não marcam lugar onde o jogador vê: cordas cruzam céu e vãos, landmark/lógica ficam em qualquer canto
NOT_VIEWERS = ("ht_", "logic_", "point_template", "info_overlay", "infodecal", "env_cubemap", "sky_camera",
               "info_landmark", "keyframe_rope", "move_rope", "math_", "filter_", "game_", "ai_", "env_fog_controller",
               "env_tonemap_controller", "shadow_control", "env_sun", "light_environment", "func_")
BLOCK_TOOLS = {"tools/toolsnodraw", "tools/toolsskybox", "tools/toolsskybox2d", "tools/toolsblack", "tools/toolsblocklight"}
VIEW_RANGE = 3000.0
PROP_TOO_CLOSE = 64.0  # prop colado na face: o próprio modelo costuma tampar o nodraw
EXPOSED_MIN = 0.25    # fração mínima das amostras da face descobertas pra ela contar como exposta
SCENERY_SIZE = 256.0   # prop maior que isso (árvore gigante, torre) é cenário: a origem não é onde o jogador fica


def _nodraw(v: VMF, rep: Report, labels, playable: set, idx, vs: float, res: Resources | None = None) -> int:
    """Face nodraw é 'visível' se o ponto 1u à frente do centro dela não está dentro de outro brush
    visível (mundo, detail ou entidade) e o espaço LIVRE à frente (até o primeiro brush que o raio acerta)
    pertence a área jogável. A sonda nunca passa do primeiro brush: antes ela atravessava o piso de baixo
    e achava a sala embaixo dele (falso positivo em laje sobre vão fechado).
    Confirmação: alguma entidade pontual (spawn, luz, prop de até 256u, npc, porta...) fora de sólidos e a até 3000u
    tem linha de visada até a face. Sem isso, vão fechado grande (debaixo do terreno, dentro da caixa de
    skybox) contava como jogável só por estar do lado de dentro do selo.
    Displacement bloqueia a visada pela superfície (triângulos), não pelo brush-base: o terreno pode ficar
    longe do brush e a árvore em cima do chão "via" a caixa de nodraw debaixo do mapa.
    A cobertura é testada em várias amostras da face (não só no centro); exposta = pelo menos 25% descobertas.
    Brush translúcido (vidro, água) com face nodraw não acusa: o vbsp não o trata como sólido e a face
    nodraw só deixa ver através dele (vidro de janela com o lado de dentro nodraw).
    Props tampam: se um ponto a 2, 8 ou 16u à frente da face cai dentro da caixa (girada) de um prop, a face está
    escondida pelo modelo (ex.: batente nodraw atrás do modelo de janela que preenche o vão)."""
    coverers = [s for s in v.brushes if _visible(s)] + [s for e in v.entities for s in e.solids if _visible(s)]
    B = 256.0
    buckets: dict[tuple, list] = defaultdict(list)
    for s in coverers:
        lo, hi = s.get_bbox()
        for bx in range(int(lo.x // B), int(hi.x // B) + 1):
            for by in range(int(lo.y // B), int(hi.y // B) + 1):
                for bz in range(int(lo.z // B), int(hi.z // B) + 1):
                    buckets[(bx, by, bz)].append(s)
    plane_cache: dict[int, list] = {}

    def planes(o: Solid):
        if id(o) not in plane_cache:
            plane_cache[id(o)] = [geom.outward(side) for side in o.sides]
        return plane_cache[id(o)]

    blockers: dict[tuple, list] = defaultdict(list)
    tris: dict[tuple, list] = defaultdict(list)  # terreno: a superfície do displacement, não o brush-base
    for b in v.brushes:
        if any(x.is_disp for x in b.sides):
            for t in geom.disp_triangles(b):
                lo = Vec(min(p.x for p in t), min(p.y for p in t), min(p.z for p in t))
                hi = Vec(max(p.x for p in t), max(p.y for p in t), max(p.z for p in t))
                for bx in range(int(lo.x // B), int(hi.x // B) + 1):
                    for by in range(int(lo.y // B), int(hi.y // B) + 1):
                        for bz in range(int(lo.z // B), int(hi.z // B) + 1):
                            tris[(bx, by, bz)].append(t)
    for o in [c for c in coverers if not any(x.is_disp for x in c.sides)] + [
            b for b in v.brushes if not _visible(b) and all(x.mat.lower() in BLOCK_TOOLS for x in b.sides)]:
        lo, hi = o.get_bbox()
        for bx in range(int(lo.x // B), int(hi.x // B) + 1):
            for by in range(int(lo.y // B), int(hi.y // B) + 1):
                for bz in range(int(lo.z // B), int(hi.z // B) + 1):
                    blockers[(bx, by, bz)].append(o)

    def cell(p: Vec) -> tuple:
        return (int(p.x // B), int(p.y // B), int(p.z // B))

    def clear(a: Vec, b: Vec, skip: Solid) -> bool:
        d = b - a
        length = d.mag()
        d = d / length
        seen: set[int] = set()
        t = 0.0
        while t <= length + B:
            k = cell(a + d * min(t, length))
            for o in blockers.get(k, ()):
                if o is skip or id(o) in seen:
                    continue
                seen.add(id(o))
                hit = _ray_entry(planes(o), a, d)
                if hit is not None and hit < length - 0.5:
                    return False
            for tri in tris.get(k, ()):
                if id(tri) in seen:
                    continue
                seen.add(id(tri))
                hit = geom.ray_triangle(a, d, tri)
                if hit is not None and hit < length - 0.5:
                    return False
            t += B / 4
        return True

    viewers: list[tuple[Vec, str]] = []
    for e in v.entities:
        cls = e["classname"]
        o = _origin(e)
        if e.solids or o is None or cls.startswith(NOT_VIEWERS):
            continue
        if any(b.point_inside(o) for b in blockers.get(cell(o), ())):
            continue  # origem enterrada em sólido não enxerga nada
        if cls.startswith("prop_") and res is not None and res.model_info is not None and e.get("model"):
            info = res.model_info(e["model"])
            if info and "mins" in info:
                size = info["maxs"] - info["mins"]
                if max(size.x, size.y, size.z) * float(e.get("modelscale", 1) or 1) > SCENERY_SIZE:
                    continue
        viewers.append((o, cls))

    props: dict[tuple, list] = defaultdict(list)
    if res is not None and res.model_info is not None:
        from srctools import Angle, Matrix
        for e in v.entities:
            if not e["classname"].startswith("prop_") or not e.get("model", "").lower().endswith(".mdl"):
                continue
            info = res.model_info(e["model"])
            o = _origin(e)
            if not info or "mins" not in info or o is None:
                continue
            try:
                inv = Matrix.from_angle(Angle.from_str(e.get("angles", "0 0 0"))).inverse()
                scale = float(e.get("modelscale", 1) or 1)
            except ValueError:
                continue
            lo, hi = info["mins"] * scale, info["maxs"] * scale
            r = max(lo.mag(), hi.mag())
            item = (o, inv, lo - Vec(1, 1, 1), hi + Vec(1, 1, 1))
            for bx in range(int((o.x - r) // B), int((o.x + r) // B) + 1):
                for by in range(int((o.y - r) // B), int((o.y + r) // B) + 1):
                    for bz in range(int((o.z - r) // B), int((o.z + r) // B) + 1):
                        props[(bx, by, bz)].append(item)

    def under_prop(p: Vec) -> bool:
        for o, inv, lo, hi in props.get((int(p.x // B), int(p.y // B), int(p.z // B)), ()):
            q = (p - o) @ inv
            if lo.x <= q.x <= hi.x and lo.y <= q.y <= hi.y and lo.z <= q.z <= hi.z:
                return True
        return False

    reach = 2.4 * vs
    owners = list(v.brushes) + [s for e in v.entities for s in e.solids if e["classname"] == "func_detail"]
    n = 0
    seals = res.material_seals if res is not None else None
    for s in owners:
        if not any(side.mat.lower() == NODRAW for side in s.sides):
            continue
        # brush translúcido/água (vidro com um lado nodraw): não é sólido pro vbsp, a face nodraw só deixa
        # ver através dele o que está atrás; o buraco pro vazio (hall of mirrors) só existe em brush opaco
        if seals is not None and any(not x.mat.lower().startswith("tools/") and not seals(x.mat) for x in s.sides):
            continue
        for side, poly in geom.face_polys(s):
            if side.mat.lower() != NODRAW or len(poly) < 3:
                continue
            nrm, _ = geom.outward(side)
            # amostras espalhadas pela face (centro + 1/3 e 2/3 do caminho até cada vértice): um ponto só no centro
            # falha quando o centro cai numa quina (rampa nodraw embaixo de degraus, que só encostam nas quinas)
            ctr = geom.centroid(poly)
            samples = [ctr] + [ctr + (vx - ctr) * t for vx in poly for t in (1 / 3, 2 / 3)]

            def exposed(pt: Vec) -> bool:
                q = pt + nrm * 1.0
                if any(o is not s and o.point_inside(q) for o in buckets.get((int(q.x // B), int(q.y // B), int(q.z // B)), ())):
                    return False
                # modelo encostado ou a até 16u (piso do modelo do elevador 5u acima do brush)
                return not any(under_prop(pt + nrm * d) for d in (2.0, 8.0, 16.0))

            open_pts = [pt for pt in samples if exposed(pt)]
            if len(open_pts) < max(1, EXPOSED_MIN * len(samples)):
                continue
            c = open_pts[0]
            q = c + nrm * 1.0
            # primeiro brush que o raio acerta dentro do alcance da sonda
            cand: dict[int, Solid] = {}
            t = 0.0
            while t <= reach + B:
                p = c + nrm * t
                for o in buckets.get((int(p.x // B), int(p.y // B), int(p.z // B)), ()):
                    if o is not s:
                        cand[id(o)] = o
                t += B / 2
            free = reach
            for o in cand.values():
                hit = _ray_entry(planes(o), q, nrm)
                if hit is not None:
                    free = min(free, hit + 1.0)
            lab = 0
            for k in (0.6, 1.2, 1.8, 2.4):
                if vs * k >= free:
                    break
                i = idx(c + nrm * (vs * k))
                if i is None:
                    break
                lab = labels[i]
                if lab:
                    break
            if not (lab and lab in playable):
                continue
            tgt = c + nrm * 2.0
            near = sorted(((o, cls) for o, cls in viewers if (o - tgt).dot(nrm) > 1 and (o - tgt).mag() < VIEW_RANGE
                           and not (cls.startswith("prop_") and (o - tgt).mag() < PROP_TOO_CLOSE)),
                          key=lambda oc: (oc[0] - tgt).mag())[:60]
            seer = next(((o, cls) for o, cls in near if clear(o, tgt, s)), None)
            if seer is None:
                continue
            n += 1
            ori = "topo" if nrm.z > 0.7 else "fundo" if nrm.z < -0.7 else "lateral"
            rep.add("aviso", "nodraw", f"face nodraw ({ori}) à vista (solid {s.id}, face {side.id}): "
                    f"{seer[1]} a {(seer[0] - tgt).mag():.0f}u enxerga", c, group=ori)
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
    "overlaps": "brushes sobrepostos", "grid": "fora do grid", "tjunctions": "t-junctions",
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
def write_html(rep: Report, path: Path, map_name: str, cluster_radius: float = 256.0, area_size: float = 1024.0) -> Path:
    """Relatório geral (hammertools.report): painel de prioridades + uma aba por checagem, filtro/agrupamento por área."""
    from hammertools import report
    return report.write(rep, path, map_name, cluster_radius, area_size)

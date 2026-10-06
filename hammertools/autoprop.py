"""Auto-prop (Propper automático do ht-vbsp): tira geometria de detail do BSP para caber nos tetos do vbsp.

O BSP do GMod tem dois tetos de 16 bits que um mapa grande encosta ao mesmo tempo: vértices únicos e índices de
t-junction (65536 cada). Converter func_detail em func_brush resolve t-junction gastando vértice; sem folga de
vértice, não existe ponto que caiba nos dois. Um prop_static sai das duas contas: as faces viram modelo (luz por
vértice no vrad -StaticPropLighting), a colisão vira casco convexo por brush.

Fluxo (só no build/, o fonte não muda):
1. estimativa do mapa: índices de t-junction (a do lint) e vértices únicos (posições das faces visíveis), cada uma
   reescalada pela calibração aprendida nas compilações anteriores (real / estimativa);
2. candidatos: solids de func_detail pequenos (maior face <= MAX_FACE_AREA, maior lado <= MAX_SIZE) com materiais que
   funcionam em modelo (sem água, refração, blend de displacement, céu); agrupados por célula de CELL unidades;
3. escolha gulosa pelo custo (índices + vértices liberados) até as duas contas ficarem em GOAL do teto;
4. cada grupo vira SMD (faces visíveis, UV dos eixos de textura) + SMD de colisão (uma peça convexa por brush) +
   QC $staticprop, compilado pelo studiomdl do jogo (pelo Wine fora do Windows), em paralelo e com cache por hash;
5. os solids saem do build/ e entra um prop_static no lugar.
"""
from __future__ import annotations

import hashlib
import os
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from srctools import Vec
from srctools.vmf import VMF, Entity, Solid

from hammertools.core import geom

LIMIT = 65536
GOAL = 0.90
CELL = 512.0
MAX_FACE_AREA = 192.0 * 192.0
MAX_SIZE = 512.0
CALIB_IDX = 0.6          # índices reais / estimativa do lint, sem histórico (a estimativa é teto; ~0.4-0.6 na prática)
CALIB_VERTS = 1.0
SKIP_SHADERS = {"water", "refract", "worldvertextransition", "lightmapped_4wayblend", "sky", "decalmodulate",
                "worldtwotextureblend", "spritecard", "cable"}
MODEL_DIR = "ht_prop"


# --------------------------------------------------------------------------- estimativa
def _visible_faces(v: VMF):
    """(solid, side, polígono) das faces que o vbsp desenha: mundo, func_detail e entidades de brush, sem tools/."""
    for s in v.brushes:
        if any(sd.is_disp for sd in s.sides):
            continue
        yield from ((s, sd, poly) for sd, poly in geom.face_polys(s) if len(poly) >= 3 and not sd.mat.lower().startswith("tools/"))
    for e in v.entities:
        for s in e.solids:
            if any(sd.is_disp for sd in s.sides):
                continue
            yield from ((s, sd, poly) for sd, poly in geom.face_polys(s) if len(poly) >= 3 and not sd.mat.lower().startswith("tools/"))


def _key(p: Vec) -> tuple:
    return round(p.x, 1), round(p.y, 1), round(p.z, 1)


@dataclass
class Estimate:
    idx_total: float                 # índices de t-junction estimados (unidades do lint)
    verts_total: int                 # posições únicas das faces visíveis
    idx_cost: dict = field(default_factory=dict)     # solid id -> índices que saem com ele
    vert_cost: dict = field(default_factory=dict)    # solid id -> vértices só dele


def estimate(v: VMF) -> Estimate:
    from hammertools import lint
    rep = lint.run(v, lint.Resources(), {"tjunctions"})
    idx_cost: dict[int, float] = defaultdict(float)
    total = 0.0
    for f in rep.data.get("tjunctions", []):
        total += f["idx"]
        idx_cost[f["solid"]] += f["idx"]
        for sid, n in f.get("sources", {}).items():
            idx_cost[int(sid)] += 3 * n
    owners: dict[tuple, set] = defaultdict(set)
    for s, _, poly in _visible_faces(v):
        for p in poly:
            owners[_key(p)].add(s.id)
    vert_cost: Counter = Counter()
    for ids in owners.values():
        if len(ids) == 1:
            vert_cost[next(iter(ids))] += 1
    return Estimate(total, len(owners), dict(idx_cost), dict(vert_cost))


# --------------------------------------------------------------------------- materiais
class Materials:
    """Lê VMTs do jogo (com "patch"/include) e devolve o que o modelo precisa."""

    def __init__(self, res):
        self.res = res
        self._cache: dict[str, dict | None] = {}

    def params(self, mat: str) -> dict | None:
        mat = mat.lower().replace("\\", "/")
        if mat in self._cache:
            return self._cache[mat]
        out = None
        data = self.res.read(f"materials/{mat}.vmt") if self.res.read else None
        if data:
            out = self._parse(data.decode("utf-8", "replace"))
        self._cache[mat] = out
        return out

    def _parse(self, text: str, depth: int = 0) -> dict | None:
        from srctools import Keyvalues
        try:
            # o Source lê VMT sem escapes: "custom_textures\txt_chao" é barra + t, não TAB (com escapes o caminho
            # da textura saía corrompido e o modelo gerado ficava com o xadrez roxo)
            kv = Keyvalues.parse(text, allow_escapes=False)
            root = next(iter(kv), None)
        except Exception:
            root = None
        if root is None:
            return self._loose(text)
        shader = root.real_name.lower()
        params = {}
        if shader == "patch" and depth < 4:
            inc = root["include", ""].replace("\\", "/").lower()
            base = self.res.read(inc) if inc and self.res.read else None
            params = dict(self._parse(base.decode("utf-8", "replace"), depth + 1) or {})
            shader = params.get("shader", "")
            for blk in ("insert", "replace"):
                for kvp in root.find_all(blk):
                    for c in kvp:
                        if not c.has_children():
                            params[c.name.lower()] = c.value
            params["shader"] = shader
            return params
        for c in root:
            if not c.has_children():
                params[c.name.lower()] = c.value
        params["shader"] = shader
        return params

    @staticmethod
    def _loose(text: str) -> dict | None:
        """Leitura tolerante (VMT numa linha só, aspas faltando): shader + pares chave/valor do primeiro nível."""
        m = re.match(r'\s*"?([\w]+)"?\s*\{', text)
        if not m:
            return None
        params = {k.lower(): v for k, v in re.findall(r'"?([$%][\w]+)"?\s+"([^"]*)"', text)}
        params["shader"] = m.group(1).lower()
        return params

    def usable(self, mat: str) -> bool:
        if mat.lower().startswith("tools/"):
            return True          # some do modelo (só na colisão)
        p = self.params(mat)
        return p is not None and p.get("shader", "") not in SKIP_SHADERS and "$basetexture" in p

    def size(self, mat: str) -> tuple[int, int]:
        import struct
        p = self.params(mat) or {}
        tex = p.get("$basetexture", "").replace("\\", "/").lower().removesuffix(".vtf")
        head = self.res.read(f"materials/{tex}.vtf", 32) if tex and self.res.read else None
        if head and head[:4] == b"VTF\0":
            w, h = struct.unpack_from("<HH", head, 16)
            if w and h:
                return w, h
        return 512, 512

    def model_vmt(self, mat: str) -> str:
        """VMT de modelo com a mesma aparência: lightmapped vira VertexLitGeneric, unlit continua unlit."""
        p = self.params(mat) or {}
        shader = "UnlitGeneric" if p.get("shader") == "unlitgeneric" else "VertexLitGeneric"
        keep = ("$basetexture", "$bumpmap", "$surfaceprop", "$translucent", "$alphatest", "$alphatestreference",
                "$color", "$color2", "$envmap", "$envmapmask", "$envmaptint", "$basealphaenvmapmask",
                "$normalmapalphaenvmapmask", "$selfillum", "$nocull", "$detail", "$detailscale", "$detailblendmode")
        lines = [f'"{shader}"', "{"]
        paths = {"$basetexture", "$bumpmap", "$envmapmask", "$detail"}
        for k in keep:
            if k in p and not (shader == "UnlitGeneric" and k == "$bumpmap"):
                v = p[k].replace("\\", "/") if k in paths else p[k]
                lines.append(f'\t"{k}" "{v}"')
        lines.append("}")
        return "\n".join(lines) + "\n"


def safe(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "mat"


# --------------------------------------------------------------------------- escolha
@dataclass
class Cluster:
    cell: tuple
    solids: list = field(default_factory=list)      # (entidade func_detail, solid)
    idx: float = 0.0
    verts: int = 0

    def key(self) -> str:
        h = hashlib.sha1(b"autoprop-v3")     # muda junto com o formato do SMD: modelo velho não é reaproveitado
        for _, s in sorted(self.solids, key=lambda t: t[1].id):
            for sd in s.sides:
                h.update(repr((tuple(map(tuple, sd.planes)), sd.mat.lower(), str(sd.uaxis), str(sd.vaxis))).encode())
        return h.hexdigest()[:12]


def candidates(v: VMF, mats: Materials) -> list[tuple[Entity, Solid]]:
    out = []
    for e in v.by_class["func_detail"]:
        for s in e.solids:
            if any(sd.is_disp for sd in s.sides):
                continue
            polys = geom.face_polys(s)
            vis = [(sd, p) for sd, p in polys if len(p) >= 3 and not sd.mat.lower().startswith("tools/")]
            if not vis:
                continue
            lo, hi = s.get_bbox()
            if max(hi - lo) > MAX_SIZE:
                continue
            if max(_area(p) for _, p in vis) > MAX_FACE_AREA:
                continue
            if not all(mats.usable(sd.mat) for sd, _ in polys):
                continue
            out.append((e, s))
    return out


def _area(poly: list[Vec]) -> float:
    a = Vec()
    for i in range(1, len(poly) - 1):
        a += Vec.cross(poly[i] - poly[0], poly[i + 1] - poly[0])
    return a.mag() / 2


def choose(est: Estimate, cands: list[tuple[Entity, Solid]], calib: float, vcalib: float) -> tuple[list[Cluster], dict]:
    """Grupos a converter, pelo maior custo, até índices e vértices ficarem em GOAL do teto."""
    cells: dict[tuple, Cluster] = {}
    for e, s in cands:
        lo, hi = s.get_bbox()
        c = (lo + hi) / 2
        key = (int(c.x // CELL), int(c.y // CELL), int(c.z // CELL))
        cl = cells.setdefault(key, Cluster(key))
        cl.solids.append((e, s))
        cl.idx += est.idx_cost.get(s.id, 0.0)
        cl.verts += est.vert_cost.get(s.id, 0)
    need_idx = max(0.0, est.idx_total * calib - GOAL * LIMIT) / calib
    need_v = max(0.0, est.verts_total * vcalib - GOAL * LIMIT) / vcalib
    stats = {"idx_est": round(est.idx_total * calib), "verts_est": round(est.verts_total * vcalib),
             "need_idx": round(need_idx * calib), "need_verts": round(need_v * vcalib), "candidatos": len(cands)}
    if need_idx <= 0 and need_v <= 0:
        return [], stats

    def score(cl: Cluster) -> float:
        return (cl.idx / need_idx if need_idx > 0 else 0) + (cl.verts / need_v if need_v > 0 else 0)

    chosen, gi, gv = [], 0.0, 0
    for cl in sorted(cells.values(), key=score, reverse=True):
        if gi >= need_idx and gv >= need_v:
            break
        if score(cl) <= 0:
            break
        chosen.append(cl)
        gi += cl.idx
        gv += cl.verts
    stats["tira_idx"] = round(gi * calib)
    stats["tira_verts"] = round(gv * vcalib)
    stats["suficiente"] = gi >= need_idx and gv >= need_v
    return chosen, stats


# --------------------------------------------------------------------------- modelo
def _smd(p: Vec) -> Vec:
    """O studiomdl gira a referência +90° em Z ((x, y) -> (-y, x), medido nos modelos compilados): o SMD vai girado
    -90° para o modelo sair no lugar com o prop em angles 0 0 0."""
    return Vec(p.y, -p.x, p.z)


def _fmt(x: float) -> str:
    s = f"{x:.6f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def cluster_origin(cl: Cluster) -> Vec:
    """Origem do prop: centro do maior solid do grupo, arredondado. O vbsp testa leak a partir da origem de todo
    prop_static; o centro de um brush de detail nunca é vazio (detail não sela), o centro da caixa do grupo pode ser."""
    def vol(s):
        lo, hi = s.get_bbox()
        d = hi - lo
        return d.x * d.y * d.z
    _, big = max(cl.solids, key=lambda t: vol(t[1]))
    lo, hi = big.get_bbox()
    c = (lo + hi) / 2
    return Vec(round(c.x), round(c.y), round(c.z))


def build_files(cl: Cluster, mats: Materials, map_name: str) -> tuple[Vec, dict[str, str], dict[str, str]]:
    """(origem, arquivos {nome: texto} do SMD/QC, VMTs {nome do material de modelo: texto})."""
    origin = cluster_origin(cl)
    head = "version 1\nnodes\n0 \"root\" -1\nend\nskeleton\ntime 0\n0 0 0 0 0 0 0\nend\ntriangles\n"
    ref, phys = [head], [head]
    vmts: dict[str, str] = {}
    surfprops: Counter = Counter()
    for piece, (_, s) in enumerate(cl.solids, 1):
        for sd, poly in geom.face_polys(s):
            if len(poly) < 3:
                continue
            n, _ = geom.outward(sd)
            loc = [p - origin for p in poly]
            # orientação anti-horária vista de fora (normal do triângulo do mesmo lado da face)
            if Vec.cross(loc[1] - loc[0], loc[2] - loc[0]).dot(n) < 0:
                loc.reverse()
            for k in range(1, len(loc) - 1):
                phys.append("phys\n")
                for p in (loc[0], loc[k], loc[k + 1]):
                    q = _smd(p)
                    phys.append(f"0 {_fmt(q.x)} {_fmt(q.y)} {_fmt(q.z)} 0 0 1 {piece} 0 1 0 1\n")
            mat = sd.mat.lower()
            if mat.startswith("tools/"):
                continue
            mname = safe(mat)
            if mname not in vmts:
                vmts[mname] = mats.model_vmt(mat)
                sp = (mats.params(mat) or {}).get("$surfaceprop")
                if sp:
                    surfprops[sp] += 1
            w, h = mats.size(mat)
            ua, va = sd.uaxis, sd.vaxis
            rn = _smd(n)
            for k in range(1, len(loc) - 1):
                ref.append(mname + "\n")
                for p in (loc[0], loc[k], loc[k + 1]):
                    wp = p + origin
                    u = (wp.dot(Vec(ua.x, ua.y, ua.z)) / ua.scale + ua.offset) / w
                    vv = (wp.dot(Vec(va.x, va.y, va.z)) / va.scale + va.offset) / h
                    q = _smd(p)
                    ref.append(f"0 {_fmt(q.x)} {_fmt(q.y)} {_fmt(q.z)} {_fmt(rn.x)} {_fmt(rn.y)} {_fmt(rn.z)} {_fmt(u)} {_fmt(1 - vv)} 1 0 1\n")
    ref.append("end\n")
    phys.append("end\n")
    name = cl.key()
    folder = f"{MODEL_DIR}/{safe(map_name)}"
    sp = surfprops.most_common(1)[0][0] if surfprops else "default"
    qc = (f'$modelname "{folder}/{name}.mdl"\n$staticprop\n$surfaceprop "{sp}"\n$cdmaterials "models/{folder}/"\n'
          f'$body "body" "ref.smd"\n$sequence "idle" "ref.smd"\n'
          f'$collisionmodel "phys.smd"\n{{\n\t$concave\n\t$maxconvexpieces {max(1, len(cl.solids))}\n\t$mass 100\n}}\n')
    return origin, {"ref.smd": "".join(ref), "phys.smd": "".join(phys), "model.qc": qc}, vmts


def find_studiomdl(real_vbsp: Path) -> Path | None:
    for d in (real_vbsp.parent, real_vbsp.parent.parent / "win64", real_vbsp.parent.parent):
        for n in ("studiomdl.exe", "studiomdl"):
            if (d / n).exists():
                return d / n
    return None


# --------------------------------------------------------------------------- aplicar
def apply(out: Path, gamedir: Path, real_vbsp: Path, calib: float = CALIB_IDX, vcalib: float = CALIB_VERTS,
          log=print, run=None) -> dict:
    """Converte os grupos escolhidos do build/ (out) em prop_static compilados. Devolve o resumo para o registro."""
    import subprocess
    from hammertools import lint
    from hammertools.core import vmf as vmfio
    studiomdl = find_studiomdl(real_vbsp)
    if studiomdl is None:
        log("ht-vbsp: auto-prop: studiomdl não encontrado ao lado do vbsp; pulando.")
        return {"models": 0, "erro": "sem studiomdl"}
    v = vmfio.load(out)
    est = estimate(v)
    res = lint.Resources.from_game(str(gamedir), None, ())
    mats = Materials(res)
    cands = candidates(v, mats)
    chosen, stats = choose(est, cands, calib, vcalib)
    log(f"ht-vbsp: auto-prop: índices ~{stats['idx_est']}, vértices ~{stats['verts_est']} (meta {GOAL:.0%} de {LIMIT}); "
        f"{stats['candidatos']} solids de detail candidatos.")
    if not chosen:
        log("ht-vbsp: auto-prop: nada a converter (já cabe ou não há candidatos).")
        return {"models": 0, **stats}
    map_name = out.stem
    work = out.parent / "ht_prop"
    mat_dir = gamedir / "materials" / "models" / MODEL_DIR / safe(map_name)
    mdl_dir = gamedir / "models" / MODEL_DIR / safe(map_name)
    mat_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for cl in chosen:
        origin, files, vmts = build_files(cl, mats, map_name)
        for mname, text in vmts.items():
            f = mat_dir / f"{mname}.vmt"
            if not f.exists() or f.read_text() != text:
                f.write_text(text)
        name = cl.key()
        d = work / name
        d.mkdir(parents=True, exist_ok=True)
        for fn, text in files.items():
            (d / fn).write_text(text)
        jobs.append((cl, origin, name, d))
    run = run or (lambda cmd, cwd: subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace",
                                                   env=dict(os.environ, WINEDEBUG="-all")).returncode)
    from hammertools.cli import _wine_cmd

    def compile_one(job) -> bool:
        cl, origin, name, d = job
        mdl = mdl_dir / f"{name}.mdl"
        if mdl.exists():
            return True     # mesmo hash = mesmo conteúdo: já compilado
        cmd = _wine_cmd([str(studiomdl), "-game", str(gamedir), "-nop4", "-nox360", str(d / "model.qc")])
        run(cmd, str(d))
        return mdl.exists()

    todo = sum(1 for j in jobs if not (mdl_dir / f"{j[2]}.mdl").exists())
    log(f"ht-vbsp: auto-prop: {len(jobs)} grupo(s) -> prop_static ({todo} para compilar no studiomdl, o resto do cache)...")
    with ThreadPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) // 2)) as pool:
        ok = list(pool.map(compile_one, jobs))
    made = 0
    for (cl, origin, name, _), good in zip(jobs, ok):
        if not good:
            continue
        for e, s in cl.solids:
            e.solids.remove(s)
            if not e.solids:
                v.remove_ent(e)
        v.add_ent(Entity(v, {"classname": "prop_static", "model": f"models/{MODEL_DIR}/{safe(map_name)}/{name}.mdl",
                             "origin": f"{origin.x:g} {origin.y:g} {origin.z:g}", "angles": "0 0 0", "solid": "6",
                             "skin": "0", "fademindist": "-1", "fadescale": "1", "disableshadows": "0"}))
        made += 1
    vmfio.save(v, out)
    failed = len(jobs) - made
    log(f"ht-vbsp: auto-prop: {made} prop_static no lugar de {sum(len(c.solids) for c, *_ in jobs if True)} solids de detail "
        f"(tira ~{stats.get('tira_idx', 0)} índices e ~{stats.get('tira_verts', 0)} vértices)"
        + (f"; {failed} grupo(s) não compilaram e ficaram como detail (log em {work})" if failed else "")
        + (". Ainda não basta pela estimativa." if not stats.get("suficiente", True) else "."))
    log(f"ht-vbsp: auto-prop: modelos em {mdl_dir} e materiais em {mat_dir} (inclua no conteúdo do mapa).")
    return {"models": made, "falhas": failed, **stats}

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
        m = mat.lower()
        if m.startswith("tools/"):
            # só o nodraw: escada invisível, clip, skip, trigger... têm colisão/conteúdo próprio e ficam como brush
            return m == "tools/toolsnodraw"
        p = self.params(mat)
        if p is None or p.get("shader", "") not in SKIP_SHADERS and "$basetexture" not in p:
            return False
        # material com conteúdo especial (%compilenonsolid, %compileladder, %playerclip...) não vira prop
        return p.get("shader", "") not in SKIP_SHADERS and not any(k.startswith(("%compile", "%playerclip")) for k in p)

    def surfaceprop(self, mat: str) -> str:
        return ((self.params(mat) or {}).get("$surfaceprop") or "default").lower()

    def surfaceprop_of(self, s) -> str:
        """$surfaceprop mais comum nas faces visíveis do solid (som de passo e de bala da colisão)."""
        c = Counter(self.surfaceprop(sd.mat) for sd in s.sides if not sd.mat.lower().startswith("tools/"))
        return c.most_common(1)[0][0] if c else "default"

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
    # empate (degraus iguais) desempata pelo id: a ordem dos solids muda entre compilações, e a origem diferente com o
    # mesmo modelo no cache punha a escada 128u abaixo, dentro da parede
    _, big = max(cl.solids, key=lambda t: (vol(t[1]), -t[1].id))
    lo, hi = big.get_bbox()
    c = (lo + hi) / 2
    return Vec(round(c.x), round(c.y), round(c.z))


def content_name(*parts: str) -> str:
    """Nome do modelo = hash do que vai ser compilado: o cache nunca devolve um .mdl de outra geometria (antes era o hash
    dos brushes, e a mesma lista de brushes com outra origem reaproveitava um modelo deslocado)."""
    h = hashlib.sha1(b"autoprop-v5")
    for p in parts:
        h.update(p.encode())
        h.update(b"\0")
    return h.hexdigest()[:12]


def build_files(cl: Cluster, mats: Materials, map_name: str) -> tuple[Vec, str, dict[str, str], dict[str, str]]:
    """(origem, nome do modelo, arquivos {nome: texto} do SMD/QC, VMTs {nome do material de modelo: texto})."""
    origin = cluster_origin(cl)
    head = "version 1\nnodes\n0 \"root\" -1\nend\nskeleton\ntime 0\n0 0 0 0 0 0 0\nend\ntriangles\n"
    ref = [head]
    vmts: dict[str, str] = {}
    surfprops: Counter = Counter()
    # ordem estável (por id): a ordem dos solids no grupo muda entre compilações e mudaria o hash do conteúdo
    for _, s in sorted(cl.solids, key=lambda t: t[1].id):
        for sd, poly in geom.face_polys(s):
            if len(poly) < 3:
                continue
            n, _ = geom.outward(sd)
            loc = [p - origin for p in poly]
            # orientação anti-horária vista de fora (normal do triângulo do mesmo lado da face)
            if Vec.cross(loc[1] - loc[0], loc[2] - loc[0]).dot(n) < 0:
                loc.reverse()
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
    folder = f"{MODEL_DIR}/{safe(map_name)}"
    sp = surfprops.most_common(1)[0][0] if surfprops else "default"
    name = content_name("".join(ref), sp)
    qc = (f'$modelname "{folder}/{name}.mdl"\n$staticprop\n$surfaceprop "{sp}"\n$cdmaterials "models/{folder}/"\n'
          f'$body "body" "ref.smd"\n$sequence "idle" "ref.smd"\n')
    # o modelo visível não tem colisão: o studiomdl funde peças de colisão encostadas num casco convexo (82 brushes
    # viravam 48 peças e verga + batentes tampavam a porta). A colisão vai em modelos à parte (collision_models)
    return origin, name, {"ref.smd": "".join(ref), "model.qc": qc}, vmts


TOUCH = 0.5   # brushes a menos disso se tocam (no mesmo modelo de colisão o studiomdl os fundiria)


def contact_colors(solids: list) -> list[int]:
    """Cor de cada solid de modo que dois que se tocam nunca tenham a mesma (gulosa, maiores primeiro). Num modelo de
    colisão só com peças que não se tocam o studiomdl mantém uma peça convexa por brush (35/35, 32/32... medido)."""
    boxes = [s.get_bbox() for s in solids]
    order = sorted(range(len(solids)), key=lambda i: -sum(boxes[i][1][k] - boxes[i][0][k] for k in range(3)))
    color: dict[int, int] = {}
    for i in order:
        lo, hi = boxes[i]
        used = {color[j] for j in color
                if all(lo[k] - TOUCH <= boxes[j][1][k] and boxes[j][0][k] - TOUCH <= hi[k] for k in range(3))}
        c = 0
        while c in used:
            c += 1
        color[i] = c
    return [color[i] for i in range(len(solids))]


def collision_models(cl: Cluster, origin: Vec, mats: Materials, map_name: str) -> list[tuple[str, dict[str, str]]]:
    """Modelos só de colisão do grupo, um por cor de contato: [(nome, arquivos)]. O corpo é a própria geometria da
    colisão, com material invisível (o prop tem fade de 1u e nunca é desenhado): com um triângulo degenerado o vbsp
    descartava o prop em silêncio, e mesmo um corpo mínimo deixaria a caixa do modelo (que decide em quais folhas da BSP
    o motor testa a colisão) num ponto só."""
    head = "version 1\nnodes\n0 \"root\" -1\nend\nskeleton\ntime 0\n0 0 0 0 0 0 0\nend\ntriangles\n"
    solids = sorted(cl.solids, key=lambda t: t[1].id)
    colors = contact_colors([s for _, s in solids])
    out = []
    folder = f"{MODEL_DIR}/{safe(map_name)}"
    for c in sorted(set(colors)):
        phys = [head]
        sps: Counter = Counter()
        pieces = 0
        body = [head]
        for (_, s), sc in zip(solids, colors):
            if sc != c:
                continue
            pieces += 1
            sps[mats.surfaceprop_of(s)] += 1
            for sd, poly in geom.face_polys(s):
                if len(poly) < 3:
                    continue
                n, _ = geom.outward(sd)
                loc = [p - origin for p in poly]
                if Vec.cross(loc[1] - loc[0], loc[2] - loc[0]).dot(n) < 0:
                    loc.reverse()
                rn = _smd(n)
                for k in range(1, len(loc) - 1):
                    phys.append("phys\n")
                    body.append("colisao\n")
                    for p in (loc[0], loc[k], loc[k + 1]):
                        q = _smd(p)
                        phys.append(f"0 {_fmt(q.x)} {_fmt(q.y)} {_fmt(q.z)} 0 0 1 {pieces} 0 1 0 1\n")
                        body.append(f"0 {_fmt(q.x)} {_fmt(q.y)} {_fmt(q.z)} {_fmt(rn.x)} {_fmt(rn.y)} {_fmt(rn.z)} 0 0 1 0 1\n")
        phys.append("end\n")
        body.append("end\n")
        body = "".join(body)
        csp = sps.most_common(1)[0][0]
        cname = content_name("".join(phys), body, csp, str(pieces)) + "_c"
        qc = (f'$modelname "{folder}/{cname}.mdl"\n$staticprop\n$surfaceprop "{csp}"\n'
              f'$cdmaterials "models/{folder}/"\n$body "body" "body.smd"\n$sequence "idle" "body.smd"\n'
              f'$collisionmodel "phys.smd"\n{{\n\t$concave\n\t$maxconvexpieces {pieces}\n\t$mass 100\n}}\n')
        out.append((cname, {"body.smd": body, "phys.smd": "".join(phys), "model.qc": qc}))
    return out


def find_studiomdl(real_vbsp: Path) -> Path | None:
    for d in (real_vbsp.parent, real_vbsp.parent.parent / "win64", real_vbsp.parent.parent):
        for n in ("studiomdl.exe", "studiomdl"):
            if (d / n).exists():
                return d / n
    return None


# --------------------------------------------------------------------------- compilar
INVISIBLE_VMT = '"VertexLitGeneric"\n{\n\t"$basetexture" "tools/toolsnodraw"\n\t"$no_draw" "1"\n}\n'


def work_dir(base: Path, key: str) -> Path:
    """Pasta de trabalho do studiomdl. Pelo Wine ele passa o caminho do .qc para minúsculas e o Z: diferencia: em
    ~/Projetos/... não acha o arquivo ("Error opening ...model.qc") e nenhum modelo compila. Aí vai para o /tmp."""
    if os.name != "nt" and str(base.resolve()) != str(base.resolve()).lower():
        import tempfile
        return Path(tempfile.gettempdir()) / "ht-autoprop" / hashlib.sha1(key.encode()).hexdigest()[:10]
    return base


def model_dirs(gamedir: Path, map_name: str) -> tuple[Path, Path, str]:
    """(pasta dos .mdl, pasta dos .vmt, caminho do modelo no jogo sem o nome) de um mapa."""
    rel = f"{MODEL_DIR}/{safe(map_name)}"
    return gamedir / "models" / rel, gamedir / "materials" / "models" / rel, f"models/{rel}"


def prepare(clusters: list[Cluster], mats: Materials, map_name: str, gamedir: Path, work: Path) -> list[tuple]:
    """Grava VMTs e os SMD/QC de cada grupo. [(grupo, origem, nome do visível, [(modelo, pasta de trabalho)])], o
    primeiro modelo é o visível e os outros os de colisão."""
    mdl_dir, mat_dir, _ = model_dirs(gamedir, map_name)
    mat_dir.mkdir(parents=True, exist_ok=True)
    mdl_dir.mkdir(parents=True, exist_ok=True)
    # material do corpo dos modelos de colisão (nunca desenhados): invisível, só para não faltar
    inv = mat_dir / "colisao.vmt"
    if not inv.exists() or inv.read_text() != INVISIBLE_VMT:
        inv.write_text(INVISIBLE_VMT)
    jobs = []
    for cl in clusters:
        origin, name, files, vmts = build_files(cl, mats, map_name)
        for mname, text in vmts.items():
            f = mat_dir / f"{mname}.vmt"
            if not f.exists() or f.read_text() != text:
                f.write_text(text)
        dirs = []
        for mname, mfiles in [(name, files)] + collision_models(cl, origin, mats, map_name):
            d = work / mname
            d.mkdir(parents=True, exist_ok=True)
            for fn, text in mfiles.items():
                (d / fn).write_text(text)
            dirs.append((mname, d))
        jobs.append((cl, origin, name, dirs))
    return jobs


def compile_jobs(jobs: list[tuple], mdl_dir: Path, gamedir: Path, studiomdl: Path, run=None) -> dict[str, bool]:
    """Compila no studiomdl (em paralelo) os modelos que ainda não existem. {modelo: compilou}."""
    import subprocess
    from hammertools.cli import _wine_cmd

    def default_run(cmd, cwd) -> int:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace", env=dict(os.environ, WINEDEBUG="-all"))
        (Path(cwd) / "studiomdl.log").write_text(r.stdout + r.stderr)    # o "log em <pasta>" dos avisos
        return r.returncode
    run = run or default_run

    # o studiomdl roda com cwd na pasta do modelo: caminho relativo (ht prop mapa.vmf --game ../gm) não acharia nada
    studiomdl, gamedir = Path(studiomdl).resolve(), Path(gamedir).resolve()

    def compile_one(item) -> bool:
        mname, d = item
        mdl = mdl_dir / f"{mname}.mdl"
        if mdl.exists():
            return True     # mesmo hash = mesmo conteúdo: já compilado
        d = Path(d).resolve()
        try:
            run(_wine_cmd([str(studiomdl), "-game", str(gamedir), "-nop4", "-nox360", str(d / "model.qc")]), str(d))
        except OSError:
            return False    # studiomdl que não executa (sem Wine, sem permissão): o grupo fica como brush
        return mdl.exists()

    items = [it for *_, dirs in jobs for it in dirs]
    with ThreadPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) // 2)) as pool:
        return dict(zip((m for m, _ in items), pool.map(compile_one, items)))


def prop_keyvalues(folder: str, origin: Vec, dirs: list[tuple]) -> list[dict[str, str]]:
    """prop_static de um grupo: o visível e os de colisão."""
    org = f"{origin.x:g} {origin.y:g} {origin.z:g}"
    name = dirs[0][0]
    # o visível só desenha, com luz por vértice (vrad -StaticPropLighting): a origem fica dentro da própria colisão
    # e, iluminado só por ela, saía preto. A sombra vem da colisão, com a forma exata dos brushes
    out = [{"classname": "prop_static", "model": f"{folder}/{name}.mdl", "origin": org, "angles": "0 0 0",
            "solid": "0", "skin": "0", "fademindist": "-1", "fadescale": "1", "disableshadows": "1",
            "disableselfshadowing": "1"}]
    # colisão: uma peça convexa por brush, em modelos sem brushes encostados; nunca desenhados (fade de 1u)
    for mname, _ in dirs[1:]:
        out.append({"classname": "prop_static", "model": f"{folder}/{mname}.mdl", "origin": org,
                    "angles": "0 0 0", "solid": "6", "skin": "0", "fademindist": "0", "fademaxdist": "1",
                    "fadescale": "1", "disableshadows": "0", "disablevertexlighting": "1"})
    return out


def isolate_prop_light(v: VMF) -> int:
    """Com props gerados no mapa (auto-prop ou `ht prop`), os outros prop_static ganham disablevertexlighting: o
    -StaticPropLighting que os gerados precisam é global no vrad e escurecia o mapa inteiro (rp_surdonoso). O Hammer++
    grava "0" em todo prop, então "0" é o padrão, não escolha. HT_ALL_PROP_LIGHT=1 (perfil final) deixa como está.
    Devolve quantos mudaram."""
    if os.environ.get("HT_ALL_PROP_LIGHT") == "1":
        return 0
    props = v.by_class["prop_static"]
    if not any(f"/{MODEL_DIR}/" in e["model"] for e in props):
        return 0
    n = 0
    for e in props:
        if f"/{MODEL_DIR}/" not in e["model"] and e["disablevertexlighting"] != "1":
            e["disablevertexlighting"] = "1"
            n += 1
    return n


# --------------------------------------------------------------------------- aplicar
def apply(out: Path, gamedir: Path, real_vbsp: Path, calib: float = CALIB_IDX, vcalib: float = CALIB_VERTS,
          log=print, run=None) -> dict:
    """Converte os grupos escolhidos do build/ (out) em prop_static compilados. Devolve o resumo para o registro."""
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
    work = work_dir(out.parent / "ht_prop", str(out.resolve()))
    mdl_dir, mat_dir, folder = model_dirs(gamedir, map_name)
    jobs = prepare(chosen, mats, map_name, gamedir, work)
    items = [it for *_, dirs in jobs for it in dirs]
    todo = sum(1 for m, _ in items if not (mdl_dir / f"{m}.mdl").exists())
    log(f"ht-vbsp: auto-prop: {len(jobs)} grupo(s) -> prop_static + {len(items) - len(jobs)} modelo(s) de colisão "
        f"({todo} para compilar no studiomdl, o resto do cache)...")
    compiled = compile_jobs(jobs, mdl_dir, gamedir, studiomdl, run)
    made = 0
    for cl, origin, name, dirs in jobs:
        if not all(compiled[m] for m, _ in dirs):
            continue                # sem a colisão inteira o grupo fica como detail (prop sem colisão = parede que some)
        for e, s_ in cl.solids:
            e.solids.remove(s_)
            if not e.solids:
                v.remove_ent(e)
        for kv in prop_keyvalues(folder, origin, dirs):
            v.add_ent(Entity(v, kv))
        made += 1
    isolate_prop_light(v)
    vmfio.save(v, out)
    # modelos que nenhum prop deste build usa (nomes antigos, outra geometria) saem da pasta: o pack embute a pasta
    used = {Path(e["model"]).stem for e in v.by_class["prop_static"] if e["model"].startswith(folder + "/")}
    for f in mdl_dir.glob("*"):
        stem = f.name.split(".")[0]
        if re.fullmatch(r"[0-9a-f]{12}(_c\d*)?", stem) and stem not in used:   # _c0.. = nomes antigos
            f.unlink()
    failed = len(jobs) - made
    log(f"ht-vbsp: auto-prop: {made} prop_static no lugar de {sum(len(c.solids) for c, *_ in jobs)} solids de detail "
        f"(tira ~{stats.get('tira_idx', 0)} índices e ~{stats.get('tira_verts', 0)} vértices)"
        + (f"; {failed} grupo(s) não compilaram e ficaram como detail (log em {work})" if failed else "")
        + (". Ainda não basta pela estimativa." if not stats.get("suficiente", True) else "."))
    log(f"ht-vbsp: auto-prop: modelos em {mdl_dir} e materiais em {mat_dir} (inclua no conteúdo do mapa).")
    if made:
        log("ht-vbsp: auto-prop: o vrad precisa de -StaticPropLighting (o `ht compile` põe sozinho; compilando por fora, "
            "sem isso o prop gerado sai preto). Os outros props ficam com disablevertexlighting e não mudam.")
    return {"models": made, "falhas": failed, **stats}


# --------------------------------------------------------------------------- `ht prop` (Propper do editor)
@dataclass
class PropResult:
    entities: list[dict[str, str]] = field(default_factory=list)   # prop_static a criar (visível primeiro)
    removed: list[int] = field(default_factory=list)              # ids dos solids que viraram prop
    skipped: dict[int, str] = field(default_factory=dict)         # id -> motivo de ficar como brush
    warnings: list[str] = field(default_factory=list)
    model: str = ""
    origin: Vec | None = None
    work: Path | None = None


def convert(v: VMF, solid_ids: list[int], gamedir: Path, map_name: str, studiomdl: Path, work: Path,
            mats: Materials | None = None, run=None) -> PropResult:
    """Propper manual: os solids escolhidos (mundo ou entidade de brush) viram UM prop_static visível e os modelos de
    colisão, com o mesmo gerador do auto-prop. Não mexe no VMF: devolve as entidades a criar e os solids a tirar (o
    editor aplica num passo de desfazer; o CLI grava um VMF novo). Modelos em models/ht_prop/<mapa>/, que o ht-vbsp
    ilumina por vértice e o pack embute."""
    from hammertools import lint
    mats = mats or Materials(lint.Resources.from_game(str(gamedir), None, ()))
    owner: dict[int, tuple] = {}
    for s in v.brushes:
        owner[s.id] = (None, s)
    for e in v.entities:
        for s in e.solids:
            owner[s.id] = (e, s)
    r = PropResult()
    picked = []
    for sid in dict.fromkeys(solid_ids):
        if sid not in owner:
            r.skipped[sid] = "não existe no mapa"
            continue
        e, s = owner[sid]
        if any(sd.is_disp for sd in s.sides):
            r.skipped[sid] = "displacement"
        elif bad := sorted({sd.mat for sd in s.sides if not mats.usable(sd.mat)}):
            r.skipped[sid] = "material que não funciona em modelo ou tem conteúdo próprio: " + ", ".join(bad[:3])
        elif not any(len(p) >= 3 and not sd.mat.lower().startswith("tools/") for sd, p in geom.face_polys(s)):
            r.skipped[sid] = "só faces de ferramenta"
        else:
            picked.append((e, s))
    if not picked:
        r.warnings.append("nada a converter")
        return r
    if any(e is None for e, _ in picked):
        r.warnings.append("brushes do mundo viram prop e deixam de selar: confira leak no próximo compile")
    mdl_dir, _, folder = model_dirs(gamedir, map_name)
    (cl_job,) = jobs = prepare([Cluster((0, 0, 0), picked)], mats, map_name, gamedir, work)
    compiled = compile_jobs(jobs, mdl_dir, gamedir, studiomdl, run)
    cl, origin, name, dirs = cl_job
    r.work, r.origin, r.model = work, origin, f"{folder}/{name}.mdl"
    failed = [m for m, _ in dirs if not compiled[m]]
    if failed:
        r.warnings.append(f"studiomdl falhou em {len(failed)} de {len(dirs)} modelo(s); log em {work}")
        r.model = ""
        return r
    r.entities = prop_keyvalues(folder, origin, dirs)
    r.removed = [s.id for _, s in picked]
    return r


def bsp_static_models(bsp: Path) -> Counter:
    """Quantos prop_static de cada modelo o BSP tem (lump de jogo sprp)."""
    import struct
    data = Path(bsp).read_bytes()
    o, l = struct.unpack_from("<ii", data, 8 + 16 * 35)
    gl = data[o:o + l]
    for k in range(struct.unpack_from("<i", gl, 0)[0]):
        gid, _flags, _ver, ofs, ln = struct.unpack_from("<iHHii", gl, 4 + 16 * k)
        if gid != 0x73707270:          # "sprp"
            continue
        b = data[ofs:ofs + ln]
        nd = struct.unpack_from("<i", b, 0)[0]
        names = [b[4 + 128 * i:4 + 128 * (i + 1)].split(b"\0")[0].decode("latin-1").lower() for i in range(nd)]
        p = 4 + 128 * nd
        p += 4 + 2 * struct.unpack_from("<i", b, p)[0]
        n = struct.unpack_from("<i", b, p)[0]
        p += 4
        size = (len(b) - p) // n if n else 0
        return Counter(names[struct.unpack_from("<H", b, p + i * size + 24)[0]] for i in range(n))
    return Counter()


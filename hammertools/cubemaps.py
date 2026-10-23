"""env_cubemap planejados no BSP: posição, quantidade e qual cubemap cada face com reflexo usa.

O vbsp liga cada face com `$envmap env_cubemap` ao cubemap mais PERTO (material corrigido
materials/maps/<mapa>/<material>_x_y_z.vmt, um "patch" que troca o $envmap), sem olhar se o cubemap enxerga a face:
no rp_surdonoso 25% da área com reflexo usava um cubemap atrás de parede e a mediana da distância era 1164u.

Aqui, depois do vbsp e antes do vvis/vrad:
  1. faces com reflexo = as que o vbsp corrigiu (o nome do material diz o cubemap; o `include` do patch, o material);
  2. candidatos = os cubemaps do autor + um ponto no ar diante de cada face (altura de olho se for chão);
  3. cobertura gulosa por área: um candidato cobre a face se a enxerga (raio na árvore do BSP), está na frente dela e
     a menos de `radius`; para em 99% da área cobrível (água fica de fora: o shader dela reflete em tempo real);
  4. cada face usa o cubemap escolhido mais perto que a enxerga (senão o mais perto, como o vbsp);
  5. o BSP ganha o lump de cubemaps novo, os patches novos e VTFs provisórios (BGR888 e RGBA16161616F, cinza) que o
     bake do EchoHammer pinta no lugar (mesmo tamanho) com o path tracer.

Raio 512u no rp_surdonoso: 242 cubemaps (eram 278), nenhum conflito de visibilidade, 455 materiais corrigidos.
"""
from __future__ import annotations

import io
from pathlib import Path
import math
import re
import struct
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field

from srctools import Vec
from srctools.bsp import BSP, VisLeaf
from srctools.const import BSPContents

PATCHED = re.compile(r"^maps/([^/]+)/(.+)_(-?\d+)_(-?\d+)_(-?\d+)$")
VTF_NAME = re.compile(r"^materials/maps/[^/]+/c-?\d+_-?\d+_-?\d+(\.hdr)?\.vtf$")
RADIUS = 512.0
COVER = 0.99
EYE = 64.0
SIDE = 32                 # lado do cubemap padrão (tamanho 0 no lump)
SURF_GAP = 32.0           # faces do mesmo material e plano a até isso uma da outra são a mesma superfície (vidros entre caixilhos)
WATER_CELL = 2048.0       # um cubemap de água por célula (lago grande ganha vários: o reflexo muda pela margem)
WATER_HEIGHT = 96.0       # altura do cubemap da água acima da superfície
PLACEHOLDER = 0.25        # cinza linear dos VTFs provisórios (se o bake não rodar, reflexo neutro e não preto)


@dataclass
class RFace:
    face: object
    center: Vec
    normal: Vec
    area: float
    base: str             # material original (sem materials/ e .vmt), como no include do patch
    water: bool
    index: int            # posição no lump de faces
    lo: Vec = field(default_factory=Vec)
    hi: Vec = field(default_factory=Vec)


@dataclass
class Plan:
    mapname: str
    origins: list[Vec]
    assign: dict[int, int]                 # índice em faces -> índice em origins
    faces: list[RFace]
    include: dict[str, str] = field(default_factory=dict)   # patch velho -> material original
    kept: int = 0
    water: int = 0                         # cubemaps acima da água
    transitions: int = 0                   # cubemaps de transição em emendas de superfície (entrada de túnel)
    surfaces: int = 0                      # superfícies contínuas (cada uma com um cubemap só)                          # cubemaps do autor mantidos
    blocked_before: float = 0.0            # fração da área com cubemap atrás de parede (antes)
    blocked_after: float = 0.0
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- árvore do BSP

def _leaf(bsp: BSP, p: Vec) -> VisLeaf | None:
    return bsp.nodes[0].test_point(p)


def _solid(leaf) -> bool:
    return leaf is None or bool(leaf.contents & BSPContents.SOLID)


def blocked(bsp: BSP, a: Vec, b: Vec) -> bool:
    """O segmento a→b atravessa folha sólida? (srctools: child_pos é o lado n·p < d, ver VisTree.test_point)"""
    stack = [(bsp.nodes[0], a, b)]
    while stack:
        node, a, b = stack.pop()
        while True:
            if isinstance(node, VisLeaf):
                if node.contents & BSPContents.SOLID:
                    return True
                break
            n, d = node.plane.normal, node.plane.dist
            da, db = n.dot(a) - d, n.dot(b) - d
            if da >= -0.01 and db >= -0.01:
                node = node.child_neg
            elif da < 0.01 and db < 0.01:
                node = node.child_pos
            else:
                m = a + (b - a) * (da / (da - db))
                near, far = (node.child_neg, node.child_pos) if da >= 0 else (node.child_pos, node.child_neg)
                stack.append((far, m, b))
                node, b = near, m
    return False


# ---------------------------------------------------------------- leitura

def reflective_faces(bsp: BSP) -> tuple[str | None, list[RFace], dict[str, str]]:
    """Faces que o vbsp ligou a um cubemap. Devolve (pasta do mapa, faces, patch -> material incluído)."""
    pak = bsp.pakfile
    own = Path(bsp.filename).stem.lower()
    include: dict[str, str] = {}
    for name in pak.namelist():
        low = name.lower()
        # só os patches que o vbsp fez para ESTE mapa: o VMF pode usar de verdade materiais com nome de patch de
        # outro mapa (maps/rp_surdonoso/..._x_y_z, herdados de um mapa decompilado), e renomear o slot deles trocava
        # o material de 679 faces no rp_surdonoso
        if low.startswith(f"materials/maps/{own}/") and low.endswith(".vmt") and PATCHED.match(low[len("materials/"):-4]):
            m = re.search(r'"include"\s+"([^"]+)"', pak.read(name).decode("latin-1"), re.I)
            if m:
                inc = m.group(1).replace("\\", "/")
                inc = inc[len("materials/"):] if inc.lower().startswith("materials/") else inc
                include[low[len("materials/"):-4]] = inc[:-4] if inc.lower().endswith(".vmt") else inc
    mapname, out = None, []
    for fi, f in enumerate(bsp.faces):
        mat = f.texinfo.mat.lower() if f.texinfo else ""
        m = PATCHED.match(mat)
        if not m or mat not in include:
            continue
        mapname = m.group(1)                  # = own (só patches deste mapa entram em include)
        pts = [e.a for e in f.edges]
        if len(pts) < 3:
            continue
        c = sum(pts, Vec()) / len(pts)
        area = sum(Vec.cross(pts[i] - pts[0], pts[i + 1] - pts[0]).mag() / 2 for i in range(1, len(pts) - 1))
        base = include[mat]
        out.append(RFace(f, c, Vec(f.plane.normal), area, base, "water" in base.lower(), fi,
                         Vec(min(q.x for q in pts), min(q.y for q in pts), min(q.z for q in pts)),
                         Vec(max(q.x for q in pts), max(q.y for q in pts), max(q.z for q in pts))))
    return mapname, out, include


# ---------------------------------------------------------------- plano

def _air_point(bsp: BSP, p: Vec, n: Vec) -> Vec | None:
    """Ponto no ar diante da face: altura de olho sobre chão; senão até 96u na normal, sem atravessar nada."""
    tries = [p + Vec(0, 0, EYE)] if n.z > 0.7 else []
    tries += [p + n * d for d in (96, 64, 48, 32, 16)]
    for q in tries:
        if not _solid(_leaf(bsp, q)) and not blocked(bsp, p, q):
            return Vec(round(q.x), round(q.y), round(q.z))
    return None


def plan(bsp: BSP, radius: float = RADIUS) -> Plan | None:
    mapname, faces, include = reflective_faces(bsp)
    if not faces:
        return None
    author = [Vec(c.origin) for c in bsp.cubemaps]
    pts = [f.center + f.normal * 2 for f in faces]
    total = sum(f.area for f in faces if not f.water) or 1.0

    # antes: a face via o cubemap que o vbsp deu?
    akey = {(round(c.x), round(c.y), round(c.z)): c for c in author}
    before = 0.0
    for f, p in zip(faces, pts):
        m = PATCHED.match(f.face.texinfo.mat.lower())
        c = akey.get((int(m.group(3)), int(m.group(4)), int(m.group(5))))
        if not f.water and c is not None and blocked(bsp, p, c):
            before += f.area

    cands = [c for c in author if not _solid(_leaf(bsp, c))]
    n_author = len(cands)
    cands += [q for f, p in zip(faces, pts) if not f.water and (q := _air_point(bsp, p, f.normal)) is not None]

    G = 256.0
    grid = defaultdict(list)
    for i, c in enumerate(cands):
        grid[(int(c.x // G), int(c.y // G), int(c.z // G))].append(i)

    def near(p, r):
        k = int(math.ceil(r / G))
        gx, gy, gz = int(p.x // G), int(p.y // G), int(p.z // G)
        for x in range(gx - k, gx + k + 1):
            for y in range(gy - k, gy + k + 1):
                for z in range(gz - k, gz + k + 1):
                    yield from grid.get((x, y, z), ())

    sees: dict[int, set[int]] = defaultdict(set)      # candidato -> faces que ele cobre
    for fi, (f, p) in enumerate(zip(faces, pts)):
        if f.water:
            continue
        for ci in near(p, radius):
            c = cands[ci]
            if (c - p).mag() <= radius and f.normal.dot(c - p) > 0 and not blocked(bsp, p, c):
                sees[ci].add(fi)
    left = set().union(*sees.values()) if sees else set()
    goal = sum(faces[i].area for i in left)
    chosen, got = [], 0.0
    while left and got < COVER * goal:
        ci = max(sees, key=lambda c: (sum(faces[i].area for i in sees[c] & left), c < n_author))
        gain = sees[ci] & left
        if not gain:
            break
        chosen.append(ci)
        got += sum(faces[i].area for i in gain)
        left -= gain
    origins = [cands[ci] for ci in chosen]
    # água: cubemap próprio acima da superfície (um por célula de WATER_CELL), que vê o céu e a margem como o
    # reflexo de verdade; o cubemap de terra mais perto (às vezes junto de parede) deixava a água apagada
    water_idx = set()
    cells: dict = defaultdict(list)
    for f in faces:
        if f.water:
            cells[(int(f.center.x // WATER_CELL), int(f.center.y // WATER_CELL), round(f.center.z))].append(f)
    for fs in cells.values():
        a = sum(f.area for f in fs) or 1.0
        c = sum((f.center * f.area for f in fs), Vec()) / a
        for h in (WATER_HEIGHT, WATER_HEIGHT / 2, 32):
            q = Vec(round(c.x), round(c.y), round(c.z + h))
            if not _solid(_leaf(bsp, q)):
                water_idx.add(len(origins))
                origins.append(q)
                break
    if not origins:
        return None

    # cubemaps que cada face enxerga (até 24 mais perto, de frente); água: só os da água
    sees_face = []
    for f, p in zip(faces, pts):
        pool = [i for i in range(len(origins)) if (i in water_idx) == f.water] if f.water and water_idx else range(len(origins))
        order = sorted(pool, key=lambda i: (origins[i] - p).mag())
        vis = [i for i in order[:24] if f.normal.dot(origins[i] - p) > 0 and not blocked(bsp, p, origins[i])]
        sees_face.append((set(vis), order[0] if order else 0))

    # superfície contínua (mesmo material, mesmo plano, faces encostadas com folga SURF_GAP): um cubemap só para
    # ela inteira. Por face, o asfalto e os vidros da fachada viravam colcha de reflexos (emenda onde muda o cubemap)
    parent = list(range(len(faces)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    buckets: dict = defaultdict(list)
    for fi, f in enumerate(faces):
        n = f.normal
        buckets[(f.base.lower(), round(n.x, 2), round(n.y, 2), round(n.z, 2), round(n.dot(f.center)))].append(fi)
    g = SURF_GAP
    for idx in buckets.values():
        for a_i, a in enumerate(idx):
            fa = faces[a]
            for b in idx[a_i + 1:]:
                fb = faces[b]
                if all(fa.lo[k] - g <= fb.hi[k] and fb.lo[k] - g <= fa.hi[k] for k in range(3)):
                    parent[find(a)] = find(b)
    groups: dict = defaultdict(list)
    for fi in range(len(faces)):
        groups[find(fi)].append(fi)

    assign, after, groups_n = assign_surfaces(faces, sees_face, origins, groups)
    n_trans = transitions(bsp, faces, origins, assign, groups)
    return Plan(mapname, origins, assign, faces, include, kept=sum(1 for ci in chosen if ci < n_author), water=len(water_idx), surfaces=groups_n,
                blocked_before=before / total, blocked_after=after / total, transitions=n_trans)


SHARE_FACTOR = 2.0        # a face só adota o cubemap da superfície se ele estiver a até 2x a distância do visível mais
SHARE_SLACK = 256.0       # perto dela + 256 (estrada que entra num túnel: o de fora, a 4.000 u, não reflete no túnel)


def assign_surfaces(faces, sees_face, origins, groups):
    """Cubemap de cada face. Por superfície contínua: o cubemap que a maior área dela enxerga fica com todas as faces
    que o enxergam E estão perto o bastante dele (SHARE_*); o resto (outra sala no mesmo plano, atrás de parede, ou
    longe dele, como o trecho dentro do túnel) escolhe de novo. Devolve (assign, área sem cubemap visível, superfícies)."""
    share = []
    for f, (vis, _) in zip(faces, sees_face):
        if not vis:
            share.append(set()); continue
        dmin = min((origins[ci] - f.center).mag() for ci in vis)
        lim = SHARE_FACTOR * dmin + SHARE_SLACK
        share.append({ci for ci in vis if (origins[ci] - f.center).mag() <= lim})
    assign, after = {}, 0.0
    groups_n = 0
    for members in groups.values():
        left = list(members)
        while left:
            groups_n += 1
            area = sum(faces[i].area for i in left) or 1.0
            c = sum((faces[i].center * faces[i].area for i in left), Vec()) / area
            score: dict = defaultdict(float)
            for i in left:
                for ci in share[i]:
                    score[ci] += faces[i].area
            if not score:
                for i in left:
                    assign[i] = sees_face[i][1]
                    if not faces[i].water:
                        after += faces[i].area
                break
            pick = max(score, key=lambda ci: (score[ci], -(origins[ci] - c).mag()))
            rest = []
            for i in left:
                if pick in share[i]:
                    assign[i] = pick
                else:
                    rest.append(i)
            left = rest
    return assign, after, groups_n


TRANS_ROOF = 512.0        # cubemap com teto a até isso acima está coberto (túnel, garagem); sem, está a céu aberto
TRANS_CELL = 512.0        # um de transição por célula de emenda (estrada larga: vários pontos da mesma boca)


def _covered(bsp: BSP, p: Vec) -> bool:
    return blocked(bsp, p, p + Vec(0, 0, TRANS_ROOF))


def transitions(bsp: BSP, faces, origins, assign, groups) -> int:
    """Cubemap de transição onde a mesma superfície troca de um cubemap a céu aberto para um coberto (estrada que sai
    do sol e entra no túnel): um cubemap novo na emenda, à altura de olho, que as faces dos dois lados passam a usar.
    O reflexo vai de fora -> transição -> dentro em vez de saltar do claro para o escuro numa linha. Muda `origins` e
    `assign`; devolve quantos criou."""
    seams: dict = defaultdict(list)          # célula da emenda -> [(ponto da emenda, face a, face b, normal)]
    cover: dict[int, bool] = {}
    g = SURF_GAP
    for members in groups.values():
        if len(members) < 2:
            continue
        for a_i, a in enumerate(members):
            fa = faces[a]
            if fa.water or a not in assign:
                continue
            for b in members[a_i + 1:]:
                fb = faces[b]
                if b not in assign or assign[a] == assign[b]:
                    continue
                if not all(fa.lo[k] - g <= fb.hi[k] and fb.lo[k] - g <= fa.hi[k] for k in range(3)):
                    continue
                for ci in (assign[a], assign[b]):
                    if ci not in cover:
                        cover[ci] = _covered(bsp, origins[ci])
                if cover[assign[a]] == cover[assign[b]]:
                    continue
                lo = Vec(*(max(fa.lo[k], fb.lo[k]) for k in range(3)))
                hi = Vec(*(min(fa.hi[k], fb.hi[k]) for k in range(3)))
                m = (lo + hi) / 2
                cell = (int(m.x // TRANS_CELL), int(m.y // TRANS_CELL), int(m.z // TRANS_CELL))
                seams[cell].append((m, a, b, fa.normal))
    made = 0
    moved: set[int] = set()                  # cada face muda uma vez só (face entre duas emendas fica com a primeira)
    for pts in seams.values():
        m = sum((p for p, *_ in pts), Vec()) / len(pts)
        n = pts[0][3]
        q = None
        for h in (EYE, EYE / 2, 16.0):
            c = Vec(round(m.x + n.x * h), round(m.y + n.y * h), round(m.z + n.z * h))
            if not _solid(_leaf(bsp, c)):
                q = c
                break
        if q is None:
            continue
        side = {i for _, a, b, _ in pts for i in (a, b)} - moved
        ok = [i for i in side if not blocked(bsp, faces[i].center + faces[i].normal * 2, q)]
        if not ok:
            continue
        ci = len(origins)
        origins.append(q)
        for i in ok:
            assign[i] = ci
        moved.update(ok)
        made += 1
    return made


# ---------------------------------------------------------------- VTF provisório

def _mips(side: int) -> int:
    return int(math.log2(side)) + 1


def placeholder_vtf(side: int, hdr: bool) -> bytes:
    """Cubemap VTF 7.0 (6 faces, sem spheremap), envmap|clamps|clampt|nolod, todos os mips; BGR888 (LDR, gama 2,2)
    ou RGBA16161616F (HDR, linear). O bake regrava só os pixels."""
    fmt, bpp = (24, 8) if hdr else (3, 3)
    head = bytearray(64)
    head[0:4] = b"VTF\0"
    struct.pack_into("<IIIHHI", head, 4, 7, 0, 64, side, side, 0x4000 | 0x0004 | 0x0008 | 0x0200)
    struct.pack_into("<HH", head, 24, 1, 0)
    struct.pack_into("<fff", head, 32, PLACEHOLDER, PLACEHOLDER, PLACEHOLDER)
    struct.pack_into("<f", head, 48, 1.0)
    struct.pack_into("<i", head, 52, fmt)
    head[56] = _mips(side)
    struct.pack_into("<i", head, 57, -1)
    if hdr:
        h = struct.pack("<e", PLACEHOLDER)
        px = h * 3 + struct.pack("<e", 1.0)
    else:
        g = round(PLACEHOLDER ** (1 / 2.2) * 255)
        px = bytes((g, g, g))
    n = sum(max(1, side >> m) ** 2 for m in range(_mips(side))) * 6
    return bytes(head) + px * n


# ---------------------------------------------------------------- aplicação

FACE_SIZE = 56
TEXINFO_SIZE = 72
TEXDATA_SIZE = 32
MAX_TEXINFO = 12288
MAX_TEXDATA = 2048


def apply(path, p: Plan, hdr: bool = True) -> dict:
    """Grava o plano no BSP em `path` mexendo só nos bytes dos lumps (o srctools, ao regravar faces/texinfo, perde
    o LEAFWATERDATA e cria OVERLAY_SYSTEM_LEVELS). Os slots de texdata dos patches velhos viram os patches novos (o que
    sobrar volta ao material original) e cada texinfo velho fica com o 1º material novo das faces dele (lados de brush
    e água, que apontam para ele, continuam válidos); as outras combinações entram no fim do lump."""
    from srctools.bsp import BSP_LUMPS as L
    bsp = BSP(str(path))
    raw = lambda lump: bytearray(bsp.lumps[lump].data)
    faces_raw, texinfo, texdata = raw(L.FACES), raw(L.TEXINFO), raw(L.TEXDATA)
    sdata, stable = raw(L.TEXDATA_STRING_DATA), raw(L.TEXDATA_STRING_TABLE)
    n_td = len(texdata) // TEXDATA_SIZE

    def name_of(td: int) -> str:
        sid = struct.unpack_from("<i", texdata, td * TEXDATA_SIZE + 12)[0]
        o = struct.unpack_from("<i", stable, sid * 4)[0]
        return sdata[o:sdata.index(0, o)].decode("latin-1")

    def set_name(td: int, name: str) -> None:
        o = len(sdata)
        sdata.extend(name.encode("latin-1") + b"\0")
        stable.extend(struct.pack("<i", o))
        struct.pack_into("<i", texdata, td * TEXDATA_SIZE + 12, len(stable) // 4 - 1)

    folder = f"maps/{p.mapname}"
    key = lambda o: f"{round(o.x)}_{round(o.y)}_{round(o.z)}"
    old_slots, base_slot = [], {}
    for td in range(n_td):
        if name_of(td).lower() in p.include:
            old_slots.append(td)
    # material novo de cada face, pela ordem do lump
    mats = {}
    for fi, f in enumerate(p.faces):
        mats[f.index] = (f.base.lower(), f"{folder}/{f.base.lower()}_{key(p.origins[p.assign[fi]])}")
    new_names = sorted({m for _b, m in mats.values()})
    base_of = {m: b for b, m in mats.values()}
    # dimensões/refletividade: as do patch velho do mesmo material
    for td in old_slots:
        base_slot.setdefault(p.include.get(name_of(td).lower(), "").lower(), td)
    slot_of = {}
    for k, m in enumerate(new_names):
        if k < len(old_slots):
            td = old_slots[k]
        else:
            td = len(texdata) // TEXDATA_SIZE
            src = base_slot.get(base_of[m], old_slots[0])
            texdata.extend(texdata[src * TEXDATA_SIZE:(src + 1) * TEXDATA_SIZE])
        src = base_slot.get(base_of[m])
        if src is not None and src != td:
            texdata[td * TEXDATA_SIZE:td * TEXDATA_SIZE + 12] = texdata[src * TEXDATA_SIZE:src * TEXDATA_SIZE + 12]
            texdata[td * TEXDATA_SIZE + 16:(td + 1) * TEXDATA_SIZE] = texdata[src * TEXDATA_SIZE + 16:(src + 1) * TEXDATA_SIZE]
        set_name(td, m)
        slot_of[m] = td
    for td in old_slots[len(new_names):]:              # patch velho sem uso: volta ao material dele
        set_name(td, p.include.get(name_of(td).lower(), name_of(td)))
    if len(texdata) // TEXDATA_SIZE > MAX_TEXDATA:
        raise ValueError(f"texdata passou do limite ({len(texdata) // TEXDATA_SIZE} > {MAX_TEXDATA})")

    # texinfo: o 1º material novo de cada texinfo velho reaproveita o slot; os outros são cópias no fim
    first: dict[int, str] = {}
    extra: dict[tuple[int, str], int] = {}
    ti_of_face = {}
    for idx, (_b, m) in sorted(mats.items()):
        t = struct.unpack_from("<h", faces_raw, idx * FACE_SIZE + 10)[0]
        if first.setdefault(t, m) == m:
            ti_of_face[idx] = t
            continue
        if (t, m) not in extra:
            extra[(t, m)] = len(texinfo) // TEXINFO_SIZE
            texinfo.extend(texinfo[t * TEXINFO_SIZE:(t + 1) * TEXINFO_SIZE])
            struct.pack_into("<i", texinfo, extra[(t, m)] * TEXINFO_SIZE + 68, slot_of[m])
        ti_of_face[idx] = extra[(t, m)]
    for t, m in first.items():
        struct.pack_into("<i", texinfo, t * TEXINFO_SIZE + 68, slot_of[m])
    if len(texinfo) // TEXINFO_SIZE > MAX_TEXINFO:
        raise ValueError(f"texinfo passou do limite ({len(texinfo) // TEXINFO_SIZE} > {MAX_TEXINFO})")

    # faces (e as HDR, paralelas) e as faces originais delas
    orig_raw = raw(L.ORIGINALFACES)
    hdr_raw = raw(L.FACES_HDR) if L.FACES_HDR in bsp.lumps else bytearray()
    for idx, ti in ti_of_face.items():
        struct.pack_into("<h", faces_raw, idx * FACE_SIZE + 10, ti)
        if len(hdr_raw) == len(faces_raw):
            struct.pack_into("<h", hdr_raw, idx * FACE_SIZE + 10, ti)
        o = struct.unpack_from("<i", faces_raw, idx * FACE_SIZE + 44)[0]
        if 0 <= o and (o + 1) * FACE_SIZE <= len(orig_raw):
            struct.pack_into("<h", orig_raw, o * FACE_SIZE + 10, ti)

    cubes = b"".join(struct.pack("<3ii", round(o.x), round(o.y), round(o.z), 0) for o in p.origins)

    old = zipfile.ZipFile(io.BytesIO(bytes(bsp.lumps[L.PAKFILE].data)))
    buf = io.BytesIO()
    z = zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED)
    dropped = 0
    for info in old.infolist():
        low = info.filename.lower()
        mine = low.startswith(f"materials/{folder}/")
        if mine and (VTF_NAME.match(low) or (low.endswith(".vmt") and low[len("materials/"):-4] in p.include)):
            dropped += 1
            continue
        z.writestr(info, old.read(info.filename), zipfile.ZIP_STORED)
    for m in new_names:
        ci_key = m.rsplit("_", 3)
        z.writestr(f"materials/{m}.vmt",
                   f'"patch"\r\n{{\r\n\t"include"\t\t"materials/{base_of[m]}.vmt"\r\n\t"replace"\r\n\t{{\r\n'
                   f'\t\t"$envmap"\t\t"{folder}/c{ci_key[1]}_{ci_key[2]}_{ci_key[3]}"\r\n\t}}\r\n}}\r\n')
    for o in p.origins:
        z.writestr(f"materials/{folder}/c{key(o)}.vtf", placeholder_vtf(SIDE, False))
        if hdr:
            z.writestr(f"materials/{folder}/c{key(o)}.hdr.vtf", placeholder_vtf(SIDE, True))
    z.close()

    for lump, data in ((L.FACES, faces_raw), (L.TEXINFO, texinfo), (L.TEXDATA, texdata),
                       (L.TEXDATA_STRING_DATA, sdata), (L.TEXDATA_STRING_TABLE, stable),
                       (L.ORIGINALFACES, orig_raw), (L.CUBEMAPS, cubes), (L.PAKFILE, buf.getvalue())):
        bsp.lumps[lump].data = bytes(data)
    if hdr_raw:
        bsp.lumps[L.FACES_HDR].data = bytes(hdr_raw)
    bsp.save()
    return {"cubemaps": len(p.origins), "patches": len(new_names), "texinfo_novos": len(extra), "removidos": dropped}


def run(path, radius: float = RADIUS, log=print) -> Plan | None:
    """Planeja e grava no BSP em `path` (o ht compile chama depois do vbsp)."""
    from srctools.bsp import BSP_LUMPS
    bsp = BSP(str(path))
    p = plan(bsp, radius)
    if p is None:
        log("cubemaps: nenhuma face com reflexo ligada a env_cubemap; nada a fazer")
        return None
    hdr = bool(bsp.lumps[BSP_LUMPS.LIGHTING_HDR].data) if BSP_LUMPS.LIGHTING_HDR in bsp.lumps else True
    del bsp
    r = apply(path, p, hdr=hdr)
    log(f"cubemaps: {r['cubemaps']} (raio {radius:g}u; {p.kept} do autor mantidos, {p.water} sobre a água; {p.surfaces} superfícies, {p.transitions} de transição), {r['patches']} materiais "
        f"corrigidos; área com cubemap atrás de parede {100 * p.blocked_before:.1f}% -> {100 * p.blocked_after:.1f}%")
    return p

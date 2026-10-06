"""`ht seal` / ht-vbsp: fecha os vãos por onde o mapa vaza (leak) com brushes de toolsskybox.

Grade de voxels igual à do `ht lint` (brush que sela marca o voxel se o CUBO o toca). Sementes: as entidades
pontuais (o que tem que ficar do lado de dentro). As tampas são o CORTE MÍNIMO entre as sementes e a borda da grade
(max-flow com capacidade 1 por voxel de ar): a menor superfície de ar que separa o mapa do vazio, ou seja, as
aberturas, e só elas. Fechamento morfológico e "caixa em volta" foram testados no rp_surdonoso e viraram casca do
mapa inteiro (1292 de 1670 entidades vazavam por dois vãos pequenos; o corte achou 7 voxels).

Limite do mundo (±16384): o vbsp não trata como parede, mas nada pode passar dele; conta como parede virtual na
busca e, onde o lado de dentro encosta nela, vira uma laje fina de skybox colada no limite.

Os blocos de voxels viram caixas (fusão gulosa) alinhadas à grade; cada face de caixa que encosta em voxel sólido
avança um voxel pra dentro dele (o voxel sólido pode estar só em parte coberto pelo brush: sem isso sobraria
uma fresta). Nunca avança pro lado de dentro do mapa.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from srctools import VMF, Vec

SEAL_VISGROUP = "ht_seal"     # tampas ficam nesse visgroup: o ht optimize não junta, o cache sabe quais são


def add_plug(v: VMF, lo: Vec, hi: Vec, material: str):
    """Tampa arredondada PRA FORA até o inteiro: cresce menos de 1u e nunca deixa face fora do grid (a grade fina
    é deslocada 0,25u; tampa em x,75 do lado de face inteira virava lasca nova de 0,25u e o vbsp vazava por ela)."""
    import math
    from hammertools.core import vmf as vmfio
    lo = Vec(*(max(-WORLD, math.floor(c + 1e-6)) for c in lo))
    hi = Vec(*(min(WORLD, math.ceil(c - 1e-6)) for c in hi))
    solid = v.make_prism(lo, hi, mat=material).solid
    solid.visgroup_ids.add(vmfio._visgroup(v, SEAL_VISGROUP, (0, 160, 255)).id)
    v.add_brush(solid)
    return solid


def plugs_in(v: VMF) -> list:
    """Tampas (do visgroup ht_seal) já no mapa: [(lo, hi, material)]."""
    ids = {vg.id for vg in v.vis_tree if vg.name == SEAL_VISGROUP}
    return [(*s.get_bbox(), s.sides[0].mat) for s in v.brushes if s.visgroup_ids & ids]


def fingerprint(vmf_text: str) -> str:
    """Impressão da geometria do mundo (bloco `world` do VMF, só planos e materiais, sem ids e sem as tampas do
    visgroup ht_seal): o cache de tampas só vale pra essa geometria. Tampa velha num mapa que mudou (ou que já foi
    fechado no Hammer) fica no meio de cômodo e o vbsp apaga as faces em volta (céu aparecendo pela parede)."""
    import hashlib
    i = vmf_text.find("\nworld\n")
    if i < 0:
        return ""
    end = re.search(r"\n(?:entity|cameras|cordons?|hidden)\b", vmf_text[i + 1:])
    block = vmf_text[i:i + 1 + end.start()] if end else vmf_text[i:]
    seal_ids = set(re.findall(r'"name" "' + SEAL_VISGROUP + r'"\s*"visgroupid" "(\d+)"', vmf_text))
    h = hashlib.sha1()
    for solid in block.split("\tsolid\n")[1:]:
        if any(f'"visgroupid" "{g}"' in solid for g in seal_ids):
            continue
        for m in re.finditer(r'"(plane|material)" "([^"]*)"', solid):
            h.update(m.group(2).encode("utf-8", "replace"))
        h.update(b"|")
    return h.hexdigest()


def save_cache(path, plugs, removed=(), geometry: str = "") -> None:
    import json
    path.write_text(json.dumps({
        "geometria": geometry,
        "tampas": [[list(map(float, lo)), list(map(float, hi)), m] for lo, hi, m in plugs],
        "removidas": [[c, [float(o.x), float(o.y), float(o.z)]] for c, o in removed],
    }))


def cache_valid(path, geometry: str) -> bool:
    """Cache feito pra esta geometria (cache antigo, sem impressão, conta como velho)."""
    import json
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and bool(geometry) and data.get("geometria") == geometry


def cached_removals(path) -> list:
    import json
    data = json.loads(path.read_text())
    return [] if isinstance(data, list) else [(c, Vec(*o)) for c, o in data.get("removidas", [])]


def apply_cache(v: VMF, path) -> tuple[int, int]:
    """Repõe as tampas de compilações anteriores (<mapa>.seal.json). Tampa que hoje contém a origem de alguma
    entidade é velha (o mapa mudou ali) e fica de fora. Devolve (aplicadas, descartadas)."""
    import json
    from hammertools import lint
    data = json.loads(path.read_text())
    plugs = data if isinstance(data, list) else data.get("tampas", [])
    # entidades de enfeite que estavam no vazio: tira as mesmas (classe e origem iguais)
    for cls, o in ([] if isinstance(data, list) else data.get("removidas", [])):
        o = Vec(*o)
        for e in list(v.entities):
            eo = lint._origin(e)
            if e["classname"] == cls and eo is not None and (eo - o).mag() < 1.0:
                v.remove_ent(e)
                break
    origins = [o for o in (lint._origin(e) for e in v.entities) if o is not None]
    used = dropped = 0
    for lo, hi, mat in plugs:
        lo, hi = Vec(*lo), Vec(*hi)
        if any(all(lo[k] < o[k] < hi[k] for k in range(3)) for o in origins):
            dropped += 1
            continue
        add_plug(v, lo, hi, mat)
        used += 1
    return used, dropped


WORLD = 16384.0
SLAB = 16.0
PAD = 3


@dataclass
class SealResult:
    sealed: bool = False
    voxel: float = 0.0
    boxes: list = field(default_factory=list)   # [(lo, hi)] dos brushes criados
    leaked_before: int = 0
    reason: str = ""


def _grid(v: VMF, res, voxel: float | None, shift=(0.0, 0.0, 0.0)):
    import numpy as np
    from hammertools import lint
    sealing = [s for s in v.brushes if lint._seals(s, res)]
    if not sealing:
        return None
    los = np.array([tuple(s.get_bbox()[0]) for s in sealing]).min(0)
    his = np.array([tuple(s.get_bbox()[1]) for s in sealing]).max(0)
    ext = float((his - los).max())
    vs = float(voxel) if voxel else max(8.0, 8.0 * -(-ext // (8 * 320)))
    pad = PAD
    # alinhada à grade (caixas em múltiplos do voxel), deslocada de `shift` voxel nas passadas extras
    origin = np.floor(los / vs) * vs - pad * vs - np.asarray(shift) * vs
    shape = tuple(int(np.ceil((h - o) / vs)) + pad for o, h in zip(origin, his))
    solid = np.zeros(shape, dtype=bool)
    lint._rasterize(solid, origin, vs, sealing, expand=True)
    # parede virtual: voxel cujo centro passa do limite do mundo
    centers = [origin[a] + (np.arange(shape[a]) + 0.5) * vs for a in range(3)]
    virtual = np.zeros(shape, dtype=bool)
    for a in range(3):
        out = np.abs(centers[a]) > WORLD
        sl = [slice(None)] * 3
        sl[a] = out
        virtual[tuple(sl)] = True
    return solid, virtual, origin, vs


def _seeds(v: VMF, origin, vs, shape):
    import numpy as np
    from hammertools import lint
    out = []
    for e in v.entities:
        if e.solids or e.hidden or e["classname"].startswith("ht_") or e["classname"].lower() in lint.VBSP_CONSUMED:
            continue
        p = lint._origin(e)
        if p is None:
            continue
        i = np.floor((np.array([p.x, p.y, p.z]) - origin) / vs).astype(int)
        if np.all(i >= 0) and np.all(i < np.array(shape)):
            out.append(tuple(i))
    return out


def _boundary_labels(lab):
    import numpy as np
    faces = [lab[0], lab[-1], lab[:, 0], lab[:, -1], lab[:, :, 0], lab[:, :, -1]]
    s = set(np.unique(np.concatenate([f.ravel() for f in faces])).tolist())
    s.discard(0)
    return s


def _leaks(blocked, seeds) -> tuple[bool, object, set]:
    """(vaza?, labels, labels das sementes)."""
    from scipy import ndimage
    lab, _ = ndimage.label(~blocked)
    seedlabs = {int(lab[c]) for c in seeds if lab[c]}
    return bool(seedlabs & _boundary_labels(lab)), lab, seedlabs


def axis_hits(blocked):
    """Pra cada voxel, em quantas das 6 direções dos eixos existe sólido à frente (até a borda da grade)."""
    import numpy as np
    hits = np.zeros(blocked.shape, dtype=np.int8)
    for ax in range(3):
        b = np.moveaxis(blocked, ax, -1)
        ahead = np.flip(np.logical_or.accumulate(np.flip(b, -1), axis=-1), -1)      # sólido daqui pra frente
        behind = np.logical_or.accumulate(b, axis=-1)
        # "à frente" exclui o próprio voxel: desloca uma posição
        fwd = np.zeros_like(ahead)
        fwd[..., :-1] = ahead[..., 1:]
        back = np.zeros_like(behind)
        back[..., 1:] = behind[..., :-1]
        hits += np.moveaxis(fwd.astype(np.int8) + back.astype(np.int8), -1, ax)
    return hits


INSIDE_HITS = 6     # cercado nos 6 eixos: lado de dentro (fonte do corte)
OUTSIDE_HITS = 2    # sólido em no máximo 2 eixos: vazio (sumidouro)
SEED_RADIUS = 2     # voxels em volta de cada entidade que nunca viram tampa
TIE = 64            # capacidade de um voxel: TIE² (área) + TIE·profundidade (desempate); cabe em int32


def _neighbor_pairs(air, idx, conn: int):
    """Pares (u, w) de voxels de ar vizinhos: 6 = pelas faces; 18 = faces e arestas (passagem na diagonal: a
    fresta do vbsp anda torta em relação à grade e os voxels dela só se tocam pela aresta)."""
    offs = [(1, 0, 0), (0, 1, 0), (0, 0, 1)]
    if conn == 18:
        offs += [(1, 1, 0), (1, -1, 0), (1, 0, 1), (1, 0, -1), (0, 1, 1), (0, 1, -1)]
    for d in offs:
        a, b = [], []
        for k in range(3):
            if d[k] > 0:
                a.append(slice(0, -d[k]))
                b.append(slice(d[k], None))
            elif d[k] < 0:
                a.append(slice(-d[k], None))
                b.append(slice(0, d[k]))
            else:
                a.append(slice(None))
                b.append(slice(None))
        m = air[tuple(a)] & air[tuple(b)]
        yield idx[tuple(a)][m], idx[tuple(b)][m]


def cut_masks(blocked, src_mask, sink_mask, protect=None, conn: int = 6):
    """Corte mínimo genérico: voxels de ar que separam `src_mask` de `sink_mask`. Capacidade de um voxel = área
    (TIE²) + desempate pela distância ao sumidouro (o corte fica no plano da abertura, não num funil pra dentro).
    `protect`: voxels que nunca entram no corte."""
    import numpy as np
    from scipy import ndimage, sparse
    from scipy.sparse.csgraph import breadth_first_order, maximum_flow
    air = ~blocked
    n = int(air.sum())
    idx = np.full(blocked.shape, -1, dtype=np.int32)
    idx[air] = np.arange(n, dtype=np.int32)
    src, snk = 2 * n, 2 * n + 1
    big = np.int32(2 ** 30)
    depth = ndimage.distance_transform_cdt(~(sink_mask & air), metric="taxicab").astype(np.int64)
    cap = (TIE * np.minimum(depth[air], TIE - 1) + TIE * TIE).astype(np.int32)
    del depth
    if protect is not None:
        cap[idx[protect & air]] = big
    rows, cols, caps = [np.arange(n, dtype=np.int32) * 2], [np.arange(n, dtype=np.int32) * 2 + 1], [cap]
    for u, w in _neighbor_pairs(air, idx, conn):
        rows += [u * 2 + 1, w * 2 + 1]
        cols += [w * 2, u * 2]
        caps += [np.full(len(u), big, np.int32)] * 2
    sd = idx[src_mask & air]
    bi = idx[sink_mask & air & ~src_mask]
    rows += [np.full(len(sd), src, np.int32), bi * 2 + 1]
    cols += [sd * 2, np.full(len(bi), snk, np.int32)]
    caps += [np.full(len(sd), big, np.int32), np.full(len(bi), big, np.int32)]
    N = 2 * n + 2
    r, c, k = np.concatenate(rows), np.concatenate(cols), np.concatenate(caps)
    del rows, cols, caps
    G = sparse.csr_matrix((k, (r, c)), shape=(N, N))
    del r, c, k
    flow = maximum_flow(G, src, snk, method="dinic").flow.tocsr()
    G.sort_indices()
    flow.sort_indices()
    # resíduo: aresta com folga, e o reverso de aresta com fluxo
    Gc = G.tocoo()
    f = np.asarray(flow[Gc.row, Gc.col]).ravel()
    del flow
    fwd = Gc.data > f
    back = f > 0
    R = sparse.csr_matrix((np.ones(int(fwd.sum() + back.sum()), np.int8),
                           (np.concatenate([Gc.row[fwd], Gc.col[back]]), np.concatenate([Gc.col[fwd], Gc.row[back]]))),
                          shape=(N, N))
    del Gc, f, G
    reach = np.zeros(N, dtype=bool)
    reach[breadth_first_order(R, src, directed=True, return_predecessors=False)] = True
    cut = np.zeros(blocked.shape, dtype=bool)
    cut[air] = reach[0:2 * n:2] & ~reach[1:2 * n:2]
    return cut


def mincut(blocked, seeds, hits=None):
    """Corte da grade inteira. Fonte: ar cercado nos 6 eixos CONECTADO às entidades (bolsão côncavo do vazio fora do
    mapa também é cercado, mas não tem entidade: fica livre) + raio de proteção em volta de cada entidade.
    Sumidouro: borda da grade e ar com sólido em no máximo OUTSIDE_HITS eixos."""
    import numpy as np
    from scipy import ndimage
    air = ~blocked
    if hits is None:
        hits = axis_hits(blocked)
    sink_mask = air & (hits <= OUTSIDE_HITS)
    edge = np.zeros(blocked.shape, dtype=bool)
    edge[0] = edge[-1] = True
    edge[:, 0] = edge[:, -1] = True
    edge[:, :, 0] = edge[:, :, -1] = True
    seed_mask = np.zeros(blocked.shape, dtype=bool)
    for c in seeds:
        if air[c] and not sink_mask[c]:
            seed_mask[c] = True
    near = ndimage.binary_dilation(seed_mask, iterations=SEED_RADIUS) & air & ~sink_mask
    enclosed = air & (hits >= INSIDE_HITS)
    lab, _ = ndimage.label(enclosed | near)
    keep = np.unique(lab[seed_mask])
    src_mask = np.isin(lab, keep[keep > 0]) & (enclosed | near)
    del lab, enclosed
    return cut_masks(blocked, src_mask, (sink_mask | edge) & air, protect=near)


def boxes(mask):
    """Fusão gulosa de voxels em caixas: [(i0, i1)] com i1 exclusivo."""
    import numpy as np
    m = mask.copy()
    out = []
    for i, j, k in zip(*np.nonzero(m)):
        if not m[i, j, k]:
            continue
        i1 = i + 1
        while i1 < m.shape[0] and m[i1, j, k]:
            i1 += 1
        j1 = j + 1
        while j1 < m.shape[1] and m[i:i1, j1, k].all():
            j1 += 1
        k1 = k + 1
        while k1 < m.shape[2] and m[i:i1, j:j1, k1].all():
            k1 += 1
        m[i:i1, j:j1, k:k1] = False
        out.append((np.array([i, j, k]), np.array([i1, j1, k1])))
    return out


def _grow_into_solid(i0, i1, solid, interior):
    """Avança cada face um voxel se a camada vizinha não tem nada do lado de dentro (só sólido/vazio)."""
    import numpy as np
    a, b = i0.copy(), i1.copy()
    shape = np.array(solid.shape)
    for ax in range(3):
        for side in (0, 1):
            sl = [slice(i0[0], i1[0]), slice(i0[1], i1[1]), slice(i0[2], i1[2])]
            pos = i0[ax] - 1 if side == 0 else i1[ax]
            if pos < 0 or pos >= shape[ax]:
                continue
            sl[ax] = slice(pos, pos + 1)
            layer_solid, layer_in = solid[tuple(sl)], interior[tuple(sl)]
            if layer_solid.any() and not layer_in.any():
                if side == 0:
                    a[ax] -= 1
                else:
                    b[ax] += 1
    return a, b


# passadas: grade alinhada e deslocada meio voxel. Fresta menor que o voxel some ou aparece conforme o alinhamento
# (no rp_surdonoso, uma passagem em -406 -16164 -228 só existia na grade do lint, que não é alinhada).
SHIFTS = ((0.0, 0.0, 0.0), (0.5, 0.5, 0.5), (0.5, 0.0, 0.0), (0.0, 0.5, 0.0), (0.0, 0.0, 0.5))
MAX_PASSES = 12


def _pass(v: VMF, res, vs: float | None, shift, material: str, r: SealResult) -> tuple[int, bool]:
    """Uma passada numa grade: (entidades que vazavam nela, conseguiu?). Acrescenta as tampas em `v` e `r.boxes`."""
    import numpy as np
    from scipy import ndimage
    g = _grid(v, res, vs, shift)
    if g is None:
        r.reason = "nenhum brush de mundo que sele"
        return 0, False
    solid, virtual, origin, vs = g
    r.voxel = vs
    seeds = [c for c in _seeds(v, origin, vs, solid.shape) if not solid[c] and not virtual[c]]
    blocked0 = solid | virtual
    leaked, lab, seedlabs = _leaks(blocked0, seeds)
    out_labels = _boundary_labels(lab)
    n_leaked = sum(1 for c in seeds if lab[c] in out_labels)
    st = ndimage.generate_binary_structure(3, 1)
    if not leaked:
        interior = np.isin(lab, list(seedlabs))
        plug = np.zeros_like(solid)
    else:
        del lab
        plug = mincut(blocked0, seeds)          # MemoryError sobe pro seal() trocar o voxel
        if any(plug[c] for c in seeds):
            r.reason = "o corte passou por uma entidade"
            return n_leaked, False
        leaked2, lab2, seedlabs2 = _leaks(blocked0 | plug, seeds)
        if leaked2:
            r.reason = "o corte mínimo não separou as entidades do vazio"
            return n_leaked, False
        interior = np.isin(lab2, list(seedlabs2))
    # limite do mundo encostado no lado de dentro vira laje (o vbsp não conhece a parede virtual)
    limit = virtual & ndimage.binary_dilation(interior, st)

    def world(i):
        return origin + np.asarray(i) * vs

    made = []
    for i0, i1 in boxes(plug):
        a, b = _grow_into_solid(i0, i1, solid, interior)
        made.append((world(a), world(b)))
    for i0, i1 in boxes(limit):
        lo, hi = world(i0), world(i1)
        for ax in range(3):
            if hi[ax] > WORLD:
                lo[ax], hi[ax] = WORLD - SLAB, WORLD
            elif lo[ax] < -WORLD:
                lo[ax], hi[ax] = -WORLD, -WORLD + SLAB
        made.append((lo, hi))
    for lo, hi in made:
        lo = np.clip(lo, -WORLD, WORLD)
        hi = np.clip(hi, -WORLD, WORLD)
        if np.any(hi - lo <= 0):
            continue
        r.boxes.append(add_plug(v, Vec(*lo), Vec(*hi), material).get_bbox())
    return n_leaked, True


def seal(v: VMF, res=None, voxel: float | None = None, material: str = "tools/toolsskybox") -> SealResult:
    """Fecha os vãos de leak de `v` (no lugar). Passa pelas grades de SHIFTS até todas dizerem que não vaza
    (e nenhuma laje de limite faltar). Não mexe em mapa que já não vaza."""
    from hammertools import lint
    res = res or lint.Resources()
    r = SealResult()
    vs = voxel
    clean = 0                                   # passadas seguidas sem acrescentar nada
    for n in range(MAX_PASSES):
        before = len(r.boxes)
        try:
            leaked, ok = _pass(v, res, vs, SHIFTS[n % len(SHIFTS)], material, r)
        except MemoryError:                     # mapa grande pra RAM: voxel 2x maior (8x menos ar no grafo)
            vs = (r.voxel or 88.0) * 2
            continue
        vs = r.voxel
        if n == 0:
            r.leaked_before = leaked
        if not ok:
            return r
        clean = clean + 1 if len(r.boxes) == before else 0
        if clean >= len(SHIFTS):
            r.sealed = True
            r.reason = "não vazava" if not r.boxes else ""
            return r
    r.reason = f"ainda vaza depois de {MAX_PASSES} passadas"
    return r


# --------------------------------------------------------------------------- refino pelo pointfile do vbsp
# refino local: (voxel, margem em volta do trecho em que o caminho do vbsp sai do lado de dentro), do mais grosso
# ao mais fino; voxel sólido só se o CENTRO está no brush (fresta de meio voxel já aparece)
# (o desenho do vbsp liga centros de portal: a fresta pode estar a centenas de unidades da linha)
LEVELS = ((8.0, 256.0), (4.0, 128.0), (2.0, 64.0), (1.0, 32.0))


def read_pointfile(path) -> list:
    pts = []
    for line in open(path, encoding="utf-8", errors="replace"):
        parts = line.split()
        if len(parts) >= 3:
            try:
                pts.append(Vec(float(parts[0]), float(parts[1]), float(parts[2])))
            except ValueError:
                continue
    return pts


def _samples(points, step: float = 4.0) -> list:
    out = []
    for a, b in zip(points, points[1:]):
        n = max(1, int((b - a).mag() // step))
        out += [a + (b - a) * (k / n) for k in range(n)]
    if points:
        out.append(points[-1])
    return out


def crossing(points, classify, step: float = 4.0):
    """Trecho do caminho em que ele passa do lado de dentro pro vazio (pela grade grossa): (ponto dentro, ponto fora),
    ou None. `classify(p)` -> 'in' | 'out' | 'solid'."""
    samples = _samples(points, step)
    prev = None                      # (classe, ponto) do último ponto fora de sólido
    for p in samples:
        c = classify(p)
        if c == "solid":
            continue
        if prev is not None and prev[0] != c:
            return (prev[1], p) if prev[0] == "in" else (p, prev[1])
        prev = (c, p)
    return None


def coarse_classifier(v: VMF, res):
    """Classe de um ponto na grade grossa ('in' lado de dentro / 'out' vazio / 'solid'), com `.volume(lo, shape,
    fine)` pra classificar um recorte fino inteiro (0 sólido, 1 dentro, 2 vazio). None sem brush que sele."""
    import numpy as np
    from scipy import ndimage
    g = _grid(v, res, None)
    if g is None:
        return None
    solid, virtual, origin, vs = g
    blocked = solid | virtual
    lab, _ = ndimage.label(~blocked)
    # lado de dentro = todo ar fechado (não ligado à borda da grade). Sala fechada cujas entidades estão todas
    # coladas na parede não tem semente, mas está selada: contá-la como vazio removia luzes do mapa principal
    inside = set(range(1, int(lab.max()) + 1)) - _boundary_labels(lab)
    shape = np.array(solid.shape)

    def coarse(p):
        i = np.floor((np.array([p.x, p.y, p.z]) - origin) / vs).astype(int)
        if np.any(i < 0) or np.any(i >= shape):
            return "out"
        i = tuple(i)
        if blocked[i]:
            return "solid"
        return "in" if int(lab[i]) in inside else "out"

    inside_arr = np.zeros(int(lab.max()) + 1, dtype=bool)
    inside_arr[list(inside)] = True

    def volume(lo, fshape, fine):
        idx, ok = [], []
        for k in range(3):
            i = np.floor((lo[k] + (np.arange(fshape[k]) + 0.5) * fine - origin[k]) / vs).astype(int)
            ok.append((i >= 0) & (i < shape[k]))
            idx.append(np.clip(i, 0, shape[k] - 1))
        ix = np.ix_(*idx)
        cls = np.where(blocked[ix], 0, np.where(inside_arr[lab[ix]], 1, 2)).astype(np.int8)
        cls[~(ok[0][:, None, None] & ok[1][None, :, None] & ok[2][None, None, :])] = 2
        return cls

    def near_out(p, cells: int = 2) -> bool:
        """Ponto em voxel grosso sólido ou a até `cells` voxels de vazio: candidato a bolsão com fresta."""
        i = np.floor((np.array([p.x, p.y, p.z]) - origin) / vs).astype(int)
        lo, hi = np.maximum(i - cells, 0), np.minimum(i + cells + 1, shape)
        if np.any(hi <= lo):
            return True
        sl = tuple(slice(lo[k], hi[k]) for k in range(3))
        out = ~blocked[sl] & ~inside_arr[lab[sl]]
        return bool(blocked[tuple(np.clip(i, 0, shape - 1))] or out.any())

    coarse.volume = volume
    coarse.near_out = near_out
    coarse.voxel = vs
    return coarse


# entidade que só enfeita (luz, sprite, prop) e ficou do lado do vazio depois do selo: no vazio ela não ilumina nem
# mostra nada que se veja (face virada pro vazio não é desenhada), mas o vbsp conta como leak. Sai do build/.
VISUAL_PREFIXES = ("light", "env_sprite", "env_lightglow", "prop_static", "prop_dynamic", "prop_physics",
                   "point_spotlight", "beam_spotlight", "env_smokestack", "func_dustmotes")


def outside_entities(v: VMF, res, coarse=None, region=None) -> list:
    """Entidades pontuais do lado do vazio pela grade grossa (no vazio, ou enterradas sem nenhum vizinho de ar
    do lado de dentro): [(entidade, origem)]."""
    import numpy as np
    from hammertools import lint
    coarse = coarse or coarse_classifier(v, res)
    if coarse is None:
        return []
    out = []
    for e in v.entities:
        if e.solids or e.hidden or e["classname"].startswith("ht_") or e["classname"].lower() in lint.VBSP_CONSUMED:
            continue
        o = lint._origin(e)
        if o is None or (region is not None and not all(region[0][k] <= o[k] <= region[1][k] for k in range(3))):
            continue
        c = coarse(o)
        if c == "in":
            continue
        if c == "solid":
            step = coarse.voxel
            near = [coarse(o + Vec(dx, dy, dz) * step) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)]
            if "in" in near or "out" not in near:
                continue
        out.append((e, o))
    return out


STRAY_RADIUS = 256.0     # enfeite solto no vazio: nenhum brush que sela a essa distância


def _stray(o, boxes) -> bool:
    import numpy as np
    if not len(boxes):
        return True
    p = np.array(tuple(o))
    return not bool(np.any(np.all((boxes[:, :3] - STRAY_RADIUS <= p) & (p <= boxes[:, 3:] + STRAY_RADIUS), axis=1)))


def drop_outside_visuals(v: VMF, res, coarse=None, region=None) -> tuple[list, list]:
    """Tira do mapa as entidades visuais do lado do vazio (só dentro de `region`: perto do caminho do leak que o
    vbsp mostrou; no mapa inteiro a grade grossa erra em parede grossa e laje) E soltas: sem brush que sela a
    STRAY_RADIUS. Com vão de verdade a grade grossa chama a sala inteira de vazio; a luz da sala não é enfeite
    perdido. Devolve (removidas, outras)."""
    import numpy as np
    from hammertools import lint
    sealing = [s for s in v.brushes if lint._seals(s, res)]
    boxes_all = np.array([tuple(s.get_bbox()[0]) + tuple(s.get_bbox()[1]) for s in sealing]) if sealing \
        else np.zeros((0, 6))
    removed, kept = [], []
    for e, o in outside_entities(v, res, coarse, region):
        if not _stray(o, boxes_all):
            continue
        if e["classname"].lower().startswith(VISUAL_PREFIXES):
            v.remove_ent(e)
            removed.append((e["classname"], o))
        else:
            kept.append((e["classname"], o))
    return removed, kept


POCKET_HALF = 128.0     # meio lado do recorte em volta de cada entidade na varredura de bolsões
POCKET_FINE = 2.0


POCKET_REGION = 512.0   # em volta do caminho do vbsp: onde procurar outros bolsões na mesma rodada


def path_region(points, coarse) -> tuple | None:
    """Caixa dos pontos do caminho que não estão no vazio grosso (as pontas no topo/fundo do mundo ficam de fora)."""
    import numpy as np
    pts = [p for p in points if coarse(p) != "out"]
    if not pts:
        return None
    a = np.array([tuple(p) for p in pts])
    return a.min(0) - POCKET_REGION, a.max(0) + POCKET_REGION


def seal_pockets(v: VMF, res, region=None, material: str = "tools/toolsnodraw", log=None, coarse=None) -> list:
    """Sem esperar o vbsp: cada entidade em voxel grosso sólido ou perto do vazio é testada num recorte fino
    (2u, vizinhança de 18) em volta dela; se o bolsão dela encosta no vazio dentro do recorte, corte local ali.
    No rp_surdonoso eram luminárias uma atrás da outra, cada uma num bolsão com fresta, e o vbsp só mostra uma por
    compilação."""
    import numpy as np
    from scipy import ndimage
    from hammertools import lint
    coarse = coarse or coarse_classifier(v, res)
    if coarse is None:
        return []
    st = ndimage.generate_binary_structure(3, 2)
    cands = []
    for e in v.entities:
        if e["classname"].startswith("ht_") or e["classname"].lower() in lint.VBSP_CONSUMED or e.hidden:
            continue
        o = lint._origin(e)
        if o is None or (region is not None and not all(region[0][k] <= o[k] <= region[1][k] for k in range(3))):
            continue
        if coarse.near_out(o):
            cands.append(o)
    sealing_all = [s for s in v.brushes if lint._seals(s, res)]
    boxes_all = np.array([tuple(s.get_bbox()[0]) + tuple(s.get_bbox()[1]) for s in sealing_all]) if sealing_all \
        else np.zeros((0, 6))
    made = []
    for o in cands:
        lo = np.floor((np.array(tuple(o)) - POCKET_HALF) / POCKET_FINE) * POCKET_FINE + GRID_OFFSET
        hi = lo + 2 * POCKET_HALF
        fshape = tuple(int(x) for x in (hi - lo) / POCKET_FINE)
        hit = np.all(boxes_all[:, 3:] >= lo, axis=1) & np.all(boxes_all[:, :3] <= hi, axis=1)
        sealing = [sealing_all[i] for i in np.nonzero(hit)[0]]
        fs = np.zeros(fshape, dtype=bool)
        lint._rasterize(fs, lo, POCKET_FINE, sealing, expand=False)
        ei = tuple(np.floor((np.array(tuple(o)) - lo) / POCKET_FINE).astype(int))
        if fs[ei]:
            continue
        lab, _ = ndimage.label(~fs, structure=st)
        comp = lab == lab[ei]
        cls = coarse.volume(lo, fshape, POCKET_FINE)
        out = comp & (cls == 2)
        if not out.any():
            continue                    # bolsão fechado (ou só ligado ao lado de dentro) neste recorte
        j = np.argwhere(out)[0]
        out_pt = Vec(*(lo + (j + 0.5) * POCKET_FINE))
        got = _local_cut(v, res, (o, out_pt), coarse, POCKET_FINE, POCKET_HALF / 2, material, o, ())
        if got and log:
            log(f"  bolsão em {o.x:.0f} {o.y:.0f} {o.z:.0f}: {len(got)} tampa(s)")
        made += got
    return made


def seal_at_pointfile(v: VMF, res, points, material: str = "tools/toolsnodraw") -> list:
    """Tampa a fresta por onde o caminho do vbsp (pointfile) sai do mapa, com grade fina só em volta dela. Fonte e
    sumidouro na borda do recorte vêm da grade grossa (lado de dentro x vazio). Devolve as caixas criadas.
    Material nodraw: sela e o vbsp não gera face nenhuma (fresta de poucas unidades não aparece; skybox ali só
    somaria vértices num mapa que costuma estar no teto)."""
    import numpy as np
    from scipy import ndimage
    from hammertools import lint
    if len(points) < 2:
        return []
    coarse = coarse_classifier(v, res)
    if coarse is None:
        return []

    # o pointfile do vbsp termina na entidade que vazou: orienta da entidade pro vazio
    origins = [o for o in (lint._origin(e) for e in v.entities) if o is not None]   # inclui func_door etc.

    def at_entity(p):
        return any((o - p).mag() < 2.0 for o in origins)
    if at_entity(points[-1]) and not at_entity(points[0]):
        points = list(reversed(points))
    ent = points[0] if at_entity(points[0]) else None
    slivers = sliver_plugs(v, res, points, material)
    if slivers:
        return slivers
    seg = crossing(points, coarse)
    if seg is None and ent is not None:
        # entidade num bolsão menor que o voxel grosso (a grade grossa vê sólido): da entidade ao primeiro ponto no vazio
        out_pt = next((p for p in _samples(points) if coarse(p) == "out"), None)
        seg = (ent, out_pt) if out_pt is not None else None
    if seg is None:
        return []
    path = _samples(points, 1.0)
    for fine, margin in LEVELS:
        n_wide = len(WIDE)
        made = _local_cut(v, res, seg, coarse, fine, margin, material, ent, path)
        if made or len(WIDE) > n_wide:      # vão largo nesta resolução continua largo nas mais finas
            return made
    return []


GRID_OFFSET = 0.25
CRACK_MAX = 8.0               # espessura máxima de fresta que o ht-vbsp tampa sozinho; mais largo é vão de verdade
WIDE: list = []               # vãos de verdade achados pelos cortes locais [(lo, hi)]: aviso, não tampa
EXTRA_GROW = 2                # depois de achar a fresta, quantas vezes ainda aumenta o recorte
LOCAL_BUDGET = 12_000_000     # voxels no recorte local (memória do corte ~ 400 bytes por voxel de ar)


def _local_cut(v: VMF, res, seg, coarse, fine: float, margin: float, material: str, ent=None, path=()) -> list:
    """Corta no recorte em volta do trecho; se o corte encosta na borda do recorte, a fresta continua pra lá:
    aumenta o recorte nesse lado e refaz (até LOCAL_BUDGET voxels)."""
    import numpy as np
    a, b = seg
    # deslocada 0,25u: o centro do voxel nunca cai em face no grid (inteira ou ,5); centro em cima da face
    # contava como sólido e escondia a passagem rente à parede por onde o vbsp vaza
    lo = np.floor((np.minimum(np.array(tuple(a)), np.array(tuple(b))) - margin) / fine) * fine + GRID_OFFSET
    hi = np.ceil((np.maximum(np.array(tuple(a)), np.array(tuple(b))) + margin) / fine) * fine + GRID_OFFSET
    extra = EXTRA_GROW
    while True:
        res_cut = _crop_cut(v, res, lo, hi, coarse, fine, ent, path)
        if res_cut == "cega":
            return []           # esta resolução não enxerga a passagem do vbsp: tenta a mais fina
        if res_cut is None:
            # dentro e vazio ainda não se ligam no recorte: a fresta está mais longe, aumenta em todo lado
            grow_lo = grow_hi = np.ones(3, dtype=bool)
        else:
            cut, fsolid, interior = res_cut
            grow_lo = np.array([cut.take(0, axis=k).any() for k in range(3)])
            grow_hi = np.array([cut.take(-1, axis=k).any() for k in range(3)])
            if not grow_lo.any() and not grow_hi.any() and extra > 0:
                # parede rachada costuma ter várias frestas lado a lado: recorte maior tampa todas de uma vez
                # (cada recompilação do vbsp só mostra uma)
                extra -= 1
                grow_lo = grow_hi = np.ones(3, dtype=bool)
        nlo = lo - grow_lo * margin * 2
        nhi = hi + grow_hi * margin * 2
        nlo, nhi = np.maximum(nlo, -WORLD - fine), np.minimum(nhi, WORLD + fine)
        if (np.all(nlo == lo) and np.all(nhi == hi)) or np.prod((nhi - nlo) / fine) > LOCAL_BUDGET:
            break
        lo, hi = nlo, nhi
    if res_cut is None:
        return []
    # cirúrgico: só fecha FRESTA (algum lado da tampa <= CRACK_MAX antes de crescer pra dentro da parede). Corte mais
    # largo em todo eixo é vão de verdade (porta, área sem teto): tampa ali ocupa espaço do mapa (nodraw no meio da
    # passagem); fica de fora e vai pra WIDE, pro aviso de fechar no Hammer
    made, wide = [], []
    origins = _entity_origins(v)
    for i0, i1 in boxes(cut):
        blo0, bhi0 = lo + i0 * fine, lo + i1 * fine
        # tampa em volta de entidade (bolsão "fechado" num cubo de nodraw) também é vão de verdade: a entidade está
        # numa sala aberta, não numa fresta
        if min((i1 - i0) * fine) > CRACK_MAX or any(
                all(blo0[k] - fine <= o[k] <= bhi0[k] + fine for k in range(3)) for o in origins):
            wide.append((Vec(*blo0), Vec(*bhi0)))
            continue
        p, q = _grow_into_solid(i0, i1, fsolid, interior)
        blo = np.clip(lo + p * fine, -WORLD, WORLD)
        bhi = np.clip(lo + q * fine, -WORLD, WORLD)
        if np.any(bhi - blo <= 0):
            continue
        made.append(add_plug(v, Vec(*blo), Vec(*bhi), material))
    if wide:
        WIDE.extend(wide)
        # o corte tem vão de verdade: as frestas em volta sozinhas não selam, tampá-las só suja o mapa
        for solid in made:
            v.remove_brush(solid)
        return []
    return [solid.get_bbox() for solid in made]


def _entity_origins(v: VMF) -> list:
    from hammertools import lint
    return [o for o in (lint._origin(e) for e in v.entities if not e.solids) if o is not None]


def _crop_cut(v: VMF, res, lo, hi, coarse, fine: float, ent=None, path=()):
    """(corte, sólidos, lado de dentro) no recorte lo..hi; None se não há o que cortar; "cega" se algum ponto do
    caminho do vbsp cai em voxel sólido (a resolução não vê a passagem: um corte aqui fecharia outra coisa)."""
    import numpy as np
    from scipy import ndimage
    from hammertools import lint
    fshape = tuple(int(x) for x in (hi - lo) / fine)
    sealing = [s for s in v.brushes if lint._seals(s, res)
               and all(s.get_bbox()[1][k] >= lo[k] and s.get_bbox()[0][k] <= hi[k] for k in range(3))]
    fsolid = np.zeros(fshape, dtype=bool)
    lint._rasterize(fsolid, lo, fine, sealing, expand=False)
    centers = [lo[k] + (np.arange(fshape[k]) + 0.5) * fine for k in range(3)]
    fvirtual = np.zeros(fshape, dtype=bool)
    for k in range(3):
        sl = [slice(None)] * 3
        sl[k] = np.abs(centers[k]) > WORLD
        fvirtual[tuple(sl)] = True
    fblocked = fsolid | fvirtual
    for p in path:
        i = np.floor((np.array(tuple(p)) - lo) / fine).astype(int)
        if np.all(i >= 0) and np.all(i < np.array(fshape)) and fsolid[tuple(i)]:
            return "cega"
    # cada voxel fino herda a classe do voxel grosso: ar "dentro" é fonte, ar "vazio" é sumidouro; só o ar fino
    # dentro de voxel grosso SÓLIDO fica livre, então o corte só cai nas frestas dentro das paredes
    cls = coarse.volume(lo, fshape, fine)
    src = (cls == 1) & ~fblocked
    snk = (cls == 2) & ~fblocked
    del cls
    if ent is not None:                     # a própria entidade que vazou é lado de dentro
        i = tuple(np.floor((np.array(tuple(ent)) - lo) / fine).astype(int))
        if all(0 <= i[k] < fshape[k] for k in range(3)) and not fblocked[i]:
            src[i] = True
    if not src.any() or not snk.any():
        return None
    cut = cut_masks(fblocked, src, snk, conn=18)
    if not cut.any():
        return None
    flab, _ = ndimage.label(~(fblocked | cut), structure=ndimage.generate_binary_structure(3, 2))
    interior = np.isin(flab, np.unique(flab[src])[1:])
    return cut, fsolid, interior


# --------------------------------------------------------------------------- lasca fora do grid
SLIVER_MAX = 4.0    # vão entre duas faces de brush que conta como lasca (vértice fora do grid: 0,4u no rp_surdonoso)


def sliver_plugs(v: VMF, res, points, material: str = "tools/toolsnodraw") -> list:
    """Lascas finas (menores que qualquer voxel) entre dois brushes no caminho do vbsp, com teste exato de ponto
    em brush: ponto do caminho no ar com brush dos dois lados a menos de SLIVER_MAX num eixo. A tampa preenche o
    vão entre as duas faces, na área em que os dois brushes se sobrepõem nos outros eixos."""
    from collections import defaultdict
    from hammertools import lint
    from hammertools.core import geom
    sealing = [s for s in v.brushes if lint._seals(s, res)]
    B = 128.0
    buckets = defaultdict(list)
    planes = {}
    for s in sealing:
        lo, hi = s.get_bbox()
        planes[id(s)] = [geom.outward(sd) for sd in s.sides]
        for bx in range(int(lo.x // B), int(hi.x // B) + 1):
            for by in range(int(lo.y // B), int(hi.y // B) + 1):
                for bz in range(int(lo.z // B), int(hi.z // B) + 1):
                    buckets[(bx, by, bz)].append(s)

    def near(p):
        return buckets.get((int(p.x // B), int(p.y // B), int(p.z // B)), [])

    def inside(s, p):
        return all(n.dot(p - q) <= 1e-3 for n, q in planes[id(s)])

    axes = (Vec(1, 0, 0), Vec(0, 1, 0), Vec(0, 0, 1))
    made, seen = [], set()
    for p in _samples(points, 0.5):
        cands = near(p)
        if any(inside(s, p) for s in cands):
            continue
        for k, d in enumerate(axes):
            hits = []
            for sign in (1, -1):
                best = None
                for s in near(p + d * (sign * SLIVER_MAX)) + cands:
                    t = lint._ray_entry(planes[id(s)], p, d * sign)
                    if t is not None and t <= SLIVER_MAX and (best is None or t < best[0]):
                        best = (t, s)
                hits.append(best)
            if not hits[0] or not hits[1] or hits[0][0] + hits[1][0] > SLIVER_MAX:
                continue
            (tp, sp), (tm, sm) = hits
            alo, ahi = sp.get_bbox(), sm.get_bbox()
            lo = [max(alo[0][j], ahi[0][j]) for j in range(3)]
            hi = [min(alo[1][j], ahi[1][j]) for j in range(3)]
            lo[k], hi[k] = p[k] - tm, p[k] + tp
            if any(hi[j] - lo[j] <= 0 for j in range(3)):
                continue
            # a tampa tem que conter o ponto do caminho (sobreposição dos dois brushes que não cobre o ponto é
            # outra lasca, não a que o vbsp usou)
            if any(not (lo[j] - 1e-3 <= p[j] <= hi[j] + 1e-3) for j in range(3)):
                continue
            key = tuple(round(x, 2) for x in lo + hi)
            if key in seen:
                continue
            seen.add(key)
            made.append(add_plug(v, Vec(*lo), Vec(*hi), material).get_bbox())
            break
    return made


SLIVER_GAP = 1.0    # vão entre faces paralelas de dois brushes que é fechado de uma vez (vértice fora do grid)


def close_slivers(v: VMF, res, gap: float = SLIVER_GAP, material: str = "tools/toolsnodraw") -> list:
    """Fecha de uma vez todas as lascas do mapa: faces alinhadas aos eixos, de brushes diferentes, viradas uma pra
    outra a 0 < distância <= `gap`, com área sobreposta. Cada uma vira uma caixa de nodraw no vão (sem face, sem
    vértice). No rp_surdonoso eram 95 com gap 1u; achar uma por compile do vbsp levava ~2 min cada."""
    from collections import defaultdict
    from hammertools import lint
    from hammertools.core import geom
    def area2(poly, o):
        a = 0.0
        for i in range(len(poly)):
            p, q = poly[i], poly[(i + 1) % len(poly)]
            a += p[o[0]] * q[o[1]] - q[o[0]] * p[o[1]]
        return abs(a) / 2

    faces = []
    for s in (s for s in v.brushes if lint._seals(s, res)):
        for sd, poly in geom.face_polys(s):
            if len(poly) < 3:
                continue
            n, p = geom.outward(sd)
            for k in range(3):
                if abs(abs(n[k]) - 1) < 1e-6:
                    o = [j for j in range(3) if j != k]
                    # extensão da FACE (não da caixa do brush) e só face retangular: numa rampa a caixa sobe acima
                    # da face, e a tampa ia para o ar e apagava a parede encostada (vão de escada do rp_surdonoso)
                    r = (min(q[o[0]] for q in poly), max(q[o[0]] for q in poly),
                         min(q[o[1]] for q in poly), max(q[o[1]] for q in poly))
                    if abs(area2(poly, o) - (r[1] - r[0]) * (r[3] - r[2])) > 0.01 * max(1.0, (r[1] - r[0]) * (r[3] - r[2])):
                        continue
                    faces.append((k, n[k] > 0, p[k], r, s))
    neg = defaultdict(list)
    for k, pos, c, r, s in faces:
        if not pos:
            neg[(k, int(c // 4))].append((c, r, s))
    made, seen = [], set()
    for k, pos, c, r, s in faces:
        if not pos:
            continue
        for b in (int(c // 4), int(c // 4) + 1):
            for c2, r2, s2 in neg.get((k, b), []):
                if s2 is s or not (1e-3 < c2 - c <= gap):
                    continue
                a0, a1, b0, b1 = max(r[0], r2[0]), min(r[1], r2[1]), max(r[2], r2[2]), min(r[3], r2[3])
                if a1 - a0 <= 1e-3 or b1 - b0 <= 1e-3:
                    continue
                o = [j for j in range(3) if j != k]
                lo, hi = [0.0] * 3, [0.0] * 3
                lo[k], hi[k] = c, c2
                lo[o[0]], hi[o[0]], lo[o[1]], hi[o[1]] = a0, a1, b0, b1
                key = tuple(round(x, 3) for x in lo + hi)
                if key in seen:
                    continue
                seen.add(key)
                made.append(add_plug(v, Vec(*lo), Vec(*hi), material).get_bbox())
    return made

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

from dataclasses import dataclass, field

from srctools import VMF, Vec

SEAL_VISGROUP = "ht_seal"     # tampas ficam nesse visgroup: o ht optimize não junta, o cache sabe quais são


def add_plug(v: VMF, lo: Vec, hi: Vec, material: str):
    from hammertools.core import vmf as vmfio
    solid = v.make_prism(lo, hi, mat=material).solid
    solid.visgroup_ids.add(vmfio._visgroup(v, SEAL_VISGROUP, (0, 160, 255)).id)
    v.add_brush(solid)
    return solid


def plugs_in(v: VMF) -> list:
    """Tampas (do visgroup ht_seal) já no mapa: [(lo, hi, material)]."""
    ids = {vg.id for vg in v.vis_tree if vg.name == SEAL_VISGROUP}
    return [(*s.get_bbox(), s.sides[0].mat) for s in v.brushes if s.visgroup_ids & ids]


def save_cache(path, plugs) -> None:
    import json
    path.write_text(json.dumps([[list(map(float, lo)), list(map(float, hi)), m] for lo, hi, m in plugs]))


def apply_cache(v: VMF, path) -> tuple[int, int]:
    """Repõe as tampas de compilações anteriores (<mapa>.seal.json). Tampa que hoje contém a origem de alguma
    entidade é velha (o mapa mudou ali) e fica de fora. Devolve (aplicadas, descartadas)."""
    import json
    from hammertools import lint
    origins = [o for o in (lint._origin(e) for e in v.entities) if o is not None]
    used = dropped = 0
    for lo, hi, mat in json.loads(path.read_text()):
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


def cut_masks(blocked, src_mask, sink_mask, protect=None):
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
    for ax in range(3):
        a = [slice(None)] * 3
        b = [slice(None)] * 3
        a[ax], b[ax] = slice(0, -1), slice(1, None)
        m = air[tuple(a)] & air[tuple(b)]
        u, w = idx[tuple(a)][m], idx[tuple(b)][m]
        rows += [u * 2 + 1, w * 2 + 1]
        cols += [w * 2, u * 2]
        caps += [np.full(len(u), big, np.int32)] * 2
        del m, u, w
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
        add_plug(v, Vec(*lo), Vec(*hi), material)
        r.boxes.append((Vec(*lo), Vec(*hi)))
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


def seal_at_pointfile(v: VMF, res, points, material: str = "tools/toolsnodraw") -> list:
    """Tampa a fresta por onde o caminho do vbsp (pointfile) sai do mapa, com grade fina só em volta dela. Fonte e
    sumidouro na borda do recorte vêm da grade grossa (lado de dentro x vazio). Devolve as caixas criadas.
    Material nodraw: sela e o vbsp não gera face nenhuma (fresta de poucas unidades não aparece; skybox ali só
    somaria vértices num mapa que costuma estar no teto)."""
    import numpy as np
    from scipy import ndimage
    from hammertools import lint
    g = _grid(v, res, None)
    if g is None or len(points) < 2:
        return []
    solid, virtual, origin, vs = g
    seeds = [c for c in _seeds(v, origin, vs, solid.shape) if not solid[c] and not virtual[c]]
    blocked = solid | virtual
    lab, _ = ndimage.label(~blocked)
    inside = {int(lab[c]) for c in seeds if lab[c]} - _boundary_labels(lab)
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
        """Classe grossa de cada voxel fino do recorte: 0 sólido, 1 dentro, 2 vazio (fora da grade = vazio)."""
        idx, ok = [], []
        for k in range(3):
            i = np.floor((lo[k] + (np.arange(fshape[k]) + 0.5) * fine - origin[k]) / vs).astype(int)
            ok.append((i >= 0) & (i < shape[k]))
            idx.append(np.clip(i, 0, shape[k] - 1))
        ix = np.ix_(*idx)
        cls = np.where(blocked[ix], 0, np.where(inside_arr[lab[ix]], 1, 2)).astype(np.int8)
        cls[~(ok[0][:, None, None] & ok[1][None, :, None] & ok[2][None, None, :])] = 2
        return cls
    coarse.volume = volume

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
        made = _local_cut(v, res, seg, coarse, fine, margin, material, ent, path)
        if made:
            return made
    return []


GRID_OFFSET = 0.25
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
    made = []
    for i0, i1 in boxes(cut):
        p, q = _grow_into_solid(i0, i1, fsolid, interior)
        blo = np.clip(lo + p * fine, -WORLD, WORLD)
        bhi = np.clip(lo + q * fine, -WORLD, WORLD)
        if np.any(bhi - blo <= 0):
            continue
        add_plug(v, Vec(*blo), Vec(*bhi), material)
        made.append((Vec(*blo), Vec(*bhi)))
    return made


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
    cut = cut_masks(fblocked, src, snk)
    if not cut.any():
        return None
    flab, _ = ndimage.label(~(fblocked | cut))
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
            add_plug(v, Vec(*lo), Vec(*hi), material)
            made.append((Vec(*lo), Vec(*hi)))
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
    faces = []
    for s in (s for s in v.brushes if lint._seals(s, res)):
        lo, hi = s.get_bbox()
        for sd in s.sides:
            n, p = geom.outward(sd)
            for k in range(3):
                if abs(abs(n[k]) - 1) < 1e-6:
                    o = [j for j in range(3) if j != k]
                    faces.append((k, n[k] > 0, p[k], (lo[o[0]], hi[o[0]], lo[o[1]], hi[o[1]]), s))
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
                add_plug(v, Vec(*lo), Vec(*hi), material)
                made.append((Vec(*lo), Vec(*hi)))
    return made

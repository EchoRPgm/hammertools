"""`ht optimize`: junta blocos retangulares fatiados pra reduzir t-junctions (e brushes/faces).

Dois brushes viram um quando:
- ambos são caixas alinhadas aos eixos (6 faces, sem displacement), no mundo ou no MESMO func_detail;
- encostam por uma face inteira (mesma extensão nos outros dois eixos);
- as 4 faces laterais têm o mesmo material e o mesmo mapeamento (uaxis/vaxis com shift e escala,
  lightmap e smoothing), então a textura continua idêntica depois da junção;
- mesmos visgroups, grupo do editor e nenhum dos dois oculto;
- o conteúdo do brush não muda: no vbsp o conteúdo é a soma das faces, então uma ponta de água/vidro/
  ferramenta levada pra um brush sólido faria ele parar de selar (leak). `classify` diz a classe de cada
  material; sem ela, cada material que não é sólido conhecido conta como classe própria (conservador).
As faces que encostam somem (nunca eram visíveis); as pontas ficam com a textura de cada lado.
Grava sempre num VMF novo (padrão <mapa>_opt.vmf); o fonte não é tocado.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from srctools import VMF
from srctools.vmf import Side, Solid

from hammertools.core import geom

EPS = 0.01


@dataclass
class Box:
    solid: Solid
    container: list            # lista de solids de onde ele sai (v.brushes ou ent.solids)
    group: tuple               # (dono, visgroups, grupo do editor): só junta dentro do mesmo
    faces: dict                # (eixo, +?) -> Side
    lo: list[float]
    hi: list[float]
    alive: bool = True


@dataclass
class Result:
    merged: Counter = field(default_factory=Counter)    # dono -> junções
    boxes: int = 0
    solids: int = 0


def _box(solid: Solid) -> tuple[dict, list, list] | None:
    if len(solid.sides) != 6 or solid.hidden or solid.is_cordon:
        return None
    faces, lo, hi = {}, [0.0] * 3, [0.0] * 3
    for side in solid.sides:
        if side.is_disp:
            return None
        n, p = geom.outward(side)
        comps = (n.x, n.y, n.z)
        ax = next((a for a in range(3) if abs(comps[a]) > 1 - 1e-6), None)
        if ax is None:
            return None
        pos = comps[ax] > 0
        if (ax, pos) in faces:
            return None
        faces[ax, pos] = side
        (hi if pos else lo)[ax] = (p.x, p.y, p.z)[ax]
    if len(faces) != 6 or any(hi[a] - lo[a] <= EPS for a in range(3)):
        return None
    return faces, lo, hi


def _uv(axis) -> tuple:
    return (round(axis.x, 4), round(axis.y, 4), round(axis.z, 4), round(axis.offset, 2), round(axis.scale, 4))


def _look(side: Side) -> tuple:
    return (side.mat.lower(), _uv(side.uaxis), _uv(side.vaxis), side.lightmap, side.smooth)


def _k(x: float) -> float:
    return round(x, 2)


def default_classify(mat: str) -> str:
    """Sem informação do jogo: nodraw é sólido; qualquer outro material é classe própria."""
    return "solid" if mat == "tools/toolsnodraw" else mat


def _contents(sides, classify) -> frozenset:
    return frozenset(classify(s.mat.lower()) for s in sides)


def _compatible(a: Box, b: Box, ax: int, classify) -> bool:
    if not all(_look(a.faces[o, s]) == _look(b.faces[o, s]) for o in range(3) if o != ax for s in (False, True)):
        return False
    merged = [f for k, f in a.faces.items() if k != (ax, True)] + [b.faces[ax, True]]
    ca = _contents(a.faces.values(), classify)
    return ca == _contents(b.faces.values(), classify) == _contents(merged, classify)


def _collect(v: VMF) -> list[Box]:
    boxes = []

    def add(solid, container, owner):
        got = _box(solid)
        if got:
            faces, lo, hi = got
            group = (owner, tuple(sorted(solid.visgroup_ids)), solid.group_id)
            boxes.append(Box(solid, container, group, faces, lo, hi))

    for s in v.brushes:
        add(s, v.brushes, "mundo")
    for e in v.entities:
        if e["classname"] == "func_detail" and not e.hidden:
            for s in e.solids:
                add(s, e.solids, f"func_detail {e.id}")
    return boxes


def optimize(v: VMF, classify: Callable[[str], str] = default_classify) -> Result:
    """Junta caixas vizinhas compatíveis no próprio VMF (em memória). Repete até não sobrar junção."""
    boxes = all_boxes = _collect(v)
    res = Result(boxes=len(boxes), solids=len(v.brushes) + sum(len(e.solids) for e in v.entities))
    changed = True
    while changed:
        changed = False
        for ax in range(3):
            others = [o for o in range(3) if o != ax]

            def key(b: Box, at: float):
                return (b.group, *(_k(b.lo[o]) for o in others), *(_k(b.hi[o]) for o in others), _k(at))

            starts: dict[tuple, Box] = {}
            for b in boxes:
                if b.alive:
                    starts.setdefault(key(b, b.lo[ax]), b)
            for b in sorted((b for b in boxes if b.alive), key=lambda b: b.lo[ax]):
                if not b.alive:
                    continue
                while True:
                    nb = starts.get(key(b, b.hi[ax]))
                    if nb is None or nb is b or not nb.alive or not _compatible(b, nb, ax, classify):
                        break
                    # b cresce até o fim de nb: a face da ponta passa a ser a de nb
                    i = b.solid.sides.index(b.faces[ax, True])
                    b.solid.sides[i] = nb.faces[ax, True]
                    b.faces[ax, True] = nb.faces[ax, True]
                    b.hi[ax] = nb.hi[ax]
                    nb.alive = False
                    del starts[key(nb, nb.lo[ax])]
                    res.merged[b.group[0].split(" ")[0]] += 1
                    changed = True
            boxes = [b for b in boxes if b.alive]
    dead = {id(b.solid) for b in all_boxes if not b.alive}
    for container in {id(b.container): b.container for b in all_boxes}.values():
        container[:] = [s for s in container if id(s) not in dead]
    return res


# --------------------------------------------------------------------------- t-junctions: detail -> func_brush
# O vbsp não corta faces de func_detail pela árvore BSP: vértice de vizinho no meio da aresta vira t-junction
# triangulada (índices primitivos, teto de 65536). Mundo e entidades de brush (func_brush) são cortados pela BSP
# do próprio modelo, então a t-junction some (custa vértices, teto de 65536 também). Converter os func_detail
# que mais causam t-junctions em func_brush (agrupados por bloco, pra não estourar o teto de modelos) troca um
# limite pelo outro na medida certa. Validado no rp_surdonoso: 400 func_detail -> 89 func_brush compila com o
# FixTjuncs ligado; 200 não basta; todos (263 func_brush) estoura "Too many unique verts".
def rank_detail_tjunctions(v: VMF) -> list[int]:
    """Ids das entidades func_detail, da que mais custa em t-junctions pra que menos (só as com custo):
    índices das faces dela + 3 índices por vértice dela no meio de aresta de outra face."""
    from collections import defaultdict
    from hammertools import lint
    rep = lint.run(v, lint.Resources(), {"tjunctions"})
    ent_of = {s.id: e.id for e in v.by_class["func_detail"] for s in e.solids}
    cost: dict[int, float] = defaultdict(float)
    for f in rep.data.get("tjunctions", []):
        if f["solid"] in ent_of:
            cost[ent_of[f["solid"]]] += f["idx"]
        for sid, n in f.get("sources", {}).items():
            if sid in ent_of:
                cost[ent_of[sid]] += 3 * n
    return sorted(cost, key=lambda k: -cost[k])


def detail_to_brush(v: VMF, ent_ids, area: float = 1024.0) -> int:
    """Troca os func_detail escolhidos por func_brush sólidos (um por bloco de `area`u, pelo centro de cada
    brush) que projetam sombra no vrad. Devolve quantos func_brush criou."""
    from collections import defaultdict
    from srctools.vmf import Entity
    chosen = set(ent_ids)
    groups: dict[tuple, list] = defaultdict(list)
    for e in list(v.by_class["func_detail"]):
        if e.id not in chosen:
            continue
        for s in e.solids:
            lo, hi = s.get_bbox()
            c = (lo + hi) / 2
            groups[(int(c.x // area), int(c.y // area), int(c.z // area))].append(s)
        v.remove_ent(e)
    for sols in groups.values():
        v.add_ent(Entity(v, {"classname": "func_brush", "Solidity": "2", "vrad_brush_cast_shadows": "1",
                             "disableshadows": "0", "rendermode": "0"}, solids=sols))
    return len(groups)

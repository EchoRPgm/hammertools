"""ht_rope: cabo (move_rope + keyframe_rope encadeados) ou trilho de brush por uma sequência de pontos.

`ht_rope` no início, `ht_rope_node` (order) nos pontos intermediários, `ht_rope_end` no fim.
kind=rope: entidades de corda com folga (`slack`). kind=rail: dois trilhos (brush) + dormentes.
"""
from __future__ import annotations

from srctools import VMF, Vec

from hammertools.core import brush, repeat
from hammertools.core.vmf import Group, origin
from hammertools.generators import Result, register

DEFAULTS = {
    "kind": "rope", "slack": 25.0, "width": 2.0, "rope_material": "cable/cable.vmt", "subdiv": 4,
    "gauge": 64.0, "rail_size": 4.0, "tie_spacing": 48.0, "tie_size": 8.0, "tie_width": 96.0,
    "material": "dev/dev_measuregeneric01b",
}


def _f(ent, k):
    return float(ent.get(k, DEFAULTS[k]))


def _path(group: Group):
    start, end = group.by_role("start"), group.by_role("end")
    if start is None or end is None:
        return None
    nodes = sorted((e for e in group.ents if e["classname"].endswith("_node")), key=lambda e: float(e.get("order", 0)))
    return [origin(start)] + [origin(n) for n in nodes] + [origin(end)]


@register("ht_rope")
def generate(vmf: VMF, group: Group) -> Result:
    res = Result()
    path = _path(group)
    if path is None:
        res.warnings.append(f"{group.name}: precisa de ht_rope (início) e ht_rope_end (fim) com o mesmo targetname")
        return res
    start = group.by_role("start")
    if start.get("kind", DEFAULTS["kind"]) == "rail":
        return _rail(vmf, group, start, path, res)
    slack, width = _f(start, "slack"), _f(start, "width")
    mat, subdiv = start.get("rope_material") or DEFAULTS["rope_material"], int(_f(start, "subdiv"))
    names = [f"{group.name}_{i}" for i in range(len(path))]
    for i, p in enumerate(path):
        cls = "move_rope" if i == 0 else "keyframe_rope"
        kv = dict(origin=p, targetname=names[i], Slack=str(slack), Width=str(width), RopeMaterial=mat,
                  Subdiv=str(subdiv), TextureScale="1", Type="0", MoveSpeed="64", PositionInterpolator="2")
        if i + 1 < len(path):
            kv["NextKey"] = names[i + 1]
        res.ents.append(vmf.create_ent(cls, **kv))
    return res


def _rail(vmf, group, start, path, res):
    gauge, rs = _f(start, "gauge"), _f(start, "rail_size")
    ts, tsz, tw = _f(start, "tie_spacing"), _f(start, "tie_size"), _f(start, "tie_width")
    mat = start.get("material") or DEFAULTS["material"]
    solids = []
    for p, q in zip(path, path[1:]):
        d = q - p
        L = d.mag()
        if L < 1e-6:
            continue
        pitch, yaw = brush.direction_angles(d)
        seg = []
        for sy in (-gauge / 2, gauge / 2):
            seg.append(brush.box(vmf, Vec(0, sy - rs / 2, tsz), Vec(L, sy + rs / 2, tsz + rs), mat))
        for x in repeat.positions(L, ts, include_end=False):
            if x + tsz > L + 1e-6:
                continue  # dormente não passa do fim do trecho
            seg.append(brush.box(vmf, Vec(x, -tw / 2, 0), Vec(x + tsz, tw / 2, tsz), mat))
        brush.place3d(seg, p, pitch, yaw)
        for s in seg:
            for side in s.sides:
                side.planes = [brush.snap(pt) for pt in side.planes]
        solids.extend(seg)
    res.solids = solids
    return res

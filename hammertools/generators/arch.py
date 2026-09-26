"""ht_arch: arco/abóbada entre dois marcadores nos pés (mesmo nível), no plano vertical A→B.

`ht_arch` num pé (chão, centro da espessura), `ht_arch_end` no outro pé. Altura, segmentos,
espessura da faixa (radial) e profundidade (extrusão perpendicular) no marcador de início.
"""
from __future__ import annotations

from srctools import VMF, Vec

from hammertools.core import brush, curves
from hammertools.core.vmf import Group, horizontal_dist, is_on_grid, origin, yaw_between
from hammertools.generators import Result, register

DEFAULTS = {
    "height": "auto",       # auto = metade do vão (semicírculo)
    "segments": 8,
    "thickness": 16.0,
    "depth": 16.0,
    "grid": 1.0,
    "material": "dev/dev_measuregeneric01b",
}


@register("ht_arch")
def generate(vmf: VMF, group: Group) -> Result:
    res = Result()
    start, end = group.by_role("start"), group.by_role("end")
    if start is None or end is None:
        res.warnings.append(f"{group.name}: precisa de um ht_arch e um ht_arch_end com o mesmo targetname")
        return res
    a, b = origin(start), origin(end)
    span = horizontal_dist(a, b)
    if span <= 0:
        res.warnings.append(f"{group.name}: pés no mesmo ponto")
        return res
    if abs(b.z - a.z) > 0.5:
        res.warnings.append(f"{group.name}: pés em alturas diferentes; usando a do início")
    h_raw = start.get("height", DEFAULTS["height"])
    height = span / 2 if h_raw in ("auto", "", None) else float(h_raw)
    segs = max(2, int(float(start.get("segments", DEFAULTS["segments"]))))
    thick = float(start.get("thickness", DEFAULTS["thickness"]))
    depth = float(start.get("depth", DEFAULTS["depth"]))
    grid = float(start.get("grid", DEFAULTS["grid"]))
    mat = start.get("material") or DEFAULTS["material"]
    if thick >= min(height, span / 2):
        res.warnings.append(f"{group.name}: espessura {thick} maior que o raio do arco; reduzida")
        thick = min(height, span / 2) / 2
    yaw = yaw_between(a, b)
    if not is_on_grid(yaw, 90):
        res.warnings.append(f"{group.name}: arco em {yaw:.1f}° gera vértices fora do grid")

    outer = curves.arch_points(span, height, segs)
    inner = curves.arch_points(span - 2 * thick, height - thick, segs)
    inner = [(x + thick, z) for x, z in inner]
    half = depth / 2
    solids = []
    for i in range(segs):
        (ox0, oz0), (ox1, oz1) = outer[i], outer[i + 1]
        (ix0, iz0), (ix1, iz1) = inner[i], inner[i + 1]
        sn = lambda x, y, z: tuple(brush.snap((x, y, z), grid))
        # quad no plano XZ (ordem: outer0, outer1, inner1, inner0), extrudado em Y
        o0, o1, i1, i0 = (ox0, oz0), (ox1, oz1), (ix1, iz1), (ix0, iz0)
        faces = [
            (sn(o0[0], half, o0[1]), sn(o1[0], half, o1[1]), sn(i1[0], half, i1[1]), mat),        # frente +Y
            (sn(i1[0], -half, i1[1]), sn(o1[0], -half, o1[1]), sn(o0[0], -half, o0[1]), mat),     # trás -Y
            (sn(o1[0], half, o1[1]), sn(o0[0], half, o0[1]), sn(o0[0], -half, o0[1]), mat),       # extradorso
            (sn(i0[0], half, i0[1]), sn(i1[0], half, i1[1]), sn(i1[0], -half, i1[1]), mat),       # intradorso
            (sn(o0[0], half, o0[1]), sn(i0[0], half, i0[1]), sn(i0[0], -half, i0[1]), mat),       # junta lado 0
            (sn(i1[0], half, i1[1]), sn(o1[0], half, o1[1]), sn(o1[0], -half, o1[1]), mat),       # junta lado 1
        ]
        # winding do srctools: cross(p2-p1, p3-p1) PRA DENTRO; a lista acima está pra fora -> inverte
        solids.append(brush.from_points(vmf, [(a, c, b, m) for a, b, c, m in faces]))
    brush.place(solids, a, yaw)
    res.solids = solids
    return res

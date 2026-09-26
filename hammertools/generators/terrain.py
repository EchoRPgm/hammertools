"""ht_terrain: terreno por displacement num retângulo (dois marcadores em cantos opostos, no nível do topo).

Gera uma grade de tiles (cada um uma caixa com a face de cima em displacement), alturas por ruído
ou por PNG (heightmap). O marcador define o nível base do topo; `amplitude` é o relevo acima dele.
Tiles vizinhos compartilham os vértices da borda (mesma função de altura), então não abre fresta.
"""
from __future__ import annotations

import math

from srctools import VMF, Vec

from hammertools.core import disp
from hammertools.core.vmf import Group, origin
from hammertools.generators import Result, register

DEFAULTS = {
    "tile": 512.0, "power": 3, "thickness": 32.0, "amplitude": 64.0, "source": "noise", "heightmap": "",
    "seed": 1, "scale": 2.0, "octaves": 3, "material": "nature/blendgrassdirt01", "side_material": "tools/toolsnodraw",
}


def _f(ent, k):
    return float(ent.get(k, DEFAULTS[k]))


@register("ht_terrain")
def generate(vmf: VMF, group: Group) -> Result:
    res = Result()
    start, end = group.by_role("start"), group.by_role("end")
    if start is None or end is None:
        res.warnings.append(f"{group.name}: precisa de ht_terrain e ht_terrain_end (cantos opostos)")
        return res
    a, b = origin(start), origin(end)
    lo, hi = Vec(min(a.x, b.x), min(a.y, b.y), a.z), Vec(max(a.x, b.x), max(a.y, b.y), a.z)
    W, H = hi.x - lo.x, hi.y - lo.y
    if W <= 0 or H <= 0:
        res.warnings.append(f"{group.name}: retângulo degenerado")
        return res
    tile = _f(start, "tile")
    power = max(1, min(4, int(_f(start, "power"))))
    thick, amp = _f(start, "thickness"), _f(start, "amplitude")
    mat, smat = start.get("material") or DEFAULTS["material"], start.get("side_material") or DEFAULTS["side_material"]
    source = start.get("source", DEFAULTS["source"])
    if source == "heightmap" and start.get("heightmap"):
        try:
            field = disp.heightmap_png(start["heightmap"])
        except Exception as e:  # noqa: BLE001
            res.warnings.append(f"{group.name}: heightmap '{start['heightmap']}' ilegível ({e}); usando ruído")
            field = disp.value_noise(int(_f(start, "seed")), _f(start, "scale"), int(_f(start, "octaves")))
    else:
        field = disp.value_noise(int(_f(start, "seed")), _f(start, "scale"), int(_f(start, "octaves")))

    nx, ny = max(1, math.ceil(W / tile)), max(1, math.ceil(H / tile))
    tw, th = W / nx, H / ny
    solids = []
    for j in range(ny):
        for i in range(nx):
            tlo = Vec(lo.x + i * tw, lo.y + j * th, lo.z)
            thi = Vec(lo.x + (i + 1) * tw, lo.y + (j + 1) * th, lo.z)
            def height_at(u, v, tlo=tlo):  # u,v do tile -> u,v globais -> altura
                gu = (tlo.x + u * tw - lo.x) / W
                gv = (tlo.y + v * th - lo.y) / H
                return round(field(gu, gv) * amp, 2)
            solids.append(disp.terrain_tile(vmf, tlo, thi, thick, power, mat, height_at, smat))
    res.solids = solids
    res.detail = False  # terreno costuma ser chão do mapa (sela); displacement não sela sozinho, a caixa embaixo sim
    return res

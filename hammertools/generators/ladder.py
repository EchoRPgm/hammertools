"""ht_ladder: escada de mão pro Garry's Mod (brush func_ladder + brush visual).

`ht_ladder` embaixo: no chão, encostado na FACE da parede, centro da largura; o `angles` (yaw)
do marcador aponta PRA PAREDE. `ht_ladder_end` em cima: nível do piso superior, mesma XY.

GMod usa o sistema de escada do CS/HL2DM: um volume `func_ladder` (textura toolsinvisibleladder)
na frente da parede. O `func_useableladder` do HL2 NÃO funciona no GMod. O volume passa um pouco
do topo (`overshoot`) pra dar pra sair no piso de cima.
"""
from __future__ import annotations

from srctools import VMF, Vec

from hammertools.core import brush, ents
from hammertools.core.vmf import Group, horizontal_dist, origin
from hammertools.generators import Result, register

DEFAULTS = {
    "width": 32.0,
    "ladder_depth": 16.0,     # espessura do volume func_ladder (da face visual pra fora)
    "overshoot": 24.0,        # quanto o volume passa do piso de cima (pra conseguir sair)
    "visual": "brush",
    "visual_depth": 4.0,
    "material": "dev/dev_measuregeneric01b",
}

LADDER_MAT = "tools/toolsinvisibleladder"


def _num(ent, key):
    return float(ent.get(key, DEFAULTS[key]))


@register("ht_ladder")
def generate(vmf: VMF, group: Group) -> Result:
    res = Result()
    start, end = group.by_role("start"), group.by_role("end")
    if start is None or end is None:
        res.warnings.append(f"{group.name}: precisa de um ht_ladder e um ht_ladder_end com o mesmo targetname")
        return res
    a, b = origin(start), origin(end)
    if b.z <= a.z:
        res.warnings.append(f"{group.name}: o topo precisa estar acima da base")
        return res
    if horizontal_dist(a, b) > 0.5:
        res.warnings.append(f"{group.name}: topo deslocado em XY; a escada é gerada vertical a partir da base")
    yaw = float(start.get("angles", "0 0 0").split()[1]) if start.get("angles") else 0.0
    height = b.z - a.z
    width, ldepth, over = _num(start, "width"), _num(start, "ladder_depth"), _num(start, "overshoot")
    vdepth = _num(start, "visual_depth") if start.get("visual", DEFAULTS["visual"]) == "brush" else 0.0

    # volume climbável: na frente da face visual (parede em +X local, jogador vem de -X)
    lad = brush.box(vmf, Vec(-vdepth - ldepth, -width / 2, 0), Vec(-vdepth, width / 2, height + over), LADDER_MAT)
    brush.place([lad], a, yaw)
    res.ents.append(ents.brush_ent(vmf, "func_ladder", [lad], targetname=group.name, origin=brush.to_world(Vec(-vdepth - ldepth / 2, 0, height / 2), a, yaw)))

    if vdepth > 0:
        mat = start.get("material") or DEFAULTS["material"]
        s = brush.box(vmf, Vec(-vdepth, -width / 2, 0), Vec(0, width / 2, height), mat, nodraw=("east",))
        brush.place([s], a, yaw)
        res.solids = [s]
    return res

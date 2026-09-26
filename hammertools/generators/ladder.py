"""ht_ladder: escada de mão (Garry's Mod = sistema HL2: func_useableladder + info_ladder_dismount).

`ht_ladder` embaixo: no chão, encostado na FACE da parede/plataforma que se escala, centro da largura;
o `angles` (yaw) do marcador aponta PRA PAREDE. `ht_ladder_end` em cima: nível do piso superior,
mesma XY. O piso de cima fica ALÉM da face (do lado pra onde o yaw aponta).

Números do gm_construct: linha de subida 24u à frente da face, point0 8u abaixo do chão, point1 8u
abaixo do piso de cima, saída de cima 20u além da face (1u acima do piso), saídas de baixo 40u da linha.
`func_ladder` (CS) NÃO funciona no GMod (o vbsp vira info_ladder e o jogador não sobe).
"""
from __future__ import annotations

from srctools import VMF, Vec

from hammertools.core import brush
from hammertools.core.vmf import Group, horizontal_dist, origin
from hammertools.generators import Result, register

DEFAULTS = {
    "width": 32.0,
    "climb_offset": 24.0,     # distância da linha de subida até a face
    "visual": "brush",
    "visual_depth": 4.0,
    "material": "dev/dev_measuregeneric01b",
}


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
    width, climb = _num(start, "width"), _num(start, "climb_offset")
    name = group.name
    W = lambda local: brush.to_world(Vec(*local), a, yaw)  # face em +X local; jogador vem de -X

    p0 = W((-climb, 0, -8))
    p1 = W((-climb, 0, height - 8))
    res.ents.append(vmf.create_ent("func_useableladder", origin=W((0, 0, 0)), targetname=name, point0=p0, point1=p1))
    # saídas: duas embaixo (frente e lado), uma em cima já sobre o piso superior
    for local in ((-climb - 40, 0, 0), (-climb, -40, 0), (20, 0, height + 1)):
        res.ents.append(vmf.create_ent("info_ladder_dismount", origin=W(local), LadderName=name))

    if start.get("visual", DEFAULTS["visual"]) == "brush":
        depth = _num(start, "visual_depth")
        mat = start.get("material") or DEFAULTS["material"]
        s = brush.box(vmf, Vec(-depth, -width / 2, 0), Vec(0, width / 2, height), mat, nodraw=("east",))
        brush.place([s], a, yaw)
        res.solids = [s]
    return res

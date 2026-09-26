"""ht_railing: corrimão entre dois marcadores (segue a inclinação, serve pra escada ou piso plano).

`ht_railing` embaixo, `ht_railing_end` em cima, mesmo targetname, colocados NA LINHA do corrimão
no nível do chão (na escada: no nível do piso em cada ponta, do lado da escada onde vai o corrimão).
"""
from __future__ import annotations

from srctools import VMF, Vec

from hammertools.core import brush, repeat
from hammertools.core.vmf import Group, horizontal_dist, is_on_grid, origin, yaw_between
from hammertools.generators import Result, register

DEFAULTS = {
    "height": 40.0,
    "post_spacing": 48.0,
    "post_size": 4.0,
    "rail_size": 4.0,
    "mid_rail": "1",
    "material": "dev/dev_measuregeneric01b",
}


def _num(ent, key):
    return float(ent.get(key, DEFAULTS[key]))


@register("ht_railing")
def generate(vmf: VMF, group: Group) -> Result:
    res = Result()
    start, end = group.by_role("start"), group.by_role("end")
    if start is None or end is None:
        res.warnings.append(f"{group.name}: precisa de um ht_railing e um ht_railing_end com o mesmo targetname")
        return res
    a, b = origin(start), origin(end)
    run, rise = horizontal_dist(a, b), b.z - a.z
    if run <= 0:
        res.warnings.append(f"{group.name}: corrimão precisa de distância horizontal > 0")
        return res
    yaw = yaw_between(a, b)
    if not is_on_grid(yaw, 90):
        res.warnings.append(f"{group.name}: corrimão em {yaw:.1f}° gera vértices fora do grid")
    height, spacing = _num(start, "height"), _num(start, "post_spacing")
    post, rail = _num(start, "post_size"), _num(start, "rail_size")
    mat = start.get("material") or DEFAULTS["material"]
    slope = rise / run

    solids = []
    for x in repeat.positions(run, spacing, include_end=True):
        floor = slope * x
        solids.append(brush.box(vmf, Vec(x - post / 2, -post / 2, floor), Vec(x + post / 2, post / 2, floor + height - rail), mat))
    # barra de cima e (opcional) do meio, inclinadas
    for z_off in ([height - rail, (height - rail) / 2] if start.get("mid_rail", DEFAULTS["mid_rail"]) == "1" else [height - rail]):
        solids.append(brush.sloped_bar(vmf, -post / 2, run + post / 2, -rail / 2, rail / 2, z_off, rise + z_off, rail, mat))
    brush.place(solids, a, yaw)
    res.solids = solids
    return res

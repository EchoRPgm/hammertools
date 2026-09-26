"""ht_lights: fila de luzes entre dois marcadores (na altura dos marcadores).

Cada posição recebe: light ou light_spot (mirando pra baixo por padrão), e opcionalmente um
prop_static de luminária. Os props são centrados, as luzes idem.
"""
from __future__ import annotations

from srctools import VMF, Vec

from hammertools.core import brush, repeat
from hammertools.core.vmf import Group, horizontal_dist, origin, yaw_between
from hammertools.generators import Result, register

DEFAULTS = {
    "spacing": 128.0, "kind": "light_spot", "brightness": "255 244 220 200", "pitch": -90.0,
    "cone": 45.0, "inner_cone": 30.0, "with_prop": "0", "model": "models/props_c17/light_cagelight01_on.mdl",
    "prop_z": 0.0, "prop_yaw": 0.0, "light_z": -8.0, "at_ends": "1",
}


def _f(ent, k):
    return float(ent.get(k, DEFAULTS[k]))


@register("ht_lights")
def generate(vmf: VMF, group: Group) -> Result:
    res = Result()
    start, end = group.by_role("start"), group.by_role("end")
    if start is None or end is None:
        res.warnings.append(f"{group.name}: precisa de ht_lights e ht_lights_end com o mesmo targetname")
        return res
    a, b = origin(start), origin(end)
    length = horizontal_dist(a, b)
    if length <= 0:
        res.warnings.append(f"{group.name}: início e fim no mesmo ponto")
        return res
    yaw = yaw_between(a, b)
    spacing = _f(start, "spacing")
    kind = start.get("kind", DEFAULTS["kind"])
    at_ends = start.get("at_ends", DEFAULTS["at_ends"]) == "1"
    xs = repeat.positions(length, spacing, include_end=True) if at_ends else \
        [x + spacing / 2 for x in repeat.positions(length - spacing, spacing, include_end=False)] if length >= spacing else []
    dz = (b.z - a.z) / length
    for x in xs:
        base = Vec(x, 0, dz * x)
        pos = brush.to_world(base + Vec(0, 0, _f(start, "light_z")), a, yaw)
        if kind == "light_spot":
            res.ents.append(vmf.create_ent(
                "light_spot", origin=pos, targetname=f"{group.name}_l", _light=start.get("brightness", DEFAULTS["brightness"]),
                pitch=str(_f(start, "pitch")), angles=f"0 {yaw:.3f} 0", _cone=str(_f(start, "cone")),
                _inner_cone=str(_f(start, "inner_cone")), _exponent="1", _quadratic_attn="1",
            ))
        else:
            res.ents.append(vmf.create_ent(
                "light", origin=pos, targetname=f"{group.name}_l", _light=start.get("brightness", DEFAULTS["brightness"]),
                _quadratic_attn="1",
            ))
        if start.get("with_prop", DEFAULTS["with_prop"]) == "1":
            ppos = brush.to_world(base + Vec(0, 0, _f(start, "prop_z")), a, yaw)
            res.ents.append(vmf.create_ent(
                "prop_static", origin=ppos, angles=f"0 {yaw + _f(start, 'prop_yaw'):.3f} 0",
                model=start.get("model") or DEFAULTS["model"], solid="6",
            ))
    if not xs:
        res.warnings.append(f"{group.name}: fila menor que um espaçamento")
    return res

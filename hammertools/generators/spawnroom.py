"""ht_spawnroom: área de spawn por retângulo (dois marcadores em cantos opostos, no chão).

Gera info_player_start em grade (GMod) ou info_player_teamspawn + func_respawnroom (+ func_regenerate)
pra TF2. O yaw do marcador de início é a direção dos spawns.
"""
from __future__ import annotations

from srctools import VMF, Vec

from hammertools.core import brush, ents
from hammertools.core.vmf import Group, origin
from hammertools.generators import Result, register

DEFAULTS = {
    "game": "gmod", "spacing": 64.0, "margin": 32.0, "team": "2", "height": 128.0, "resupply": "0",
}


def _f(ent, k):
    return float(ent.get(k, DEFAULTS[k]))


@register("ht_spawnroom")
def generate(vmf: VMF, group: Group) -> Result:
    res = Result()
    start, end = group.by_role("start"), group.by_role("end")
    if start is None or end is None:
        res.warnings.append(f"{group.name}: precisa de ht_spawnroom e ht_spawnroom_end (cantos opostos)")
        return res
    a, b = origin(start), origin(end)
    lo, hi = Vec(min(a.x, b.x), min(a.y, b.y), a.z), Vec(max(a.x, b.x), max(a.y, b.y), a.z)
    yaw = float(start.get("angles", "0 0 0").split()[1]) if start.get("angles") else 0.0
    game = start.get("game", DEFAULTS["game"])
    sp, mg = _f(start, "spacing"), _f(start, "margin")
    xs = _grid(lo.x + mg, hi.x - mg, sp)
    ys = _grid(lo.y + mg, hi.y - mg, sp)
    if not xs or not ys:
        res.warnings.append(f"{group.name}: área pequena demais pra um spawn com margem {mg}")
        return res
    cls = "info_player_start" if game == "gmod" else "info_player_teamspawn"
    for x in xs:
        for y in ys:
            kv = dict(origin=Vec(x, y, a.z + 1), angles=f"0 {yaw:.3f} 0")
            if game != "gmod":
                kv["TeamNum"] = start.get("team", DEFAULTS["team"])
            res.ents.append(vmf.create_ent(cls, **kv))
    if game != "gmod":
        h = _f(start, "height")
        room = brush.box(vmf, Vec(lo.x, lo.y, a.z), Vec(hi.x, hi.y, a.z + h), "tools/toolstrigger")
        res.ents.append(ents.brush_ent(vmf, "func_respawnroom", [room], targetname=f"{group.name}_room", TeamNum=start.get("team", DEFAULTS["team"])))
        if start.get("resupply", DEFAULTS["resupply"]) == "1":
            rs = brush.box(vmf, Vec(lo.x, lo.y, a.z), Vec(hi.x, hi.y, a.z + h), "tools/toolstrigger")
            res.ents.append(ents.brush_ent(vmf, "func_regenerate", [rs], targetname=f"{group.name}_regen", TeamNum=start.get("team", DEFAULTS["team"])))
    return res


def _grid(lo: float, hi: float, step: float) -> list[float]:
    if hi < lo:
        return []
    n = int((hi - lo) // step) + 1
    total = (n - 1) * step
    first = lo + ((hi - lo) - total) / 2  # centraliza a grade na área
    return [first + i * step for i in range(n)]

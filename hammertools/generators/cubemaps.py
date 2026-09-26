"""ht_cubemaps: grade de env_cubemap num retângulo (cantos opostos) na altura dos marcadores."""
from __future__ import annotations

from srctools import VMF, Vec

from hammertools.core.vmf import Group, origin
from hammertools.generators import Result, register

DEFAULTS = {"spacing": 256.0, "margin": 64.0, "size": "0"}


def _grid(lo: float, hi: float, step: float) -> list[float]:
    if hi < lo:
        return []
    n = int((hi - lo) // step) + 1
    first = lo + ((hi - lo) - (n - 1) * step) / 2
    return [first + i * step for i in range(n)]


@register("ht_cubemaps")
def generate(vmf: VMF, group: Group) -> Result:
    res = Result()
    start, end = group.by_role("start"), group.by_role("end")
    if start is None or end is None:
        res.warnings.append(f"{group.name}: precisa de ht_cubemaps e ht_cubemaps_end (cantos opostos)")
        return res
    a, b = origin(start), origin(end)
    sp, mg = float(start.get("spacing", DEFAULTS["spacing"])), float(start.get("margin", DEFAULTS["margin"]))
    xs = _grid(min(a.x, b.x) + mg, max(a.x, b.x) - mg, sp)
    ys = _grid(min(a.y, b.y) + mg, max(a.y, b.y) - mg, sp)
    if not xs or not ys:
        res.warnings.append(f"{group.name}: área pequena demais pra um cubemap com margem {mg}")
        return res
    for x in xs:
        for y in ys:
            res.ents.append(vmf.create_ent("env_cubemap", origin=Vec(x, y, a.z), cubemapsize=start.get("size", DEFAULTS["size"])))
    return res


def auto_cubemaps(vmf: VMF, drop: float = 64.0, min_dist: float = 128.0) -> int:
    """Modo automático (`ht build --cubemaps`): um env_cubemap abaixo de cada luz, sem repetir vizinhos."""
    placed: list[Vec] = [Vec.from_str(e["origin"]) for e in vmf.entities if e["classname"] == "env_cubemap"]
    n = 0
    for e in list(vmf.entities):
        if e["classname"] not in ("light", "light_spot"):
            continue
        p = Vec.from_str(e["origin"]) - Vec(0, 0, drop)
        if any((p - q).mag() < min_dist for q in placed):
            continue
        vmf.create_ent("env_cubemap", origin=p, cubemapsize="0")
        placed.append(p)
        n += 1
    return n

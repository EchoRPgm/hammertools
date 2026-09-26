"""ht_zone: volume utilitário num retângulo (cantos opostos no chão) com altura.

kind: playerclip | npcclip | block_los | nav_blocker (func_nav_blocker) | trigger_hurt? (não) | invisible (sólido invisível).
Clips/block_los são brushes de ferramenta em func_detail; nav_blocker é brush entity.
"""
from __future__ import annotations

from srctools import VMF, Vec

from hammertools.core import brush, ents
from hammertools.core.vmf import Group, origin
from hammertools.generators import Result, register

DEFAULTS = {"kind": "playerclip", "height": 128.0}
MATS = {
    "playerclip": "tools/toolsplayerclip", "npcclip": "tools/toolsnpcclip", "clip": "tools/toolsclip",
    "block_los": "tools/toolsblock_los", "invisible": "tools/toolsinvisible", "nav_blocker": "tools/toolstrigger",
}


@register("ht_zone")
def generate(vmf: VMF, group: Group) -> Result:
    res = Result()
    start, end = group.by_role("start"), group.by_role("end")
    if start is None or end is None:
        res.warnings.append(f"{group.name}: precisa de ht_zone e ht_zone_end (cantos opostos)")
        return res
    a, b = origin(start), origin(end)
    kind = start.get("kind", DEFAULTS["kind"])
    if kind not in MATS:
        res.warnings.append(f"{group.name}: kind '{kind}' desconhecido; usando playerclip")
        kind = "playerclip"
    h = float(start.get("height", DEFAULTS["height"]))
    lo, hi = Vec(min(a.x, b.x), min(a.y, b.y), a.z), Vec(max(a.x, b.x), max(a.y, b.y), a.z + h)
    if hi.x - lo.x <= 0 or hi.y - lo.y <= 0 or h <= 0:
        res.warnings.append(f"{group.name}: volume degenerado")
        return res
    solid = brush.box(vmf, lo, hi, MATS[kind])
    if kind == "nav_blocker":
        res.ents.append(ents.brush_ent(vmf, "func_nav_blocker", [solid], targetname=group.name, StartDisabled="0"))
    else:
        res.solids = [solid]
    return res

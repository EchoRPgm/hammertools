"""ht_fence: cerca/grade/parede modular entre dois marcadores.

`ht_fence` no início (nível do chão, na linha da cerca), `ht_fence_end` no fim, mesmo targetname.
mode=brush: postes a cada `spacing` + painéis de brush entre eles (o último cortado pra fechar).
mode=prop:  um prop_static a cada `spacing` (mais um no fim, opcional).
"""
from __future__ import annotations

from srctools import VMF, Vec

from hammertools.core import brush, models, repeat
from hammertools.core.vmf import Group, horizontal_dist, is_on_grid, origin, yaw_between
from hammertools.generators import Result, register

DEFAULTS = {
    "mode": "brush",
    "spacing": 64.0,
    "height": 96.0,
    "thickness": 8.0,
    "post_size": 8.0,
    "post_extra": 8.0,
    "material": "dev/dev_measuregeneric01b",
    "material_post": "",
    "model": "models/props_c17/fence01a.mdl",
    "prop_spacing": "auto",   # auto = comprimento do modelo (eixo longo do bbox)
    "model_yaw": "auto",      # auto = alinha o eixo longo do modelo com a linha
    "model_z": "auto",        # auto = apoia o bbox no chão
    "prop_at_end": "0",
}



def _auto_prop(start, model: str, res: Result) -> tuple[float, float, float]:
    """(spacing, yaw_extra, z_off) resolvendo os 'auto' pelo bbox do modelo."""
    sp, yaw, z = start.get("prop_spacing", DEFAULTS["prop_spacing"]), start.get("model_yaw", DEFAULTS["model_yaw"]), start.get("model_z", DEFAULTS["model_z"])
    need = "auto" in (sp, yaw, z)
    bbox = models.model_bbox(models.game_dir(), model) if need else None
    if need and bbox is None:
        res.warnings.append(f"{start.get('targetname', '?')}: não li o bbox de {model} (sem --game/HT_GAME?); usando spacing=64, yaw=0, z=0")
    if bbox:
        mins, maxs = bbox
        ext_x, ext_y = maxs.x - mins.x, maxs.y - mins.y
        long_is_y = ext_y > ext_x
        if sp == "auto":
            sp = round(max(ext_x, ext_y))
        if yaw == "auto":
            yaw = 90.0 if long_is_y else 0.0
        if z == "auto":
            z = -mins.z if mins.z < 0 else 0.0
    return (64.0 if sp == "auto" else float(sp)), (0.0 if yaw == "auto" else float(yaw)), (0.0 if z == "auto" else float(z))


def _num(ent, key):
    return float(ent.get(key, DEFAULTS[key]))


@register("ht_fence")
def generate(vmf: VMF, group: Group) -> Result:
    res = Result()
    start, end = group.by_role("start"), group.by_role("end")
    if start is None or end is None:
        res.warnings.append(f"{group.name}: precisa de um ht_fence e um ht_fence_end com o mesmo targetname")
        return res
    a, b = origin(start), origin(end)
    length = horizontal_dist(a, b)
    if length <= 0:
        res.warnings.append(f"{group.name}: início e fim no mesmo ponto")
        return res
    yaw = yaw_between(a, b)
    if not is_on_grid(yaw, 90):
        res.warnings.append(f"{group.name}: cerca em {yaw:.1f}° gera vértices fora do grid")
    spacing = _num(start, "spacing")
    mode = start.get("mode", DEFAULTS["mode"])

    if mode == "prop":
        model = start.get("model") or DEFAULTS["model"]
        include_end = start.get("prop_at_end", DEFAULTS["prop_at_end"]) == "1"
        p_spacing, yaw_extra, z_off = _auto_prop(start, model, res)
        # o prop é centrado no seu bbox: primeiro fica em spacing/2, último não passa do fim
        xs = [x + p_spacing / 2 for x in repeat.positions(length - p_spacing, p_spacing, include_end=False)] if length >= p_spacing else []
        if include_end and xs and length - (xs[-1] + p_spacing / 2) > 1e-6:
            xs.append(length - p_spacing / 2)
        for x in xs:
            pos = brush.to_world(Vec(x, 0, z_off), a, yaw)
            res.ents.append(vmf.create_ent(
                "prop_static", origin=pos, angles=f"0 {(yaw + yaw_extra) % 360:.3f} 0", model=model, solid="6",
            ))
        if not xs:
            res.warnings.append(f"{group.name}: cerca menor que um módulo do modelo ({p_spacing}u)")
        return res

    height, thick = _num(start, "height"), _num(start, "thickness")
    post, extra = _num(start, "post_size"), _num(start, "post_extra")
    mat = start.get("material") or DEFAULTS["material"]
    mat_post = start.get("material_post") or mat
    solids = []
    for x in repeat.positions(length, spacing, include_end=True):
        solids.append(brush.box(vmf, Vec(x - post / 2, -post / 2, 0), Vec(x + post / 2, post / 2, height + extra), mat_post))
    for x0, x1 in repeat.segments(length, spacing):
        if (x1 - post / 2) - (x0 + post / 2) <= 0:
            continue  # resto menor que o poste: o poste final já fecha
        solids.append(brush.box(vmf, Vec(x0 + post / 2, -thick / 2, 0), Vec(x1 - post / 2, thick / 2, height), mat,
                                nodraw=("bottom",)))
    brush.place(solids, a, yaw)
    res.solids = solids
    return res

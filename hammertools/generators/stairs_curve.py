"""ht_stairs_curve: escada/rampa em curva por 3 marcadores.

`ht_stairs_curve` no pé (chão, centro da largura), `ht_stairs_curve_ctrl` no ponto de controle
(define a curvatura, altura ignorada) e `ht_stairs_curve_end` no piso de cima. Curva = bezier
quadrática em XY; degraus com altura constante. Sem rampa de playerclip (v1).
"""
from __future__ import annotations

from srctools import VMF, Vec

from hammertools.core import brush, curves
from hammertools.core.vmf import Group, origin
from hammertools.generators import Result, register

DEFAULTS = {
    "width": 64.0,
    "step_height": 8.0,
    "style": "solid",
    "tread_thickness": 8.0,
    "grid": 1.0,
    "material": "dev/dev_measuregeneric01b",
    "material_top": "",
}


@register("ht_stairs_curve")
def generate(vmf: VMF, group: Group) -> Result:
    res = Result()
    start, end = group.by_role("start"), group.by_role("end")
    ctrl = next((e for e in group.ents if e["classname"].endswith("_ctrl")), None)
    if start is None or end is None or ctrl is None:
        res.warnings.append(f"{group.name}: precisa de ht_stairs_curve, ht_stairs_curve_ctrl e ht_stairs_curve_end com o mesmo targetname")
        return res
    a, c, b = origin(start), origin(ctrl), origin(end)
    a2, c2, b2 = Vec(a.x, a.y, 0), Vec(c.x, c.y, 0), Vec(b.x, b.y, 0)
    rise = b.z - a.z
    if rise <= 0:
        res.warnings.append(f"{group.name}: o fim precisa estar acima do início")
        return res
    width = float(start.get("width", DEFAULTS["width"]))
    step_h = float(start.get("step_height", DEFAULTS["step_height"]))
    style = start.get("style", DEFAULTS["style"])
    tread = float(start.get("tread_thickness", DEFAULTS["tread_thickness"]))
    grid = float(start.get("grid", DEFAULTS["grid"]))
    mat = start.get("material") or DEFAULTS["material"]
    mat_top = start.get("material_top") or None
    n = max(1, round(rise / step_h))
    h = rise / n
    if h > 18:
        res.warnings.append(f"{group.name}: degrau de {h:.1f}u passa do máximo do Source (18)")

    samples = []
    for i in range(n + 1):
        t = i / n
        p = curves.bezier2(a2, c2, b2, t)
        nrm = curves.left_normal_xy(curves.bezier2_tangent(a2, c2, b2, t))
        samples.append((p, nrm))
    solids = []
    for i in range(n):
        (p0, n0), (p1, n1) = samples[i], samples[i + 1]
        # anti-horário visto de cima: direita0, direita1, esquerda1, esquerda0
        quad = [p0 - n0 * (width / 2), p1 - n1 * (width / 2), p1 + n1 * (width / 2), p0 + n0 * (width / 2)]
        z_top = a.z + (i + 1) * h
        z_bot = a.z if style == "solid" else max(a.z, z_top - tread)
        solids.append(brush.quad_prism(vmf, quad, z_bot, z_top, mat, mat_top, nodraw_bottom=(style == "solid"), grid=grid))
    res.solids = solids
    return res

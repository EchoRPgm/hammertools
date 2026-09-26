"""ht_stairs: escada reta entre dois marcadores.

Marcador `ht_stairs`: pé da escada, no nível do chão, centro da largura, na borda do 1º degrau.
Marcador `ht_stairs_end`: nível do piso de cima, centro da largura, na borda do último degrau.
Parâmetros lidos do ht_stairs.
"""
from __future__ import annotations

import math

from srctools import VMF, Vec

from hammertools.core import brush
from hammertools.core.vmf import Group, horizontal_dist, is_on_grid, origin, yaw_between
from hammertools.generators import Result, register

DEFAULTS = {
    "width": 64.0,
    "step_height": 8.0,
    "style": "solid",          # solid = cada degrau vai até o chão; floating = só a laje do degrau
    "material": "dev/dev_measuregeneric01b",
    "material_top": "",
    "nodraw_hidden": "1",
    "tread_thickness": 8.0,    # só pra style=floating
    "playerclip": "1",         # rampa de tools/toolsplayerclip sobre os degraus (subida lisa)
}

PLAYERCLIP = "tools/toolsplayerclip"


def clip_ramp(vmf: VMF, run: float, rise: float, d: float, h: float, half: float, style: str, tread: float):
    """Rampa de clip pelos narizes dos degraus. Narizes em (i*d, (i+1)*h), i=0..n-1: reta de inclinação h/d
    que passa por (-d, 0) e (run-d, rise); de run-d até run o topo é plano no nível do piso de cima.
    Sólida: prisma (-d,0) (run-d,rise) (run,rise) (run,0). Flutuante: laje inclinada logo abaixo da reta,
    pra não fechar o espaço embaixo da escada."""
    m = PLAYERCLIP
    x1 = run - d
    if style == "solid":
        return brush.from_points(vmf, [
            ((-d, half, 0), (x1, half, rise), (x1, -half, rise), m),      # rampa
            ((x1, half, rise), (run, half, rise), (run, -half, rise), m),  # topo plano
            ((-d, -half, 0), (run, -half, 0), (run, half, 0), m),          # base
            ((-d, half, 0), (run, half, 0), (run, half, rise), m),         # lateral +Y
            ((run, -half, 0), (-d, -half, 0), (run, -half, rise), m),      # lateral -Y
            ((run, half, 0), (run, -half, 0), (run, -half, rise), m),      # cap traseiro x=run
        ])
    return brush.sloped_bar(vmf, -d, x1, -half, half, -tread, rise - tread, tread, m)


def _num(ent, key: str) -> float:
    return float(ent.get(key, DEFAULTS[key]))


@register("ht_stairs")
def generate(vmf: VMF, group: Group) -> Result:
    res = Result()
    start, end = group.by_role("start"), group.by_role("end")
    if start is None or end is None:
        res.warnings.append(f"{group.name}: precisa de um ht_stairs (pé) e um ht_stairs_end (topo) com o mesmo targetname")
        return res

    a, b = origin(start), origin(end)
    rise = b.z - a.z
    run = horizontal_dist(a, b)
    if rise <= 0 or run <= 0:
        res.warnings.append(f"{group.name}: end precisa estar acima e à frente do start (rise={rise}, run={run})")
        return res

    width = _num(start, "width")
    step_h_target = _num(start, "step_height")
    style = start.get("style", DEFAULTS["style"])
    mat = start.get("material") or DEFAULTS["material"]
    mat_top = start.get("material_top") or None
    use_nodraw = start.get("nodraw_hidden", DEFAULTS["nodraw_hidden"]) == "1"
    tread = _num(start, "tread_thickness")

    n = max(1, round(rise / step_h_target))
    h = rise / n
    d = run / n
    if h > 18:
        res.warnings.append(f"{group.name}: degrau de {h:.1f}u é mais alto que o step máximo do Source (18)")
    if not is_on_grid(h) or not is_on_grid(d):
        res.warnings.append(f"{group.name}: degrau {d:.2f}x{h:.2f} não é inteiro; ajuste a distância entre marcadores")

    yaw = yaw_between(a, b)
    if not is_on_grid(yaw, 90):
        res.warnings.append(f"{group.name}: escada em {yaw:.1f}° gera vértices fora do grid")

    half = width / 2
    solids = []
    for i in range(n):
        x0, x1 = i * d, (i + 1) * d
        z_top = (i + 1) * h
        z_bot = 0.0 if style == "solid" else max(0.0, z_top - tread)
        # Faces realmente escondidas: na escada sólida, a base (encostada no chão) e a face
        # traseira (+X, coberta pelo degrau seguinte, exceto no último). Na flutuante, nenhuma.
        nodraw: tuple[str, ...] = ()
        if use_nodraw and style == "solid":
            nodraw = ("bottom", "east") if i < n - 1 else ("bottom",)
        solids.append(brush.box(vmf, Vec(x0, -half, z_bot), Vec(x1, half, z_top), mat, top=mat_top, nodraw=nodraw))
    if start.get("playerclip", DEFAULTS["playerclip"]) == "1":
        solids.append(clip_ramp(vmf, run, rise, d, h, half, style, tread))
    brush.place(solids, a, yaw)
    res.solids = solids
    return res

"""ht_door: porta completa num único marcador.

Origem = centro do vão, no chão. Yaw (angles) = direção pra onde a porta abre / lado de "fora".
Gera: folha (prop_door_rotating ou func_door de brush), batente (2 ombreiras + verga), e
opcionalmente trigger_multiple dos dois lados que abre/fecha sozinho.
"""
from __future__ import annotations

from srctools import VMF, Vec

from hammertools.core import brush, ents
from hammertools.core.vmf import Group, origin
from hammertools.generators import Result, register

DEFAULTS = {
    "type": "prop",                 # prop = prop_door_rotating; brush = func_door deslizante
    "width": 56.0, "height": 112.0, "thickness": 8.0,
    "frame": "1", "frame_size": 8.0, "frame_depth": 16.0,
    "material": "dev/dev_measuregeneric01b", "material_frame": "",
    "model": "models/props_c17/door01_left.mdl", "hinge": "left", "model_yaw": 0.0,
    "slide": "side",                # brush: side (desliza pro lado) | up
    "speed": 100.0, "wait": 4.0, "auto_open": "0", "trigger_depth": 48.0,
    "locked": "0",
}


def _f(ent, k):
    return float(ent.get(k, DEFAULTS[k]))


@register("ht_door", single=True)
def generate(vmf: VMF, group: Group) -> Result:
    res = Result()
    start = group.by_role("start")
    if start is None:
        res.warnings.append(f"{group.name}: marcador ht_door ausente")
        return res
    a = origin(start)
    yaw = float(start.get("angles", "0 0 0").split()[1]) if start.get("angles") else 0.0
    name = group.name
    kind = start.get("type", DEFAULTS["type"])
    w, h, t = _f(start, "width"), _f(start, "height"), _f(start, "thickness")
    mat = start.get("material") or DEFAULTS["material"]
    mat_frame = start.get("material_frame") or mat
    solids, ent_list = [], []

    # batente: ombreiras em y=±(w/2+fs/2), verga em z=h..h+fs; profundidade frame_depth em X
    if start.get("frame", DEFAULTS["frame"]) == "1":
        fs, fd = _f(start, "frame_size"), _f(start, "frame_depth")
        for sy in (-1, 1):
            solids.append(brush.box(vmf, Vec(-fd / 2, sy * (w / 2) + (0 if sy < 0 else 0) - (fs if sy < 0 else 0), 0),
                                    Vec(fd / 2, sy * (w / 2) + (fs if sy > 0 else 0), h + fs), mat_frame))
        solids.append(brush.box(vmf, Vec(-fd / 2, -w / 2, h), Vec(fd / 2, w / 2, h + fs), mat_frame))

    door_name = name
    if kind == "prop":
        hinge_y = -w / 2 if start.get("hinge", DEFAULTS["hinge"]) == "left" else w / 2
        pos = brush.to_world(Vec(0, hinge_y, 0), a, yaw)
        e = vmf.create_ent(
            "prop_door_rotating", origin=pos, targetname=door_name,
            angles=ents.angles_str(0, yaw + _f(start, "model_yaw") + (180 if hinge_y > 0 else 0)),
            model=start.get("model") or DEFAULTS["model"], distance="90", speed=str(_f(start, "speed")),
            returndelay=str(int(_f(start, "wait"))), spawnflags="0", hardware="1",
            opendir="0", forceclosed="0", spawnpos="0", ajarangles="0 0 0",
        )
        if start.get("locked", DEFAULTS["locked"]) == "1":
            e["spawnflags"] = "2048"
        ent_list.append(e)
    else:
        slab = brush.box(vmf, Vec(-t / 2, -w / 2, 0), Vec(t / 2, w / 2, h), mat)
        brush.place([slab], a, yaw)
        up = start.get("slide", DEFAULTS["slide"]) == "up"
        movedir = ents.angles_str(-90, 0, 0) if up else ents.angles_str(0, yaw + 90, 0)
        e = ents.brush_ent(vmf, "func_door", [slab], targetname=door_name, origin=a, movedir=movedir,
                           speed=_f(start, "speed"), wait=_f(start, "wait"), lip="4",
                           spawnflags="0" if start.get("locked", DEFAULTS["locked"]) != "1" else "2048",
                           noise1="doors/door_metal_medium_open1.wav", noise2="doors/door_metal_medium_close2.wav")
        ent_list.append(e)

    # trigger dos dois lados: abre ao entrar, fecha ao sair
    if start.get("auto_open", DEFAULTS["auto_open"]) == "1":
        td = _f(start, "trigger_depth")
        tb = brush.box(vmf, Vec(-td, -w / 2 - 16, 0), Vec(td, w / 2 + 16, h), "tools/toolstrigger")
        brush.place([tb], a, yaw)
        tr = ents.brush_ent(vmf, "trigger_multiple", [tb], targetname=f"{name}_trigger", origin=a, spawnflags="1", wait="0.2")
        ents.out(tr, "OnStartTouch", door_name, "Open")
        ents.out(tr, "OnEndTouchAll", door_name, "Close", delay=1.0)
        ent_list.append(tr)

    brush.place(solids, a, yaw)
    res.solids, res.ents = solids, ent_list
    return res

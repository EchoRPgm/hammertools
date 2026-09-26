"""ht_elevator: elevador entre dois andares.

`ht_elevator` no andar de baixo (centro da plataforma, nível do piso), `ht_elevator_end` no de cima
(mesma XY). Gera: plataforma func_door (movedir pra cima, lip negativo = curso), botão a bordo
(Toggle) e botões de chamada em cada andar (Open no de cima, Close no de baixo), com I/O pronta.
O yaw do marcador de baixo diz de que lado ficam os botões de chamada.
"""
from __future__ import annotations

from srctools import VMF, Vec

from hammertools.core import brush, ents
from hammertools.core.vmf import Group, horizontal_dist, origin
from hammertools.generators import Result, register

DEFAULTS = {
    "width": 128.0, "depth": 128.0, "thickness": 8.0, "speed": 100.0,
    "material": "dev/dev_measuregeneric01b", "material_button": "dev/dev_measuregeneric01",
    "button_size": 16.0, "call_buttons": "1", "onboard_button": "1", "button_height": 48.0,
    "sound_move": "plats/elevator_move.wav", "sound_stop": "plats/elevator_stop.wav",
}


def _f(ent, k):
    return float(ent.get(k, DEFAULTS[k]))


@register("ht_elevator")
def generate(vmf: VMF, group: Group) -> Result:
    res = Result()
    start, end = group.by_role("start"), group.by_role("end")
    if start is None or end is None:
        res.warnings.append(f"{group.name}: precisa de ht_elevator (baixo) e ht_elevator_end (cima) com o mesmo targetname")
        return res
    a, b = origin(start), origin(end)
    rise = b.z - a.z
    if rise <= 0:
        res.warnings.append(f"{group.name}: o andar de cima precisa estar acima")
        return res
    if horizontal_dist(a, b) > 0.5:
        res.warnings.append(f"{group.name}: topo deslocado em XY; a plataforma sobe reto a partir do de baixo")
    yaw = float(start.get("angles", "0 0 0").split()[1]) if start.get("angles") else 0.0
    w, d, t = _f(start, "width"), _f(start, "depth"), _f(start, "thickness")
    mat, matb = start.get("material") or DEFAULTS["material"], start.get("material_button") or DEFAULTS["material_button"]
    bs, bh = _f(start, "button_size"), _f(start, "button_height")
    name = group.name
    ent_list = []

    # plataforma apoiada no piso de baixo (z 0..t). Embutir no piso exigiria um poço do usuário.
    # No topo, a superfície fica em rise + t: o patamar de chegada deve ter o piso nessa altura.
    plat = brush.box(vmf, Vec(-d / 2, -w / 2, 0), Vec(d / 2, w / 2, t), mat, nodraw=("bottom",))
    brush.place([plat], a, yaw)
    lift = ents.brush_ent(vmf, "func_door", [plat], targetname=name, origin=a, movedir=ents.angles_str(-90, 0, 0),
                          speed=_f(start, "speed"), wait="-1", lip=str(t - rise), spawnflags="1024",  # 1024 = use opens
                          noise1=start.get("sound_move", DEFAULTS["sound_move"]), noise2=start.get("sound_stop", DEFAULTS["sound_stop"]),
                          forceclosed="1", dmg="0")
    ent_list.append(lift)

    # botão a bordo: pequeno poste na borda traseira (-X local), parentado à plataforma
    if start.get("onboard_button", DEFAULTS["onboard_button"]) == "1":
        post = brush.box(vmf, Vec(-d / 2, -bs / 2, t), Vec(-d / 2 + bs / 2, bs / 2, t + bh), mat)
        bb = brush.box(vmf, Vec(-d / 2 + bs / 2, -bs / 4, t + bh - bs / 2), Vec(-d / 2 + bs, bs / 4, t + bh), matb)
        brush.place([post, bb], a, yaw)
        res.solids.append(post)
        onb = ents.brush_ent(vmf, "func_button", [bb], targetname=f"{name}_btn", origin=a, parentname=name,
                             spawnflags="1025", wait="1", speed="5", sounds="3")  # 1024 use activates, 1 don't move
        ents.out(onb, "OnPressed", name, "Toggle")
        ent_list.append(onb)
        # o botão a bordo precisa subir junto: parentname resolve isso

    # botões de chamada nos andares, do lado indicado pelo yaw (+X local), fora da plataforma
    if start.get("call_buttons", DEFAULTS["call_buttons"]) == "1":
        for z, inp, suffix in ((0.0, "Close", "call_down"), (rise + t, "Open", "call_up")):
            bx = d / 2 + 8
            cb = brush.box(vmf, Vec(bx, -bs / 2, z + bh - bs / 2), Vec(bx + bs / 2, bs / 2, z + bh), matb)
            brush.place([cb], a, yaw)
            e = ents.brush_ent(vmf, "func_button", [cb], targetname=f"{name}_{suffix}", origin=a, spawnflags="1025", wait="1", speed="5", sounds="3")
            ents.out(e, "OnPressed", name, inp)
            ent_list.append(e)
    res.ents = ent_list
    return res

"""ht_rope: cabo (move_rope + keyframe_rope encadeados) ou trilho de brush por uma sequência de pontos.

`ht_rope` no início, `ht_rope_node` (order) nos pontos intermediários, `ht_rope_end` no fim.
kind=rope: entidades de corda com folga (`slack`). kind=rail: dois trilhos (brush) + dormentes.
"""
from __future__ import annotations

from srctools import VMF, Vec

from hammertools.core import brush, ents, repeat
from hammertools.core.vmf import Group, origin
from hammertools.generators import Result, register

DEFAULTS = {
    "kind": "rope", "slack": 25.0, "width": 2.0, "rope_material": "cable/cable.vmt", "subdiv": 4,
    "gauge": 64.0, "rail_size": 4.0, "tie_spacing": 48.0, "tie_size": 8.0, "tie_width": 96.0,
    "material": "dev/dev_measuregeneric01b",
    "train": "0", "train_mode": "auto", "train_length": 128.0, "train_width": 80.0, "train_height": 48.0,
    "train_speed": 200.0, "loop": "0", "material_train": "",
}


def _f(ent, k):
    return float(ent.get(k, DEFAULTS[k]))


def _markers(group: Group):
    start, end = group.by_role("start"), group.by_role("end")
    if start is None or end is None:
        return None
    nodes = sorted((e for e in group.ents if e["classname"].endswith("_node")), key=lambda e: float(e.get("order", 0)))
    return [start] + nodes + [end]


def _path(group: Group):
    ms = _markers(group)
    return None if ms is None else [origin(m) for m in ms]


@register("ht_rope")
def generate(vmf: VMF, group: Group) -> Result:
    res = Result()
    path = _path(group)
    if path is None:
        res.warnings.append(f"{group.name}: precisa de ht_rope (início) e ht_rope_end (fim) com o mesmo targetname")
        return res
    start = group.by_role("start")
    if start.get("kind", DEFAULTS["kind"]) == "rail":
        return _rail(vmf, group, start, path, res)
    slack, width = _f(start, "slack"), _f(start, "width")
    mat, subdiv = start.get("rope_material") or DEFAULTS["rope_material"], int(_f(start, "subdiv"))
    names = [f"{group.name}_{i}" for i in range(len(path))]
    for i, p in enumerate(path):
        cls = "move_rope" if i == 0 else "keyframe_rope"
        kv = dict(origin=p, targetname=names[i], Slack=str(slack), Width=str(width), RopeMaterial=mat,
                  Subdiv=str(subdiv), TextureScale="1", Type="0", MoveSpeed="64", PositionInterpolator="2")
        if i + 1 < len(path):
            kv["NextKey"] = names[i + 1]
        res.ents.append(vmf.create_ent(cls, **kv))
    return res


def _rail(vmf, group, start, path, res):
    gauge, rs = _f(start, "gauge"), _f(start, "rail_size")
    ts, tsz, tw = _f(start, "tie_spacing"), _f(start, "tie_size"), _f(start, "tie_width")
    mat = start.get("material") or DEFAULTS["material"]
    solids = []
    segs = list(zip(path, path[1:]))
    if start.get("loop", DEFAULTS["loop"]) == "1" and len(path) > 2:
        segs.append((path[-1], path[0]))  # fecha o circuito
    for p, q in segs:
        d = q - p
        L = d.mag()
        if L < 1e-6:
            continue
        pitch, yaw = brush.direction_angles(d)
        seg = []
        for sy in (-gauge / 2, gauge / 2):
            seg.append(brush.box(vmf, Vec(0, sy - rs / 2, tsz), Vec(L, sy + rs / 2, tsz + rs), mat))
        for x in repeat.positions(L, ts, include_end=False):
            if x + tsz > L + 1e-6:
                continue  # dormente não passa do fim do trecho
            seg.append(brush.box(vmf, Vec(x, -tw / 2, 0), Vec(x + tsz, tw / 2, tsz), mat))
        brush.place3d(seg, p, pitch, yaw)
        for s in seg:
            for side in s.sides:
                side.planes = [brush.snap(pt) for pt in side.planes]
        solids.extend(seg)
    res.solids = solids
    if start.get("train", DEFAULTS["train"]) == "1":
        _train(vmf, group, start, path, tsz + rs, res)
    return res


def _station(vmf, train_name, marker, pt, track_name, res):
    """Estação: o marcador do ponto tem `stop` (s), sons e outputs OnArrive/OnDepart. Tudo vira I/O
    no path_track: OnPass -> trem Stop; OnArrive do usuário; OnPass(+stop) -> trem StartForward + OnDepart."""
    stop = float(marker.get("stop", 0) or 0)
    arrive = [o for o in marker.outputs if o.output.lower() == "onarrive"]
    depart = [o for o in marker.outputs if o.output.lower() == "ondepart"]
    a_snd, d_snd = marker.get("arrive_sound", ""), marker.get("depart_sound", "")
    if stop <= 0 and not (arrive or depart or a_snd or d_snd):
        return
    origin_ = Vec.from_str(pt["origin"])
    if a_snd:
        sa = vmf.create_ent("ambient_generic", origin=origin_ + Vec(0, 0, 32), targetname=f"{track_name}_snd_a", message=a_snd, health="10", radius="1250", spawnflags="48")
        res.ents.append(sa); ents.out(pt, "OnPass", sa["targetname"], "PlaySound")
    if d_snd:
        sd = vmf.create_ent("ambient_generic", origin=origin_ + Vec(0, 0, 40), targetname=f"{track_name}_snd_d", message=d_snd, health="10", radius="1250", spawnflags="48")
        res.ents.append(sd); ents.out(pt, "OnPass", sd["targetname"], "PlaySound", delay=max(stop, 0.0))
    if stop > 0:
        ents.out(pt, "OnPass", train_name, "Stop")
        ents.out(pt, "OnPass", train_name, "StartForward", delay=stop)
    for o in arrive:
        ents.out(pt, "OnPass", o.target, o.input, o.params, o.delay, o.only_once)
    for o in depart:
        ents.out(pt, "OnPass", o.target, o.input, o.params, o.delay + max(stop, 0.0), o.only_once)


def _train(vmf, group, start, path, rail_top, res):
    """Vagão func_tracktrain dirigível: path_track em cada ponto (na altura do topo do trilho),
    carroceria de brush no 1º ponto, func_traincontrols parentado (E dentro do vagão = dirigir)."""
    name = group.name
    L, W, H = _f(start, "train_length"), _f(start, "train_width"), _f(start, "train_height")
    mat = start.get("material_train") or start.get("material") or DEFAULTS["material"]
    loop = start.get("loop", DEFAULTS["loop"]) == "1"
    tracks = [f"{name}_t{i}" for i in range(len(path))]
    markers = _markers(group)
    for i, p in enumerate(path):
        kv = dict(origin=p + Vec(0, 0, rail_top), targetname=tracks[i])
        if i + 1 < len(path):
            kv["target"] = tracks[i + 1]
        elif loop:
            kv["target"] = tracks[0]
        pt = vmf.create_ent("path_track", **kv)
        res.ents.append(pt)
        _station(vmf, name, markers[i], pt, tracks[i], res)
    p0 = path[0] + Vec(0, 0, rail_top)
    d = path[1] - path[0]
    pitch, yaw = brush.direction_angles(d)
    body = brush.box(vmf, Vec(-L / 2, -W / 2, 0), Vec(L / 2, W / 2, 8), mat)                 # chassi
    walls = [
        brush.box(vmf, Vec(-L / 2, -W / 2, 8), Vec(-L / 2 + 8, W / 2, H), mat),               # traseira
        brush.box(vmf, Vec(L / 2 - 8, -W / 2, 8), Vec(L / 2, W / 2, H), mat),                 # frente
        brush.box(vmf, Vec(-L / 2, -W / 2, 8), Vec(L / 2, -W / 2 + 4, round(H * 0.6)), mat),   # mureta lateral
        brush.box(vmf, Vec(-L / 2, W / 2 - 4, 8), Vec(L / 2, W / 2, round(H * 0.6)), mat),
    ]
    car = [body, *walls]
    brush.place3d(car, p0, 0, yaw)
    auto = start.get("train_mode", DEFAULTS["train_mode"]) != "manual"
    speed = _f(start, "train_speed")
    train = ents.brush_ent(vmf, "func_tracktrain", car, targetname=name, origin=p0, target=tracks[0],
                           speed=speed, startspeed=(speed if auto else 0), wheels=str(L * 0.75), height="8",
                           bank="0", dmg="0", volume="10",
                           spawnflags=("514" if auto else "512"),  # 512 = Is unblockable by player (senão "Blocked by player" e trava); 2 = No User Control
                           velocitytype="1", orientationtype="1",
                           MoveSound="plats/train_move.wav", StopSound="plats/train_stop.wav")
    res.ents.append(train)
    if auto:
        la = vmf.create_ent("logic_auto", origin=p0 + Vec(0, 0, 64), targetname=f"{name}_auto", spawnflags="1")
        ents.out(la, "OnMapSpawn", name, "StartForward", delay=0.5)
        res.ents.append(la)
    else:
        ctl = brush.box(vmf, Vec(L / 2 - 40, -W / 2 + 8, 8), Vec(L / 2 - 8, W / 2 - 8, H), "tools/toolstrigger")
        brush.place3d([ctl], p0, 0, yaw)
        res.ents.append(ents.brush_ent(vmf, "func_traincontrols", [ctl], target=name, parentname=name, origin=p0))

"""ht_rope: cabo (move_rope + keyframe_rope encadeados) ou trilho de brush por uma sequência de pontos.

`ht_rope` no início, `ht_rope_node` (order) nos pontos intermediários, `ht_rope_end` no fim.
kind=rope: entidades de corda com folga (`slack`). kind=rail: dois trilhos (brush) + dormentes.
"""
from __future__ import annotations

from srctools import VMF, Vec

from hammertools.core import brush, curves, ents, repeat
from hammertools.core.vmf import Group, origin
from hammertools.generators import Result, register

DEFAULTS = {
    "kind": "rope", "slack": 25.0, "width": 2.0, "rope_material": "cable/cable.vmt", "subdiv": 4,
    "gauge": 64.0, "rail_size": 4.0, "tie_spacing": 48.0, "tie_size": 8.0, "tie_width": 96.0,
    "material": "dev/dev_measuregeneric01b",
    "curve_radius": 256.0, "curve_segments": 6,
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
    """Trilho contínuo: cantos arredondados (arco tangente de `curve_radius`), cada trilho é uma varredura
    de seção retangular com anéis compartilhados entre pedaços (sem fresta), dormentes seguem a curva."""
    import math
    gauge, rs = _f(start, "gauge"), _f(start, "rail_size")
    ts, tsz, tw = _f(start, "tie_spacing"), _f(start, "tie_size"), _f(start, "tie_width")
    mat = start.get("material") or DEFAULTS["material"]
    closed = start.get("loop", DEFAULTS["loop"]) == "1" and len(path) > 2
    radius = _f(start, "curve_radius")
    rmin = gauge / 2 + 2 * rs
    if 0 < radius < rmin:
        res.warnings.append(f"{group.name}: raio de curva {radius:.0f} < meia bitola + folga ({rmin:.0f}); trilho interno se cruzaria, usando {rmin:.0f}")
        radius = rmin
    samples = curves.rounded_path(path, radius, int(_f(start, "curve_segments")), closed, res.warnings)
    pts = [q for q, _ in samples]
    if closed:
        pts = pts + [pts[0]]
    up = Vec(0, 0, 1)
    # normal lateral (horizontal) de cada trecho; em cada junta, bissetriz exata (offset de polilinha
    # com miter: largura constante e faces laterais planas, inclusive na costura arco->reto)
    def seg_n(a, b):
        d = Vec(b.x - a.x, b.y - a.y, 0)
        return Vec.cross(up, d.norm()) if d.mag() > 1e-9 else None
    segn = [seg_n(a, b) for a, b in zip(pts, pts[1:])]
    for i in range(len(segn)):  # trechos degenerados herdam a normal vizinha
        if segn[i] is None:
            segn[i] = segn[i - 1] if i > 0 and segn[i - 1] is not None else Vec(0, 1, 0)
    miters = []
    for i in range(len(pts)):
        if i == 0:
            n_prev, n_next = (segn[-1] if closed else segn[0]), segn[0]
        elif i == len(pts) - 1:
            n_prev, n_next = segn[-1], (segn[0] if closed else segn[-1])
        else:
            n_prev, n_next = segn[i - 1], segn[i]
        bis = n_prev + n_next
        bis = bis.norm() if bis.mag() > 1e-6 else n_next
        miters.append((bis, max(0.3, bis.dot(n_next))))
    solids = []
    for side in (-1, 1):
        rings = []
        for i, q in enumerate(pts):
            nrm, cosh = miters[i]
            c = q + nrm * (side * gauge / 2 / cosh)
            w = nrm * (rs / 2 / cosh)
            rings.append([c - w + up * tsz, c + w + up * tsz, c + w + up * (tsz + rs), c - w + up * (tsz + rs)])
        # pedaços curtos demais colapsam no arredondamento pro grid: pula o anel e liga no próximo
        # (o anel anterior continua sendo a base, então não abre fresta)
        last = rings[0]
        for k, rb in enumerate(rings[1:], start=1):
            ca, cb = sum(last, Vec()) / 4, sum(rb, Vec()) / 4
            if (cb - ca).mag() < 4 and k < len(rings) - 1:
                continue
            if (cb - ca).mag() < 1:
                continue
            try:
                solids.append(brush.sweep_piece(vmf, last, rb, mat, grid=0.125))  # trilho fino: grade 1 torceria as curvas
            except ValueError:
                continue  # face degenerada após o snap (curva apertada demais pro grid): liga no próximo anel
            last = rb
    # dormentes pelo comprimento da curva
    seglens = [(b - a).mag() for a, b in zip(pts, pts[1:])]
    total = sum(seglens)
    for x0 in repeat.positions(total, ts, include_end=False):
        if x0 + tsz > total + 1e-6:
            continue  # dormente não passa do fim
        x = x0 + tsz / 2  # centro do dormente (a borda de trás fica em x0)
        acc, k = 0.0, 0
        while k < len(seglens) - 1 and acc + seglens[k] < x:
            acc += seglens[k]; k += 1
        if seglens[k] <= 1e-9:
            continue
        u = (x - acc) / seglens[k]
        c = pts[k] + (pts[k + 1] - pts[k]) * u
        d = pts[k + 1] - pts[k]
        pitch, yaw = brush.direction_angles(d)
        tie = brush.box(vmf, Vec(-tsz / 2, -tw / 2, 0), Vec(tsz / 2, tw / 2, tsz), mat)
        brush.place3d([tie], c, pitch, yaw)
        for sd in tie.sides:
            sd.planes = [brush.snap(pt) for pt in sd.planes]
        solids.append(tie)
    res.solids = solids
    if start.get("train", DEFAULTS["train"]) == "1":
        _train(vmf, group, start, samples, tsz + rs, res, closed)
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


def _train(vmf, group, start, samples, rail_top, res, closed):
    """Vagão func_tracktrain dirigível: path_track em cada ponto (na altura do topo do trilho),
    carroceria de brush no 1º ponto, func_traincontrols parentado (E dentro do vagão = dirigir)."""
    name = group.name
    L, W, H = _f(start, "train_length"), _f(start, "train_width"), _f(start, "train_height")
    mat = start.get("material_train") or start.get("material") or DEFAULTS["material"]
    path = [q for q, _ in samples]
    # remove amostras duplicadas consecutivas (fim de arco = começo do reto)
    dedup = []
    for q, mi in samples:
        if dedup and (dedup[-1][0] - q).mag() < 1:
            if mi is not None:
                dedup[-1] = (dedup[-1][0], mi)
            continue
        dedup.append((q, mi))
    if closed and len(dedup) > 1 and (dedup[0][0] - dedup[-1][0]).mag() < 1:
        dedup.pop()
    tracks = [f"{name}_t{i}" for i in range(len(dedup))]
    markers = _markers(group)
    for i, (q, mi) in enumerate(dedup):
        kv = dict(origin=q + Vec(0, 0, rail_top), targetname=tracks[i])
        if i + 1 < len(dedup):
            kv["target"] = tracks[i + 1]
        elif closed:
            kv["target"] = tracks[0]
        pt = vmf.create_ent("path_track", **kv)
        res.ents.append(pt)
        if mi is not None:
            _station(vmf, name, markers[mi], pt, tracks[i], res)
    # vagão nasce no começo do trecho reto mais longo (rotação limpa, fora das curvas)
    nxt = lambda i: (i + 1) % len(dedup) if closed else min(i + 1, len(dedup) - 1)
    si = max(range(len(dedup) - (0 if closed else 1)), key=lambda i: (dedup[nxt(i)][0] - dedup[i][0]).mag())
    p0 = dedup[si][0] + Vec(0, 0, rail_top)
    d = dedup[nxt(si)][0] - dedup[si][0]
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
    train = ents.brush_ent(vmf, "func_tracktrain", car, targetname=name, origin=p0, target=tracks[si],
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

"""ht_pipe: tubo/duto por uma sequência de pontos, com cotovelos curvos.

`ht_pipe` no início, `ht_pipe_node` nos vértices (keyvalue `order`), `ht_pipe_end` no fim; mesmo targetname.
Seção quadrada (4) ou octogonal (8), sólida ou oca. Em cada vértice intermediário entra um cotovelo:
arco tangente aos dois trechos com raio `bend_radius`, feito de `bend_segments` pedaços (por 90°).
Os trechos retos são encurtados pela tangente. Funciona em qualquer ângulo, horizontal ou vertical.
"""
from __future__ import annotations

import math

from srctools import Angle, VMF, Vec

from hammertools.core import brush
from hammertools.core.vmf import Group, origin
from hammertools.generators import Result, register

DEFAULTS = {
    "radius": 32.0,
    "sides": 4,
    "hollow": "0",
    "wall": 4.0,
    "bend_radius": "auto",     # auto = 2 * radius
    "bend_segments": 4,        # pedaços por 90° de curva
    "grid": 1.0,
    "material": "dev/dev_measuregeneric01b",
    "material_inside": "",
}


def _path(group: Group) -> list[Vec] | None:
    start, end = group.by_role("start"), group.by_role("end")
    if start is None or end is None:
        return None
    nodes = [e for e in group.ents if e["classname"].endswith("_node")]
    nodes.sort(key=lambda e: float(e.get("order", 0)))
    return [origin(start)] + [origin(n) for n in nodes] + [origin(end)]


def _profile(R: float, sides: int, grid: float) -> list[tuple[float, float]]:
    """Vértices (y, z) da seção regular com face plana em cima/embaixo. `R` é o APÓTEMA (do eixo à
    face plana): radius=32 numa seção quadrada dá um tubo de 64 de largura."""
    off = math.pi / sides
    rc = R / math.cos(math.pi / sides)  # raio circunscrito
    return [(round(math.cos(off + 2 * math.pi * i / sides) * rc / grid) * grid,
             round(math.sin(off + 2 * math.pi * i / sides) * rc / grid) * grid) for i in range(sides)]


def _frame(d: Vec) -> tuple[Vec, Vec, Vec]:
    """(t, y, z) do trecho: t = direção; y, z = eixos locais Y e Z do mesmo Angle usado em place3d."""
    pitch, yaw = brush.direction_angles(d)
    ang = Angle(pitch, yaw, 0)
    return Vec(d).norm(), Vec(0, 1, 0) @ ang, Vec(0, 0, 1) @ ang


def _ring(center: Vec, y: Vec, z: Vec, prof: list[tuple[float, float]], scale: float = 1.0) -> list[Vec]:
    return [center + y * (py * scale) + z * (pz * scale) for py, pz in prof]


@register("ht_pipe")
def generate(vmf: VMF, group: Group) -> Result:
    res = Result()
    path = _path(group)
    if path is None:
        res.warnings.append(f"{group.name}: precisa de ht_pipe (início) e ht_pipe_end (fim) com o mesmo targetname")
        return res
    start = group.by_role("start")
    R = float(start.get("radius", DEFAULTS["radius"]))
    sides = int(float(start.get("sides", DEFAULTS["sides"])))
    hollow = start.get("hollow", DEFAULTS["hollow"]) == "1"
    wall = float(start.get("wall", DEFAULTS["wall"]))
    grid = float(start.get("grid", DEFAULTS["grid"]))
    br_raw = start.get("bend_radius", DEFAULTS["bend_radius"])
    Rb = 2 * R if br_raw in ("auto", "", None) else float(br_raw)
    segs90 = max(1, int(float(start.get("bend_segments", DEFAULTS["bend_segments"]))))
    mat = start.get("material") or DEFAULTS["material"]
    mat_in = start.get("material_inside") or mat
    if sides not in (4, 8):
        res.warnings.append(f"{group.name}: sides={sides} não suportado (4 ou 8); usando 4")
        sides = 4
    if hollow and wall >= R:
        res.warnings.append(f"{group.name}: parede {wall} maior que o raio; reduzida")
        wall = R / 2
    if Rb < R:
        res.warnings.append(f"{group.name}: raio de curvatura {Rb} menor que o raio do tubo {R}; o interior do cotovelo se auto-intersecta")

    prof = _profile(R, sides, grid)
    inner_scale = (R - wall) / R

    dirs = [q - p for p, q in zip(path, path[1:])]
    if any(d.mag() < 1e-6 for d in dirs):
        res.warnings.append(f"{group.name}: dois pontos consecutivos iguais")
        return res
    # ângulo e tangente em cada vértice interno
    thetas, tans = [], []
    for d1, d2 in zip(dirs, dirs[1:]):
        cosang = max(-1.0, min(1.0, d1.norm().dot(d2.norm())))
        th = math.acos(cosang)
        thetas.append(th)
        tans.append(Rb * math.tan(th / 2) if th > 1e-6 else 0.0)
    # trechos retos encurtados
    for i, d in enumerate(dirs):
        cut = (tans[i - 1] if i > 0 else 0.0) + (tans[i] if i < len(tans) else 0.0)
        if d.mag() < cut - 1e-6:
            res.warnings.append(f"{group.name}: trecho {i + 1} ({d.mag():.0f}u) menor que as tangentes dos cotovelos ({cut:.0f}u); reduza bend_radius")
            return res

    solids: list = []

    def add_section(ring_a, ring_b):
        if hollow:
            n = len(ring_a)
            ca = sum(ring_a, Vec()) / n
            cb = sum(ring_b, Vec()) / n
            ia = [ca + (p - ca) * inner_scale for p in ring_a]
            ib = [cb + (p - cb) * inner_scale for p in ring_b]
            for i in range(n):
                # fatia com laterais radiais: paredes vizinhas compartilham o mesmo plano (sem frestas/leak)
                solids.append(brush.ring_wall_piece(vmf, ring_a, ring_b, ia, ib, ca, cb, i, mat, mat_in, grid))
        else:
            solids.append(brush.sweep_piece(vmf, ring_a, ring_b, mat, grid=grid))

    for i, d in enumerate(dirs):
        t, y, z = _frame(d)
        p0 = path[i] + t * (tans[i - 1] if i > 0 else 0.0)
        p1 = path[i + 1] - t * (tans[i] if i < len(tans) else 0.0)
        if (p1 - p0).mag() > 1e-6:
            add_section(_ring(p0, y, z, prof), _ring(p1, y, z, prof))
        # cotovelo depois deste trecho
        if i < len(tans) and thetas[i] > 1e-6:
            d2 = dirs[i + 1].norm()
            th, T = thetas[i], tans[i]
            n1 = (d2 - t * t.dot(d2)).norm()          # pra dentro da curva, no plano da curva
            b = Vec.cross(t, n1).norm()                # normal do plano da curva (eixo de rotação)
            S = path[i + 1] - t * T                    # fim do reto = início do arco
            C = S + n1 * Rb                            # centro do arco
            k = max(1, round(segs90 * th / (math.pi / 2)))
            rings = []
            for j in range(k + 1):
                phi = th * j / k
                tj = t * math.cos(phi) + n1 * math.sin(phi)
                nj = n1 * math.cos(phi) - t * math.sin(phi)
                Pj = C - nj * Rb
                yj = brush.rotate_about(y, b, phi)
                zj = brush.rotate_about(z, b, phi)
                rings.append(_ring(Pj, yj, zj, prof))
            for ra, rb in zip(rings, rings[1:]):
                add_section(ra, rb)
    res.solids = solids
    res.detail = not hollow  # duto oco é parede (sela); tubo sólido é detalhe
    return res

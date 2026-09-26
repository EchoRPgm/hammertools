"""Curvas amostradas: arco elíptico e bezier quadrática."""
from __future__ import annotations

import math

from srctools import Vec


def arch_points(span: float, height: float, segments: int) -> list[tuple[float, float]]:
    """Pontos (x, z) de um semi-arco elíptico de x=0 a x=span com altura `height`, do pé esquerdo ao direito."""
    pts = []
    for i in range(segments + 1):
        th = math.pi - math.pi * i / segments
        pts.append((span / 2 + (span / 2) * math.cos(th), height * math.sin(th)))
    return pts


def bezier2(a: Vec, c: Vec, b: Vec, t: float) -> Vec:
    return a * (1 - t) ** 2 + c * 2 * (1 - t) * t + b * t ** 2


def bezier2_tangent(a: Vec, c: Vec, b: Vec, t: float) -> Vec:
    return (c - a) * (2 * (1 - t)) + (b - c) * (2 * t)


def left_normal_xy(d: Vec) -> Vec:
    n = Vec(-d.y, d.x, 0)
    return n.norm() if n.mag() > 1e-9 else Vec(0, 1, 0)


def rounded_path(points: list[Vec], radius: float, segs_per_90: int = 4, closed: bool = False,
                 warn: list | None = None) -> list[tuple[Vec, int | None]]:
    """Polilinha com cantos arredondados por arcos tangentes de raio `radius` (em 3D, no plano dos dois
    trechos). Retorna [(ponto, índice_do_vértice_original ou None)]; o ponto do meio de cada arco leva o
    índice do vértice (serve de âncora pra estações). Raio reduzido se não couber no trecho (com aviso)."""
    import math as _m
    n = len(points)
    if n < 2:
        return [(Vec(p), i) for i, p in enumerate(points)]
    idx = list(range(n))

    def corner(i):
        """(tangente T, dados do arco) do vértice i, ou None se reto/ponta aberta."""
        if not closed and (i == 0 or i == n - 1):
            return None
        a, p, b = points[(i - 1) % n], points[i], points[(i + 1) % n]
        d1, d2 = (p - a), (b - p)
        if d1.mag() < 1e-6 or d2.mag() < 1e-6:
            return None
        t1, t2 = d1.norm(), d2.norm()
        th = _m.acos(max(-1.0, min(1.0, t1.dot(t2))))
        if th < 1e-3:
            return None
        R = radius
        T = R * _m.tan(th / 2)
        lim = min(d1.mag(), d2.mag()) / 2
        if T > lim:
            R = lim / _m.tan(th / 2)
            T = lim
            if warn is not None:
                warn.append(f"raio da curva reduzido para {R:.0f} no vértice {i} (trecho curto)")
        return t1, t2, th, R, T

    corners = [corner(i) for i in idx]
    out: list[tuple[Vec, int | None]] = []
    for i in idx:
        c = corners[i]
        p = points[i]
        if c is None:
            out.append((Vec(p), i))
            continue
        t1, t2, th, R, T = c
        S = p - t1 * T
        n1 = (t2 - t1 * t1.dot(t2)).norm()
        C = S + n1 * R
        k = max(1, round(segs_per_90 * th / (_m.pi / 2)))
        mid = k // 2 if k % 2 == 0 else None
        for j in range(k + 1):
            phi = th * j / k
            nj = n1 * _m.cos(phi) - t1 * _m.sin(phi)
            q = C - nj * R
            out.append((q, i if (j == mid or (mid is None and j == (k + 1) // 2)) else None))
    return out

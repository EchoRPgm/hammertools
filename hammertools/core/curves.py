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

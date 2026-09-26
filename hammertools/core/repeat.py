"""Repetição ao longo de um segmento: posições de postes e trechos de painel."""
from __future__ import annotations

import math


def positions(length: float, spacing: float, include_end: bool = True, eps: float = 1e-6) -> list[float]:
    """0, spacing, 2*spacing, ... <= length; com include_end garante um ponto em `length`."""
    if spacing <= 0:
        raise ValueError("spacing deve ser > 0")
    n = int(math.floor(length / spacing + eps))
    pts = [i * spacing for i in range(n + 1)]
    if include_end and length - pts[-1] > eps:
        pts.append(length)
    return pts


def segments(length: float, spacing: float, eps: float = 1e-6) -> list[tuple[float, float]]:
    """Trechos [i*spacing, (i+1)*spacing) com o último cortado em `length`."""
    pts = positions(length, spacing, include_end=True, eps=eps)
    return [(a, b) for a, b in zip(pts, pts[1:]) if b - a > eps]

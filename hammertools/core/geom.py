"""Geometria de brushes: polígonos das faces (clipping por planos), bbox e interseção convexa (SAT)."""
from __future__ import annotations

from srctools import Vec
from srctools.vmf import Side, Solid

BIG = 65536.0


def outward(side: Side) -> tuple[Vec, Vec]:
    """(normal pra FORA, ponto no plano). srctools devolve normal() pra dentro."""
    return -side.normal(), Vec(side.planes[0])


def _clip(poly: list[Vec], n: Vec, p: Vec, eps: float = 1e-4) -> list[Vec]:
    """Mantém o lado (x - p)·n <= 0 (Sutherland-Hodgman)."""
    out: list[Vec] = []
    if not poly:
        return out
    prev = poly[-1]
    dprev = (prev - p).dot(n)
    for cur in poly:
        dcur = (cur - p).dot(n)
        if dcur <= eps:
            if dprev > eps:
                t = dprev / (dprev - dcur)
                out.append(prev + (cur - prev) * t)
            out.append(cur)
        elif dprev <= eps:
            t = dprev / (dprev - dcur)
            out.append(prev + (cur - prev) * t)
        prev, dprev = cur, dcur
    return out


def face_polys(solid: Solid) -> list[tuple[Side, list[Vec]]]:
    """Polígono (vértices) de cada face, recortado pelos planos das outras faces."""
    planes = [outward(s) for s in solid.sides]
    res = []
    for i, side in enumerate(solid.sides):
        n, p = planes[i]
        a = Vec(1, 0, 0) if abs(n.x) < 0.9 else Vec(0, 1, 0)
        u = Vec.cross(n, a).norm()
        w = Vec.cross(n, u).norm()
        poly = [p + (u + w) * BIG, p + (u - w) * BIG, p + (-u - w) * BIG, p + (-u + w) * BIG]
        for j, (n2, p2) in enumerate(planes):
            if j != i:
                poly = _clip(poly, n2, p2)
                if not poly:
                    break
        res.append((side, poly))
    return res


def vertices(solid: Solid) -> list[Vec]:
    seen, out = set(), []
    for _, poly in face_polys(solid):
        for v in poly:
            k = (round(v.x, 2), round(v.y, 2), round(v.z, 2))
            if k not in seen:
                seen.add(k)
                out.append(v)
    return out


def centroid(poly: list[Vec]) -> Vec:
    return sum(poly, Vec()) / len(poly) if poly else Vec()


def plane_key(solid: Solid) -> frozenset:
    """Chave independente de ordem/winding pra detectar brushes idênticos."""
    keys = []
    for side in solid.sides:
        n, p = outward(side)
        keys.append((round(n.x, 4), round(n.y, 4), round(n.z, 4), round(n.dot(p), 2)))
    return frozenset(keys)


def _proj(verts: list[Vec], axis: Vec) -> tuple[float, float]:
    ds = [v.dot(axis) for v in verts]
    return min(ds), max(ds)


def penetration(a_verts: list[Vec], a_axes: list[Vec], b_verts: list[Vec], b_axes: list[Vec],
                a_edges: list[Vec], b_edges: list[Vec]) -> float:
    """Profundidade mínima de sobreposição entre dois convexos (0 = separados ou só encostados).
    SAT com normais das faces e produtos vetoriais das arestas."""
    best = float("inf")
    axes = list(a_axes) + list(b_axes)
    for ea in a_edges:
        for eb in b_edges:
            c = Vec.cross(ea, eb)
            if c.mag() > 1e-6:
                axes.append(c.norm())
    for ax in axes:
        amin, amax = _proj(a_verts, ax)
        bmin, bmax = _proj(b_verts, ax)
        ov = min(amax, bmax) - max(amin, bmin)
        if ov <= 0:
            return 0.0
        best = min(best, ov)
    return best if best != float("inf") else 0.0


def edges(solid: Solid) -> list[Vec]:
    dirs = []
    for _, poly in face_polys(solid):
        for i in range(len(poly)):
            d = poly[(i + 1) % len(poly)] - poly[i]
            if d.mag() > 1e-3:
                d = d.norm()
                if not any(abs(abs(d.dot(e)) - 1) < 1e-4 for e in dirs):
                    dirs.append(d)
    return dirs

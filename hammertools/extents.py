"""Limite de coordenadas do engine: o mundo compilado tem que ficar dentro de ±16384.

O engine recusa o mapa ("Map coordinate extents are too large") quando o mundo encosta no teto: o rp_surdonoso
com paredes de fora em y = -16384 (mundo de -16384) não carregava, a versão anterior (mundo até -15824) carrega. Os
nós da árvore BSP dos dois vão a -16392, então não são eles. Aqui, só no build/: brush que passa de ±LIMIT ganha uma
face nodraw no limite (a parte de fora some; é o lado que dá pro vazio), brush todo de fora sai, e o que não dá pra
cortar (displacement) só avisa. Roda antes de cada passada do vbsp (as tampas de leak nascem depois do primeiro corte).
"""
from __future__ import annotations

from srctools import Vec
from srctools.vmf import VMF, Side

ENGINE = 16384
LIMIT = 16352            # 32u de folga do teto


def _solids(v: VMF):
    for s in list(v.brushes):
        yield None, s
    for e in list(v.entities):
        for s in list(e.solids):
            yield e, s


def _extent(s) -> tuple[Vec, Vec]:
    """Caixa pelos polígonos das faces (o get_bbox do srctools usa os pontos dos planos: brush já cortado continua
    "passando" do limite e ganharia outra face igual a cada chamada)."""
    from hammertools.core import geom
    pts = [p for _, poly in geom.face_polys(s) for p in poly]
    if not pts:
        return s.get_bbox()
    return (Vec(min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)),
            Vec(max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))


def clamp(v: VMF, limit: float = LIMIT) -> dict:
    """Corta o que passa de ±limit. Devolve {"cortados": [...], "removidos": [...], "displacement": [...],
    "entidades": [...]} com (classe, id, eixo) para o aviso."""
    out = {"cortados": [], "removidos": [], "displacement": [], "entidades": []}
    axes = ("x", "y", "z")
    for owner, s in _solids(v):
        lo, hi = _extent(s)
        cls = owner["classname"] if owner is not None else "mundo"
        if all(-limit - 0.01 <= lo[a] and hi[a] <= limit + 0.01 for a in axes):
            continue
        if any(lo[a] >= limit or hi[a] <= -limit for a in axes):
            (owner.solids.remove(s) if owner is not None else v.remove_brush(s))
            if owner is not None and not owner.solids:
                v.remove_ent(owner)
            out["removidos"].append((cls, s.id))
            continue
        if any(sd.is_disp for sd in s.sides):
            out["displacement"].append((cls, s.id))
            continue
        for a in axes:
            for sign in (-1, 1):
                if (sign < 0 and lo[a] < -limit) or (sign > 0 and hi[a] > limit):
                    n = Vec(**{a: sign})                       # normal pra fora da parte que fica
                    p = Vec(**{a: sign * limit})
                    side = Side.from_plane(v, p, -n, "tools/toolsnodraw")
                    side.reset_uv()
                    s.sides.append(side)
                    out["cortados"].append((cls, s.id, f"{'-' if sign < 0 else '+'}{a}"))
    for e in v.entities:
        if e["origin"]:
            o = Vec.from_str(e["origin"])
            if max(abs(o.x), abs(o.y), abs(o.z)) > limit:
                out["entidades"].append((e["classname"], e.id, f"{o.x:.0f} {o.y:.0f} {o.z:.0f}"))
    return out


def report(r: dict) -> list[str]:
    lines = []
    if r["cortados"]:
        lines.append(f"{len(r['cortados'])} corte(s) no limite de ±{LIMIT} (brushes: "
                     + ", ".join(sorted({str(i) for _, i, _ in r['cortados']})[:12]) + ("…" if len(r["cortados"]) > 12 else "") + ")")
    if r["removidos"]:
        lines.append(f"{len(r['removidos'])} brush(es) inteiro(s) fora do limite removido(s) do build/")
    for cls, i in r["displacement"]:
        lines.append(f"AVISO: displacement {i} ({cls}) passa do limite e não pode ser cortado: mova no mapa")
    for cls, i, o in r["entidades"]:
        lines.append(f"AVISO: {cls} {i} fora do limite em {o}: mova no mapa")
    return lines

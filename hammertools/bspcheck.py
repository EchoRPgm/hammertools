"""Checagens que comparam o BSP compilado com o VMF que o gerou.

Face fantasma: face desenhada no BSP (modelo do mundo) que não está sobre nenhuma face VISÍVEL de brush do
VMF. O vbsp cria essas faces em certos arranjos da árvore BSP (sensível a ela: tirar um piso do outro lado
do mapa pode fazer sumir ou aparecer). No jogo: parede/chão que não existe no Hammer e dá pra atravessar
(rp_surdonoso: entrada da escada em 3257 -10898 -316 com CONCRETEWALL001). Conserto validado: brush de hint
(hint nas 6 faces) cobrindo a região, que força o vbsp a cortar ali.

Ignora: displacements, água (o vbsp gera a superfície dos dois lados), modelos de entidade (coordenadas
locais), skybox. Plano do brush casa por normal (> 0,999) e distância do centro da face ao plano (< 1u),
porque o vbsp arredonda planos quase axiais.
"""
from __future__ import annotations

import struct
from collections import defaultdict
from pathlib import Path

from srctools import VMF, Vec

from hammertools.core import geom


def _read_faces(bsp_path: str | Path):
    import logging
    from srctools.bsp import BSP, BSP_LUMPS as L
    logging.getLogger("srctools").setLevel(logging.ERROR)
    b = BSP(str(bsp_path))
    F = b.get_lump(L.FACES); V = b.get_lump(L.VERTEXES); E = b.get_lump(L.EDGES); SE = b.get_lump(L.SURFEDGES)
    P = b.get_lump(L.PLANES); M = b.get_lump(L.MODELS)
    TI = b.get_lump(L.TEXINFO); TD = b.get_lump(L.TEXDATA)
    ST = b.get_lump(L.TEXDATA_STRING_TABLE); SD = b.get_lump(L.TEXDATA_STRING_DATA)
    w_first, w_num = struct.unpack_from("<ii", M, 40)

    def tex(ti: int) -> str:
        td = struct.unpack_from("<i", TI, ti * 72 + 68)[0]
        si = struct.unpack_from("<i", TD, td * 32 + 12)[0]
        off = struct.unpack_from("<i", ST, si * 4)[0]
        return SD[off:SD.index(b"\0", off)].decode("utf-8", "replace")

    for fi in range(w_first, w_first + w_num):
        pn, side, _onnode, fe, ne, ti, di = struct.unpack_from("<HBBihhh", F, fi * 56)
        if di != -1 or ti < 0:
            continue
        pts = []
        for k in range(ne):
            se = struct.unpack_from("<i", SE, (fe + k) * 4)[0]
            a, c = struct.unpack_from("<HH", E, abs(se) * 4)
            pts.append(Vec(*struct.unpack_from("<3f", V, (a if se >= 0 else c) * 12)))
        if len(pts) < 3:
            continue
        n = Vec(*struct.unpack_from("<3f", P, pn * 20))
        if side:
            n = -n
        yield fi, tex(ti), pts, n


def _on_poly(pt: Vec, poly: list[Vec], n: Vec) -> bool:
    sg = [Vec.cross(poly[(k + 1) % len(poly)] - poly[k], pt - poly[k]).dot(n) for k in range(len(poly))]
    return all(x >= -0.05 for x in sg) or all(x <= 0.05 for x in sg)


def phantom_faces(v: VMF, bsp_path: str | Path, min_area: float = 16.0) -> list[dict]:
    """Faces fantasma do BSP, da maior pra menor: {face, material, area, center, normal, points}."""
    index: dict[tuple, list] = defaultdict(list)

    def key(n: Vec, d: float) -> tuple:
        return (round(n.x, 1), round(n.y, 1), round(n.z, 1), int(d // 16))

    for s in list(v.brushes) + [s for e in v.entities for s in e.solids]:
        for side, poly in geom.face_polys(s):
            if len(poly) < 3 or side.mat.lower().startswith("tools/"):
                continue
            n, p = geom.outward(side)
            index[key(n, n.dot(p))].append((poly, n, n.dot(p)))
    out = []
    for fi, mat, pts, n in _read_faces(bsp_path):
        low = mat.lower()
        if "water" in low or low.startswith("tools/toolsskybox"):
            continue
        ctr = sum(pts, Vec()) / len(pts)
        d = n.dot(ctr)
        found = False
        for sg in (1, -1):
            nn, dd = n * sg, d * sg
            cands = [c for dk in range(-3, 4) for c in index.get((round(nn.x, 1), round(nn.y, 1), round(nn.z, 1), int(dd // 16) + dk), ())]
            if any(pn.dot(nn) > 0.999 and abs(pn.dot(ctr) - pd) < 1.0 and _on_poly(ctr, poly, pn) for poly, pn, pd in cands):
                found = True
                break
        if found:
            continue
        area = sum(Vec.cross(pts[i] - pts[0], pts[i + 1] - pts[0]).mag() for i in range(1, len(pts) - 1)) / 2
        if area >= min_area:
            out.append({"face": fi, "material": mat, "area": area, "center": ctr, "normal": n, "points": pts})
    out.sort(key=lambda f: -f["area"])
    return out


def hint_boxes(phantoms: list[dict], depth: float = 8.0) -> list[tuple[Vec, Vec]]:
    """Caixas de hint pra cobrir as faces fantasma: a face estendida `depth` unidades pra trás (contra a normal),
    no eixo dominante; faces coplanares dos dois lados viram uma caixa só."""
    boxes: list[list[Vec]] = []
    for f in phantoms:
        pts, n = f["points"], f["normal"]
        lo = Vec(min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))
        hi = Vec(max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))
        ax = max(range(3), key=lambda a: abs(n[a]))
        if n[ax] > 0:
            lo[ax] = hi[ax] - depth
        else:
            hi[ax] = lo[ax] + depth
        for a in range(3):
            if hi[a] - lo[a] < 1:
                hi[a] = lo[a] + 1
        # junta com caixa que já cobre a mesma região (as duas faces da mesma fantasma)
        for b in boxes:
            if all(lo[a] <= b[1][a] and hi[a] >= b[0][a] for a in range(3)):
                b[0] = Vec(min(b[0].x, lo.x), min(b[0].y, lo.y), min(b[0].z, lo.z))
                b[1] = Vec(max(b[1].x, hi.x), max(b[1].y, hi.y), max(b[1].z, hi.z))
                break
        else:
            boxes.append([lo, hi])
    return [(Vec(round(b[0].x), round(b[0].y), round(b[0].z)), Vec(round(b[1].x), round(b[1].y), round(b[1].z))) for b in boxes]


def add_hints(v: VMF, boxes) -> list[int]:
    """Adiciona brushes de hint (hint nas 6 faces) no mundo. Devolve os ids."""
    ids = []
    for lo, hi in boxes:
        s = v.make_prism(lo, hi, "tools/toolshint").solid
        v.add_brush(s)
        ids.append(s.id)
    return ids

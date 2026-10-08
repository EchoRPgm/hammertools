"""Checagens que comparam o BSP compilado com o VMF que o gerou.

Face fantasma: face desenhada no BSP (modelo do mundo) que não está sobre nenhuma face VISÍVEL de brush do
VMF. O vbsp cria essas faces em certos arranjos da árvore BSP (sensível a ela: tirar um piso do outro lado
do mapa pode fazer sumir ou aparecer). No jogo: parede/chão que não existe no Hammer e dá pra atravessar
(rp_surdonoso: entrada da escada em 3257 -10898 -316 com CONCRETEWALL001).

Causa (código do vbsp, src/utils/vbsp/portals.cpp, FindPortalSide): as faces do MUNDO nascem dos portais da
árvore BSP, e a textura de cada uma é a da PRIMEIRA face de brush coplanar que o vbsp acha naquela folha.
Quando brushes de mundo com texturas diferentes ficam no mesmo plano e a árvore não corta nas divisas, uma
textura cobre as outras ("textura vazada") e pode até cobrir um vão (face fantasma). Hint só muda onde a árvore
corta: funcionou numa caixa e piorou em outra. Conserto estável (validado no vbsp): os acabamentos de textura
diferente no plano viram func_detail, cujas faces saem das próprias faces do brush (sem FindPortalSide).

Ignora: displacements, água (o vbsp gera a superfície dos dois lados), modelos de entidade (coordenadas
locais), skybox. Plano do brush casa por normal (> 0,999) e distância do centro da face ao plano (< 1u),
porque o vbsp arredonda planos quase axiais.
"""
from __future__ import annotations

import re
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


def _bbox(pts):
    return (Vec(min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)),
            Vec(max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))


def _norm_mat(t: str) -> str:
    """Nome do material como no VMF: tira o prefixo maps/<mapa>/, o sufixo _x_y_z de cubemap e _wvt_patch, e o
    prefixo da cópia com lightmap do build (models/ht_prop/<mapa>/lm/)."""
    t = t.lower().replace("\\", "/")
    t = t[len("materials/"):] if t.startswith("materials/") else t     # o VMF às vezes grava com o prefixo
    m = re.match(r"maps/[^/]+/(.+?)(_-?\d+_-?\d+_-?\d+)?$", t)
    t = m.group(1) if m else t
    t = t[len("materials/"):] if t.startswith("materials/") else t     # maps/<mapa>/materials/... (cubemap)
    t = re.sub(r"_wvt_patch$", "", t)
    # cópia com lightmap que o build faz de material de modelo usado em brush (fix.autofix_build): é o mesmo material
    m = re.match(r"models/ht_prop/[^/]+/lm/(.+)$", t)
    return m.group(1) if m else t


def world_face_problems(v: VMF, bsp_path: str | Path, min_area: float = 16.0) -> list[dict]:
    """Faces do mundo desenhadas errado: 'fantasma' (sem face de brush visível no lugar) e 'vazada' (só brushes
    de MUNDO no lugar e nenhum com a textura desenhada). Faces de detail/entidade sobrepostas não contam: o
    FindPortalSide só atinge o mundo."""
    index: dict[tuple, list] = defaultdict(list)
    for e in [None] + list(v.entities):
        for s in (v.brushes if e is None else e.solids):
            for side, poly in geom.face_polys(s):
                if len(poly) < 3 or side.mat.lower().startswith("tools/"):
                    continue
                n, p = geom.outward(side)
                index[(round(n.x, 1), round(n.y, 1), round(n.z, 1))].append((poly, n, n.dot(p), _norm_mat(side.mat), s, e is None))
    out = []
    for fi, mat, pts, n in _read_faces(bsp_path):
        t = _norm_mat(mat)
        if "water" in t or t.startswith("tools/"):
            continue
        ctr = sum(pts, Vec()) / len(pts)
        hits = []
        for sg in (1, -1):
            nn = n * sg
            hits += [h for h in index.get((round(nn.x, 1), round(nn.y, 1), round(nn.z, 1)), ())
                     if h[1].dot(nn) > 0.999 and abs(h[1].dot(ctr) - h[2]) < 1.0 and _on_poly(ctr, h[0], h[1])]
        if not hits:
            kind = "fantasma"
        elif all(h[5] for h in hits) and all(h[3] != t for h in hits):
            kind = "vazada"
        else:
            continue
        area = sum(Vec.cross(pts[i] - pts[0], pts[i + 1] - pts[0]).mag() for i in range(1, len(pts) - 1)) / 2
        if area >= min_area:
            out.append({"face": fi, "material": mat, "kind": kind, "area": area, "center": ctr, "normal": n, "points": pts,
                        "expected": hits[0][3] if hits else ""})
    out.sort(key=lambda f: -f["area"])
    return out


def detail_candidates(v: VMF, problems: list[dict]) -> list[int]:
    """Brushes de MUNDO a virar func_detail pra acabar com o vazamento: nos planos dos problemas, os brushes com
    face visível na região (bbox da face problema + 1u); fica no mundo o grupo de textura dominante (maior área
    na região), os outros viram detail. rp_surdonoso: tijolo fica, faixa de concreto e batentes de metal viram
    detail (validado no vbsp)."""
    chosen: set[int] = set()
    for f in problems:
        n = f["normal"]
        lo, hi = _bbox(f["points"])
        lo, hi = lo - Vec(1, 1, 1), hi + Vec(1, 1, 1)
        area_by_mat: dict[str, float] = defaultdict(float)
        brushes_by_mat: dict[str, set] = defaultdict(set)
        for s in v.brushes:
            slo, shi = s.get_bbox()
            if not all(slo[a] <= hi[a] and shi[a] >= lo[a] for a in range(3)):
                continue
            for side, poly in geom.face_polys(s):
                if len(poly) < 3 or side.mat.lower().startswith("tools/"):
                    continue
                sn, sp = geom.outward(side)
                if abs(sn.dot(n)) < 0.999 or abs(sn.dot(f["center"]) - sn.dot(sp)) > 1.0:
                    continue
                plo, phi = _bbox(poly)
                if not all(plo[a] <= hi[a] and phi[a] >= lo[a] for a in range(3)):
                    continue
                a = sum(Vec.cross(poly[i] - poly[0], poly[i + 1] - poly[0]).mag() for i in range(1, len(poly) - 1)) / 2
                area_by_mat[side.mat.lower()] += a
                brushes_by_mat[side.mat.lower()].add(s.id)
        if len(area_by_mat) < 2:
            continue
        keep = max(area_by_mat, key=area_by_mat.get)
        for m, ids in brushes_by_mat.items():
            if m != keep:
                chosen |= ids - brushes_by_mat[keep]
    return sorted(chosen)


def to_detail(v: VMF, ids) -> int:
    """Move os brushes de mundo escolhidos pra um func_detail novo. Devolve quantos moveu."""
    from srctools.vmf import Entity
    ids = set(ids)
    sols = [s for s in v.brushes if s.id in ids]
    for s in sols:
        v.remove_brush(s)
    if sols:
        v.add_ent(Entity(v, {"classname": "func_detail"}, solids=sols))
    return len(sols)


def hint_boxes(phantoms: list[dict], depth: float = 8.0) -> list[tuple[Vec, Vec]]:
    """Caixas de hint pras faces fantasma. Par coplanar com normais opostas (o vbsp costuma gerar a fantasma dos
    dois lados): a MENOR das duas é a que cobre o vão; a caixa tem o tamanho dela e vai `depth` unidades no
    sentido da normal dela (rp_surdonoso: x 3249..3257 sobre a entrada da escada, validado no vbsp). Face sem
    par: `depth` unidades pra trás dela."""
    used: set[int] = set()
    boxes: list[tuple[Vec, Vec]] = []
    for i, f in enumerate(phantoms):
        if i in used:
            continue
        n = f["normal"]
        ax = max(range(3), key=lambda a: abs(n[a]))
        lo, hi = _bbox(f["points"])
        pair = None
        for j in range(i + 1, len(phantoms)):
            g = phantoms[j]
            if j in used or g["normal"].dot(n) > -0.999:
                continue
            glo, ghi = _bbox(g["points"])
            if abs(glo[ax] - lo[ax]) < 0.5 and all(glo[a] <= hi[a] and ghi[a] >= lo[a] for a in range(3) if a != ax):
                pair = j
                break
        if pair is not None:
            used.add(pair)
            small = min((f, phantoms[pair]), key=lambda x: x["area"])
            lo, hi = _bbox(small["points"])
            sign = 1 if small["normal"][ax] > 0 else -1
        else:
            sign = -1 if n[ax] > 0 else 1   # sem par: pra trás da face
        plane = lo[ax]
        if sign > 0:
            lo[ax], hi[ax] = plane, plane + depth
        else:
            lo[ax], hi[ax] = plane - depth, plane
        for a in range(3):
            if hi[a] - lo[a] < 1:
                hi[a] = lo[a] + 1
        used.add(i)
        boxes.append((Vec(round(lo.x), round(lo.y), round(lo.z)), Vec(round(hi.x), round(hi.y), round(hi.z))))
    return boxes


def add_hints(v: VMF, boxes) -> list[int]:
    """Adiciona brushes de hint (hint nas 6 faces) no mundo. Devolve os ids."""
    ids = []
    for lo, hi in boxes:
        s = v.make_prism(lo, hi, "tools/toolshint").solid
        v.add_brush(s)
        ids.append(s.id)
    return ids


# --------------------------------------------------------------------------- lightstyles
# Luz com estilo (piscando/pulsando: `style` 1..12; luz com nome: 32+) ganha uma página de lightmap à parte em
# cada face que ela alcança, somada no jogo com a intensidade animada. O vrad do GMod às vezes grava na página do
# estilo a luz da página base (sol/céu) em faces que nenhuma luz daquele estilo alcança: no jogo a face inteira
# fica clara e pisca, com borda reta na divisa da face. Medido no rp_surdonoso_w_tj com o mesmo BSP: vrad win64
# -fast = 154 faces, vrad normal (win64 ou 32 bits) = 1, BSP publicado = 1. A página de um estilo só pode ter luz se houver luz daquele estilo perto.
STYLE_FAR = 512.0     # nenhuma luz do estilo a menos disso da caixa da face
STYLE_MIN = 20.0      # luminância média da página (0..255 por canal)


def bad_lightstyle_faces(bsp_path: str | Path, far: float = STYLE_FAR, min_lum: float = STYLE_MIN) -> list[dict]:
    import logging
    import numpy as np
    from srctools.bsp import BSP, BSP_LUMPS as L
    logging.getLogger("srctools").setLevel(logging.ERROR)
    b = BSP(str(bsp_path))
    F = b.get_lump(L.FACES); TI = b.get_lump(L.TEXINFO)
    LT = np.frombuffer(b.get_lump(L.LIGHTING), dtype=np.uint8)
    V = np.frombuffer(b.get_lump(L.VERTEXES), dtype=np.float32).reshape(-1, 3)
    E = np.frombuffer(b.get_lump(L.EDGES), dtype=np.uint16).reshape(-1, 2)
    SE = np.frombuffer(b.get_lump(L.SURFEDGES), dtype=np.int32)
    lights: dict[int, list] = defaultdict(list)
    for e in b.ents.entities:
        st = e["style", "0"]
        if e["classname"] in ("light", "light_spot") and st.isdigit() and int(st) and e["origin", ""]:
            lights[int(st)].append(np.array(tuple(Vec.from_str(e["origin"]))))

    def lum(lo: int, n: int, k: int) -> float:
        a = LT[lo + k * n * 4: lo + (k + 1) * n * 4].reshape(-1, 4).astype(np.float64)
        if not len(a):
            return 0.0
        return float((a[:, :3] * (2.0 ** a[:, 3].astype(np.int8))[:, None]).mean())

    out = []
    for fi in range(len(F) // 56):
        styles = struct.unpack_from("<4B", F, fi * 56 + 16)
        lo = struct.unpack_from("<i", F, fi * 56 + 20)[0]
        if lo < 0 or styles[1] == 255:
            continue
        ti = struct.unpack_from("<h", F, fi * 56 + 10)[0]
        pages = 4 if ti >= 0 and struct.unpack_from("<i", TI, ti * 72 + 64)[0] & 0x800 else 1   # SURF_BUMPLIGHT
        sw, sh = struct.unpack_from("<ii", F, fi * 56 + 36)
        n = (sw + 1) * (sh + 1)
        fe, ne = struct.unpack_from("<ih", F, fi * 56 + 4)
        se = SE[fe:fe + ne]
        pts = V[np.where(se >= 0, E[np.abs(se), 0], E[np.abs(se), 1])]
        lo3, hi3 = pts.min(0), pts.max(0)
        for slot in range(1, 4):
            st = styles[slot]
            if st == 255:
                break
            page = lum(lo, n, slot * pages)
            if page < min_lum:
                continue
            dist = min((float(np.linalg.norm(np.maximum(lo3 - o, 0) + np.maximum(o - hi3, 0))) for o in lights.get(st, [])),
                       default=float("inf"))
            if dist > far:
                c = (lo3 + hi3) / 2
                out.append({"face": fi, "style": st, "page": page, "base": lum(lo, n, 0), "dist": dist,
                            "center": Vec(*map(float, c)), "size": tuple(float(x) for x in hi3 - lo3)})
    return out

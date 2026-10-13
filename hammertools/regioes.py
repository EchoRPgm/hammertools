"""Regiões do mapa (`<mapa>.regioes.json` ao lado do VMF): caixas alinhadas aos eixos com configuração de luz (o
EchoHammer bake usa com `--regioes`) e de céu (o addon de céu do EchoRP lê de dentro do BSP). A primeira região da
lista que contém o ponto vence, como nas regiões do minimapa do EchoRP; a faixa de transição mistura as vizinhas.

Aqui: ler o arquivo, aplicar a escala de lightmap de cada região nas faces do build/ (antes do vbsp) e embutir o JSON
no pakfile do BSP em `data_static/ht_regioes/<mapa>.json`."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from srctools import VMF, Vec

PAK_DIR = "data_static/ht_regioes"


def path_for(src_vmf: Path) -> Path:
    return src_vmf.with_suffix(".regioes.json")


def load(src_vmf: Path) -> dict | None:
    p = path_for(src_vmf)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and d.get("regioes") else None


def apply_lightmapscale(v: VMF, data: dict) -> int:
    """Faces que encostam numa região com "escala_lightmap" (caixa + meia faixa) ficam com a escala dela, ou a menor
    entre as regiões (na faixa vale a mais fina: resolução não se mistura, e a mais fina não cria degrau de brilho).
    Só diminui a escala (mais luxels), nunca aumenta a que o mapper escolheu. Devolve quantas faces mudaram."""
    from hammertools.core import geom
    band = float(data.get("transicao", 128))
    regs = []
    for r in data.get("regioes", []):
        esc = (r.get("luz") or {}).get("escala_lightmap")
        if not esc:
            continue
        h = float(r.get("transicao", band)) / 2
        regs.append((Vec(*r["mins"]) - Vec(h, h, h), Vec(*r["maxs"]) + Vec(h, h, h), int(esc)))
    if not regs:
        return 0
    changed = 0
    for solid in list(v.brushes) + [s for e in v.entities for s in e.solids]:
        for sd, poly in geom.face_polys(solid):
            if len(poly) < 3 or sd.mat.lower().startswith("tools/"):
                continue
            lo = Vec(min(p.x for p in poly), min(p.y for p in poly), min(p.z for p in poly))
            hi = Vec(max(p.x for p in poly), max(p.y for p in poly), max(p.z for p in poly))
            best = min((esc for mn, mx, esc in regs
                        if lo.x <= mx.x and hi.x >= mn.x and lo.y <= mx.y and hi.y >= mn.y and lo.z <= mx.z and hi.z >= mn.z),
                       default=None)
            if best is not None and best < sd.lightmap:
                sd.lightmap = best
                changed += 1
    return changed


def embed(bsp_path: Path, data: dict, map_name: str) -> str:
    """Grava o JSON no pakfile do BSP (sem compressão: o Source só lê ZIP_STORED). Devolve o caminho no pakfile."""
    from srctools.bsp import BSP
    name = f"{PAK_DIR}/{map_name.lower()}.json"
    bsp = BSP(str(bsp_path))
    pak: zipfile.ZipFile = bsp.pakfile
    blob = json.dumps(data, ensure_ascii=False).encode("utf-8")
    if name in pak.namelist():
        # ZipFile não troca arquivo no lugar: refaz o zip sem o antigo
        import io
        old = {i.filename: pak.read(i.filename) for i in pak.infolist() if i.filename != name}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
            for n, b in old.items():
                z.writestr(n, b)
        bsp.pakfile = zipfile.ZipFile(io.BytesIO(buf.getvalue()), "a", zipfile.ZIP_STORED)
        pak = bsp.pakfile
    pak.writestr(zipfile.ZipInfo(name), blob, compress_type=zipfile.ZIP_STORED)
    bsp.save()
    return name

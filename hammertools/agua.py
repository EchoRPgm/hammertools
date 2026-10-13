"""Água rasa sem reflexo planar (correção automática do ht-vbsp, no BSP; o VMF não muda).

O reflexo em tempo real da água da Source renderiza a cena de uma câmera espelhada pelo plano da água: com o olho
a h unidades acima da superfície, a câmera fica h unidades abaixo dela. Em água mais rasa que isso, a câmera cai
dentro do fundo (sólido), não enxerga a geometria perto das paredes e o fundo do reflexo vaza como um pontilhado
azul na linha d'água. O vbsp já grava a profundidade de cada água num material próprio
(materials/maps/<mapa>/..._depth_<N>.vmt, um "patch" com "$waterdepth"); nas rasas, este módulo zera o
"$reflecttint" desse material. A refração (que dá a ondulação e o fundo) continua.
"""
from __future__ import annotations

import logging
import re
import zipfile
from io import BytesIO
from pathlib import Path

# canais rasos (12-16 u): a câmera do reflexo cai no fundo; mar e lago mais fundos ficam com o reflexo do céu
RASA = 32
_DEPTH = re.compile(r"_depth_(\d+)\.vmt$", re.IGNORECASE)
_INSERT = re.compile(r'("insert"\s*\{)', re.IGNORECASE)


def patch_vmt(text: str) -> str | None:
    """O vmt com "$reflecttint" "[0 0 0]" num bloco insert (o que já existe, ou um novo no fim do patch); None se já
    tem ou não é um "patch"."""
    if "$reflecttint" in text.lower() or not text.lstrip().lower().startswith('"patch"'):
        return None
    line = '\n\t\t"$reflecttint"\t\t"[0 0 0]"'
    if _INSERT.search(text):
        return _INSERT.sub(lambda m: m.group(1) + line, text, count=1)
    end = text.rstrip().rfind("}")
    if end < 0:
        return None
    return text[:end] + '\t"insert"\n\t{' + line + '\n\t}\n' + text[end:]


def fix_shallow_water(bsp_path: Path, rasa: int = RASA) -> list[str]:
    """Zera o reflexo planar das águas com profundidade < `rasa` no pakfile do BSP. Devolve os materiais mudados."""
    from srctools.bsp import BSP
    logging.getLogger("srctools").setLevel(logging.ERROR)
    bsp = BSP(str(bsp_path))
    pak = bsp.pakfile
    changed: dict[str, bytes] = {}
    names = pak.namelist()
    # a variante _depth_N e o material base da mesma água (as faces usam um ou outro; o base tem o mesmo nome sem o
    # sufixo, numa pasta acima)
    shallow = {}
    for name in names:
        m = _DEPTH.search(name)
        if m and int(m.group(1)) < rasa:
            shallow[name] = True
            shallow[name[:m.start()].rsplit("/", 1)[-1].lower() + ".vmt"] = True
    for name in names:
        if not name.lower().endswith(".vmt") or not (name in shallow or name.rsplit("/", 1)[-1].lower() in shallow):
            continue
        new = patch_vmt(pak.read(name).decode("latin-1"))
        if new is not None:
            changed[name] = new.encode("latin-1")
    if not changed:
        return []
    # zip não troca um arquivo no lugar: monta outro com os mesmos itens (o Source só lê ZIP_STORED)
    out = zipfile.ZipFile(BytesIO(), mode="a")
    for info in pak.infolist():
        data = changed.get(info.filename, None)
        out.writestr(zipfile.ZipInfo(info.filename, info.date_time), data if data is not None else pak.read(info),
                     compress_type=zipfile.ZIP_STORED)
    out.filename = pak.filename
    bsp.pakfile = out
    tmp = bsp_path.with_name(bsp_path.name + ".tmp")
    bsp.save(str(tmp))
    tmp.replace(bsp_path)
    return sorted(changed)

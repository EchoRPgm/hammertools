"""Arquivos do projeto que vão sempre dentro do BSP (pakfile), mesmo sem o VMF citar: a pasta `embutir/` ao lado do
VMF, com os caminhos do jogo (ex.: embutir/materials/echorp/mapas/<mapa>.vtf). Serve para o que os addons leem do mapa
(minimapa, regiões) e precisa acompanhar a versão compilada. O GMod só carrega do pakfile os tipos da whitelist dele
(vtf, vmt, json, mdl...; png não)."""
from __future__ import annotations

import logging
import zipfile
from io import BytesIO
from pathlib import Path

PASTA = "embutir"


def write_pak(bsp_path: Path, files: dict[str, bytes]) -> None:
    """Grava os arquivos no pakfile do BSP (troca os que já existem com o mesmo nome, sem diferenciar maiúsculas)."""
    from srctools.bsp import BSP
    logging.getLogger("srctools").setLevel(logging.ERROR)
    bsp = BSP(str(bsp_path))
    pak = bsp.pakfile
    novos = {k.replace("\\", "/").lower(): (k.replace("\\", "/"), v) for k, v in files.items()}
    # zip não troca um arquivo no lugar: monta outro com os mesmos itens (o Source só lê ZIP_STORED)
    out = zipfile.ZipFile(BytesIO(), mode="a")
    for info in pak.infolist():
        if info.filename.lower() in novos:
            continue
        out.writestr(zipfile.ZipInfo(info.filename, info.date_time), pak.read(info), compress_type=zipfile.ZIP_STORED)
    for name, data in novos.values():
        out.writestr(zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0)), data, compress_type=zipfile.ZIP_STORED)
    out.filename = pak.filename
    bsp.pakfile = out
    tmp = bsp_path.with_name(bsp_path.name + ".tmp")
    bsp.save(str(tmp))
    tmp.replace(bsp_path)


def embed_dir(bsp_path: Path, folder: Path) -> list[str]:
    """Embute tudo de `folder` (caminhos relativos a ela). Devolve os nomes embutidos."""
    if not folder.is_dir():
        return []
    files = {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}
    if files:
        write_pak(bsp_path, files)
    return sorted(files)

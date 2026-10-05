"""`ht pack`: embute no pakfile do BSP compilado o conteúdo que o mapa usa e o GMod base não tem.

"GMod base" = os VPKs de garrysmod/ e sourceengine/ (sem addons: um addon instalado na máquina de quem compila
não existe na máquina de quem joga). Jogos montáveis (CS:S) contam como disponíveis por padrão (servidor de RP
costuma exigir); `mount=False` embute também o que vem deles.

De onde tira os arquivos: as fontes passadas (pasta de conteúdo do mapa, que o `ht content` e o `ht fix` montam,
GMAs, BSPs). Árvore de dependências igual à do `ht content` (materiais -> .vtf/.vmt incluídos, modelos -> .vvd/.vtx/
.phy + materiais do modelo, sons). Arquivos já no pakfile ficam. O Source só lê pakfile SEM compressão (ZIP_STORED).
"""
from __future__ import annotations

import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from srctools import VMF

from hammertools import content


@dataclass
class PackResult:
    added: dict[str, str] = field(default_factory=dict)   # caminho -> fonte
    kept: int = 0                                          # já estava no pakfile
    missing: set[str] = field(default_factory=set)
    bytes_added: int = 0


def base_filesystem(gamedir: Path, mount: bool = True):
    """(has, read) do GMod base: VPKs de garrysmod/ e sourceengine/, + jogos montáveis se `mount`."""
    from srctools.filesys import VPKFileSystem
    logging.getLogger("srctools").setLevel(logging.ERROR)
    gamedir = Path(gamedir)
    systems = []
    for folder in (gamedir, gamedir.parent / "sourceengine"):
        for vpk in sorted(folder.glob("*_dir.vpk")):
            try:
                systems.append(VPKFileSystem(str(vpk)))
            except Exception:  # VPK corrompido/sem permissão: ignora
                continue
    if mount:
        from hammertools.lint import _mountable_games
        for mdir in _mountable_games(gamedir):
            for vpk in sorted(Path(mdir).glob("*_dir.vpk")):
                try:
                    systems.append(VPKFileSystem(str(vpk)))
                except Exception:
                    continue

    def find(path: str):
        p = content.norm(path)
        for fs in systems:
            try:
                return fs[p]
            except (FileNotFoundError, KeyError):
                continue
        return None

    def has(path: str) -> bool:
        return find(path) is not None

    def read(path: str) -> bytes | None:
        f = find(path)
        if f is None:
            return None
        with f.open_bin() as fh:
            return fh.read()

    return has, read


def pack(v: VMF, bsp_path: Path, out: Path, sources: list[content.Source], base_has, base_read,
         dry_run: bool = False) -> PackResult:
    from srctools.bsp import BSP
    logging.getLogger("srctools").setLevel(logging.ERROR)
    bsp = BSP(str(bsp_path))
    pak = bsp.pakfile
    existing = {content.norm(n) for n in pak.namelist()}
    already = content.Source("pakfile do BSP", lambda p: content.norm(p) in existing, lambda p: pak.read(p))
    res = content.resolve(v, base_has, base_read, [already, *sources])
    out_res = PackResult(missing=set(res.missing))
    by_name = {s.name: s for s in sources}
    for path, src in sorted(res.copy.items()):
        if src == already.name:
            out_res.kept += 1
            continue
        data = by_name[src].read(path)
        out_res.added[path] = src
        out_res.bytes_added += len(data)
        if not dry_run:
            pak.writestr(zipfile.ZipInfo(path), data, compress_type=zipfile.ZIP_STORED)
    if not dry_run:
        bsp.save(str(out))
    return out_res


def pack_generated(v: VMF, bsp_path: Path, gamedir: Path, map_stem: str) -> PackResult:
    """Embute só o que o auto-prop gerou (models/ e materials/ em ht_prop/<mapa>) no próprio BSP: esses arquivos não
    existem no addon de conteúdo de ninguém. vvis e vrad preservam o pakfile, então pode rodar logo depois do vbsp."""
    import os
    from hammertools import autoprop
    gamedir = Path(gamedir)
    ap = autoprop.safe(map_stem)
    sources = [content.source_subdir(gamedir, rel) for rel in (f"models/{autoprop.MODEL_DIR}/{ap}", f"materials/models/{autoprop.MODEL_DIR}/{ap}")
               if (gamedir / rel).is_dir()]
    if not sources:
        return PackResult()
    tmp = bsp_path.with_name(bsp_path.name + ".tmp")
    r = pack(v, bsp_path, tmp, sources, lambda p: False, lambda p: None)
    os.replace(tmp, bsp_path)
    gen = f"/{autoprop.MODEL_DIR}/"
    r.missing = {m for m in r.missing if gen in "/" + m}
    return r

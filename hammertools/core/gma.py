"""Leitura de addons do Garry's Mod (.gma): índice de arquivos e leitura sob demanda.

Formato: "GMAD" | versão (u8) | steamid (u64) | timestamp (u64) | [v>1: strings de conteúdo até ""]
| nome, descrição, autor (cstr) | versão do addon (i32) | lista {nº (u32, 0 = fim), nome (cstr),
tamanho (i64), crc (u32)} | dados dos arquivos na mesma ordem.
"""
from __future__ import annotations

import struct
from pathlib import Path


def _cstr(f) -> str:
    out = bytearray()
    while True:
        b = f.read(1)
        if not b or b == b"\0":
            return out.decode("utf-8", "replace")
        out += b


class GMA:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.files: dict[str, tuple[int, int]] = {}
        with open(self.path, "rb") as f:
            if f.read(4) != b"GMAD":
                raise ValueError(f"{path}: não é GMA")
            version = f.read(1)[0]
            f.read(16)  # steamid + timestamp
            if version > 1:
                while _cstr(f):
                    pass
            _cstr(f); _cstr(f); _cstr(f)  # nome, descrição, autor
            f.read(4)
            entries = []
            while True:
                (num,) = struct.unpack("<I", f.read(4))
                if num == 0:
                    break
                name = _cstr(f)
                size, _crc = struct.unpack("<qI", f.read(12))
                entries.append((name, size))
            off = f.tell()
        for name, size in entries:
            self.files[name.lower().replace("\\", "/")] = (off, size)
            off += size

    def read(self, name: str, limit: int | None = None) -> bytes:
        off, size = self.files[name.lower()]
        with open(self.path, "rb") as f:
            f.seek(off)
            return f.read(size if limit is None else min(size, limit))


def find_addons(gamedir: Path) -> list[Path]:
    """GMAs que o jogo monta: addons/, cache/workshop/ e a pasta da Workshop do Steam."""
    out: list[Path] = []
    out += sorted((gamedir / "addons").glob("*.gma"))
    out += sorted((gamedir / "cache" / "workshop").glob("*.gma"))
    steamapps = gamedir.parent.parent.parent  # .../steamapps/common/GarrysMod/garrysmod -> .../steamapps
    ws = steamapps / "workshop" / "content" / "4000"
    if ws.is_dir():
        out += sorted(ws.glob("*/*.gma"))
    return out


class AddonIndex:
    """Índice unificado dos arquivos de todos os GMAs (primeiro encontrado vence)."""

    def __init__(self, paths: list[Path]):
        self.where: dict[str, GMA] = {}
        self.count = 0
        for p in paths:
            try:
                g = GMA(p)
            except (OSError, ValueError, struct.error):
                continue
            self.count += 1
            for name in g.files:
                self.where.setdefault(name, g)

    def __contains__(self, name: str) -> bool:
        return name.lower() in self.where

    def read(self, name: str, limit: int | None = None) -> bytes:
        return self.where[name.lower()].read(name, limit)

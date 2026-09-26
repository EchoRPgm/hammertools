"""Leitura de bounding box de modelos (.mdl) nos arquivos do jogo, pra auto-ajuste de props."""
from __future__ import annotations

import functools
import os
from pathlib import Path

from srctools import Vec


def game_dir(explicit: str | None = None) -> Path | None:
    """Pasta do jogo (a que tem gameinfo.txt): argumento, env HT_GAME, ou None."""
    for cand in (explicit, os.environ.get("HT_GAME")):
        if cand and (Path(cand) / "gameinfo.txt").exists():
            return Path(cand)
    return None


@functools.lru_cache(maxsize=None)
def _fs(gamedir: str):
    import logging
    logging.getLogger("srctools").setLevel(logging.ERROR)  # "Cannot find tools ID 211": SDK Base não montado, irrelevante
    from srctools.game import Game
    return Game(gamedir).get_filesystem()


def model_bbox(gamedir: Path | None, model: str) -> tuple[Vec, Vec] | None:
    """(mins, maxs) do hull do modelo, ou None se não der pra ler."""
    if gamedir is None:
        return None
    try:
        from srctools.mdl import Model
        fs = _fs(str(gamedir))
        m = Model(fs, fs[model])
        return Vec(m.hull_min), Vec(m.hull_max)
    except Exception:
        return None

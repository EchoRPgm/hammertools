"""`ht lightmap`: padroniza a escala de lightmap (luxels por unidade) das faces por material.

Escala menor = mais detalhe de sombra e mais memória/tempo de vrad; a mesma textura com escalas diferentes dá
emendas visíveis de luz. Regras `material=escala` (curinga permitido, primeira que casa vence) e, sem regra
pra um material, `--uniform` usa a escala mais comum que esse material já tem no mapa. Faces de ferramenta e
displacement ficam de fora. `report()` mostra os materiais com escalas misturadas.
"""
from __future__ import annotations

import fnmatch
from collections import Counter, defaultdict

from srctools import VMF


def _faces(v: VMF):
    for s in list(v.brushes) + [s for e in v.entities for s in e.solids]:
        for side in s.sides:
            m = side.mat.lower()
            if m.startswith("tools/") or side.is_disp:
                continue
            yield side, m


def report(v: VMF) -> dict[str, Counter]:
    """material -> Counter(escala -> faces), só os que têm mais de uma escala."""
    by: dict[str, Counter] = defaultdict(Counter)
    for side, m in _faces(v):
        by[m][side.lightmap] += 1
    return {m: c for m, c in by.items() if len(c) > 1}


def normalize(v: VMF, rules: list[tuple[str, int]], uniform: bool = False) -> int:
    """Aplica as regras (e, com `uniform`, a escala mais comum por material). Devolve quantas faces mudaram."""
    common: dict[str, int] = {}
    if uniform:
        by: dict[str, Counter] = defaultdict(Counter)
        for side, m in _faces(v):
            by[m][side.lightmap] += 1
        common = {m: c.most_common(1)[0][0] for m, c in by.items()}
    n = 0
    for side, m in _faces(v):
        target = next((scale for pat, scale in rules if fnmatch.fnmatchcase(m, pat.lower())), None)
        if target is None and uniform:
            target = common.get(m)
        if target is not None and side.lightmap != target:
            side.lightmap = int(target)
            n += 1
    return n

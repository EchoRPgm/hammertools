"""`ht retexture`: troca materiais por tabela (ex.: blockout `dev/dev_measure*` -> texturas finais).

Tabela: TOML `[materiais]` com `"origem" = "destino"`; origem aceita curinga (`dev/dev_measuregeneric*`) e o
primeiro que casar vence (na ordem do arquivo). Vale pra faces de brush (mundo e entidades), overlays, decals e
`material` de entidades. Tamanho/alinhamento da textura ficam como estão (o destino deve ter a mesma escala
de pixels; se não tiver, `--rescale` ajusta a escala pra manter o tamanho na parede).
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field

from srctools import VMF


@dataclass
class RetextureResult:
    faces: int = 0
    entities: int = 0
    used: dict[str, int] = field(default_factory=dict)   # regra -> quantas trocas


def load_table(path) -> list[tuple[str, str]]:
    import tomllib
    with open(path, "rb") as f:
        data = tomllib.load(f)
    table = data.get("materiais") or data.get("materials") or {}
    return [(k.lower().replace("\\", "/"), v.replace("\\", "/")) for k, v in table.items()]


def _match(mat: str, table: list[tuple[str, str]]) -> tuple[str, str] | None:
    m = mat.lower().replace("\\", "/")
    for src, dst in table:
        if fnmatch.fnmatchcase(m, src):
            return src, dst
    return None


def retexture(v: VMF, table: list[tuple[str, str]], size_of=None) -> RetextureResult:
    """`size_of(material) -> (largura, altura)` opcional: se as duas texturas tiverem tamanho conhecido e diferente,
    a escala da face é ajustada pra textura ocupar o mesmo espaço na parede."""
    res = RetextureResult()
    for s in list(v.brushes) + [s for e in v.entities for s in e.solids]:
        for side in s.sides:
            hit = _match(side.mat, table)
            if not hit:
                continue
            src, dst = hit
            if size_of:
                a, b = size_of(side.mat), size_of(dst)
                if a and b and a != b:
                    side.uaxis.scale *= a[0] / b[0]
                    side.vaxis.scale *= a[1] / b[1]
            side.mat = dst
            res.faces += 1
            res.used[src] = res.used.get(src, 0) + 1
    for e in v.entities:
        for key in ("material", "texture"):
            if e.get(key) and e["classname"] in ("info_overlay", "info_overlay_transition", "infodecal", "func_dustmotes", "env_sprite"):
                hit = _match(e[key], table)
                if hit:
                    e[key] = hit[1]
                    res.entities += 1
                    res.used[hit[0]] = res.used.get(hit[0], 0) + 1
    return res

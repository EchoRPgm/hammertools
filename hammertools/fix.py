"""`ht fix`: consertos automáticos e seguros no mapa. Grava sempre um VMF novo (o fonte não é tocado).

shaders: face de brush com material de modelo (VertexLitGeneric) não recebe lightmap e a luz sai errada (muda
com a distância). Cria uma cópia LightmappedGeneric do material com os mesmos parâmetros de textura em
materials/<prefixo>/<caminho original>.vmt e troca nas faces de brush (overlays/decals/props não mudam).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from srctools import VMF

from hammertools import lint

# parâmetros que valem igual em LightmappedGeneric; o resto (phong, rimlight, selfillum de modelo...) é de modelo
KEEP = {"$basetexture", "$bumpmap", "$normalmap", "$detail", "$detailscale", "$detailblendmode", "$detailblendfactor",
        "$surfaceprop", "$translucent", "$alphatest", "$alphatestreference", "$alpha", "$color", "$envmap", "$envmapmask",
        "$envmaptint", "$envmapcontrast", "$envmapsaturation", "$basetexturetransform", "$nocull", "$additive",
        "$selfillum", "$selfillummask", "%keywords", "$ssbump", "$basealphaenvmapmask", "$normalmapalphaenvmapmask"}


@dataclass
class FixResult:
    materials: dict[str, str] = field(default_factory=dict)   # material novo -> texto do .vmt
    faces: int = 0
    replaced: dict[str, str] = field(default_factory=dict)    # original -> novo


def _params(text: str) -> list[tuple[str, str]]:
    return [(k.lower(), val) for k, val in re.findall(r'"?(\$[A-Za-z0-9_]+|%keywords)"?\s+"?([^"\n{}]+?)"?\s*(?:\n|$)', text)]


def lightmapped_copy(text: str) -> str:
    keep = [(k, v.strip()) for k, v in _params(text) if k in KEEP]
    body = "\n".join(f'\t"{k}" "{v}"' for k, v in keep)
    return f'"LightmappedGeneric"\n{{\n{body}\n}}\n'


def fix_model_shaders(v: VMF, res: lint.Resources, prefix: str) -> FixResult:
    out = FixResult()
    cache: dict[str, str | None] = {}

    def target(mat: str) -> str | None:
        if mat not in cache:
            cache[mat] = None
            if lint._shader(res, mat) in lint.MODEL_SHADERS:
                text = (res.read(f"materials/{mat}.vmt") or b"").decode("utf-8", "replace")
                clean = re.sub(r"^materials/", "", mat)
                new = f"{prefix}/{clean}"
                out.materials[new] = lightmapped_copy(text)
                out.replaced[mat] = new
                cache[mat] = new
        return cache[mat]

    solids = list(v.brushes) + [s for e in v.entities for s in e.solids]
    for s in solids:
        for side in s.sides:
            new = target(side.mat.lower())
            if new:
                side.mat = new
                out.faces += 1
    return out


def write_materials(res: FixResult, content_dir: Path) -> list[Path]:
    written = []
    for mat, text in res.materials.items():
        p = Path(content_dir) / "materials" / f"{mat}.vmt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        written.append(p)
    return written

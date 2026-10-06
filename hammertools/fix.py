"""`ht fix`: consertos automáticos e seguros no mapa. Grava sempre um VMF novo (o fonte não é tocado).

fade: prop_static sem distância de desaparecer ganha fademindist/fademaxdist pelo tamanho do modelo (lint.FADE_TABLE);
props encaixados em parede (janela, batente) e modelos >= 512u ficam sem fade de propósito.
detail-small (opcional): brushes de mundo pequenos/finos longe do vazio viram func_detail (lint checagem perf).

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


def fix_fades(v: VMF, res: lint.Resources) -> int:
    """Aplica o fade sugerido pela checagem perf nos prop_static sem fade. Devolve quantos mudou."""
    rep = lint.run(v, res, {"perf"})
    by_id = {e.id: e for e in v.entities}
    n = 0
    for eid, fmin, fmax in rep.data.get("perf_fade", []):
        e = by_id.get(eid)
        if e is not None:
            e["fademindist"] = str(fmin)
            e["fademaxdist"] = str(fmax)
            n += 1
    return n


def fix_small_world(v: VMF, res: lint.Resources) -> int:
    """Brushes de mundo pequenos/finos longe do vazio -> func_detail (menos cortes na árvore BSP)."""
    from hammertools import bspcheck
    rep = lint.run(v, res, {"perf"})
    return bspcheck.to_detail(v, rep.data.get("perf_detail", []))


def hidden_detail_faces(v: VMF) -> list:
    """Faces de func_detail totalmente cobertas por outro brush visível (mundo ou detail): o vbsp descarta as faces do
    MUNDO escondidas por CSG, mas as de detail continuam gerando faces e vértices. Amostras espalhadas pela face
    (centro, 1/3 e 2/3 até cada vértice e perto dos cantos), 0,5u à frente de cada uma, todas dentro de outro brush."""
    from collections import defaultdict
    from hammertools.core import geom
    world = [s for s in v.brushes if lint._visible(s) and not any(x.is_disp for x in s.sides)]
    detail = [s for e in v.by_class["func_detail"] for s in e.solids]
    B = 256.0
    buckets = defaultdict(list)
    for s in world + detail:
        lo, hi = s.get_bbox()
        for bx in range(int(lo.x // B), int(hi.x // B) + 1):
            for by in range(int(lo.y // B), int(hi.y // B) + 1):
                for bz in range(int(lo.z // B), int(hi.z // B) + 1):
                    buckets[(bx, by, bz)].append(s)
    out = []
    for s in detail:
        for side, poly in geom.face_polys(s):
            if len(poly) < 3 or side.mat.lower().startswith("tools/") or side.is_disp:
                continue
            n, _ = geom.outward(side)
            ctr = geom.centroid(poly)
            samples = [ctr] + [ctr + (vx - ctr) * t for vx in poly for t in (1 / 3, 2 / 3, 0.97)]
            if all(any(o is not s and o.point_inside(q) for o in buckets.get((int(q.x // B), int(q.y // B), int(q.z // B)), ()))
                   for q in (pt + n * 0.5 for pt in samples)):
                out.append((s, side))
    return out


def nodraw_hidden_detail(v: VMF) -> int:
    """Põe nodraw nas faces de detail escondidas (não muda nada na tela; economiza faces e vértices)."""
    faces = hidden_detail_faces(v)
    for _, side in faces:
        side.mat = "tools/toolsnodraw"
    return len(faces)


def autofix_build(out: Path, gamedir: Path | None, map_stem: str, log=print) -> int:
    """Consertos seguros que o ht-vbsp aplica sozinho no build/ (o fonte não muda), para o lint não só avisar:
    material de modelo em brush vira uma cópia LightmappedGeneric (com lightmap; antes a luz mudava com a distância,
    canteiro do rp_surdonoso). As cópias vão para a pasta de materiais gerados do mapa, que o pack embute no BSP.
    Devolve quantas faces mudaram."""
    from hammertools import autoprop
    from hammertools.core import vmf as vmfio
    if gamedir is None:
        return 0
    v = vmfio.load(out)
    res = lint.Resources.from_game(str(gamedir), None, ())
    if res.read is None:
        return 0
    prefix = f"models/{autoprop.MODEL_DIR}/{autoprop.safe(map_stem)}/lm"
    r = fix_model_shaders(v, res, prefix)
    if not r.faces:
        return 0
    for mat, text in r.materials.items():
        p = Path(gamedir) / "materials" / f"{mat}.vmt"
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists() or p.read_text() != text:
            p.write_text(text)
    vmfio.save(v, out)
    log(f"ht-vbsp: conserto automático: {r.faces} face(s) de brush com material de modelo ganharam cópia "
        f"LightmappedGeneric ({', '.join(sorted(r.replaced))}): agora têm lightmap")
    return r.faces


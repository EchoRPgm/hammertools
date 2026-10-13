"""`ht fix`: consertos automáticos e seguros no mapa. Grava sempre um VMF novo (o fonte não é tocado).

fade: prop_static sem distância de desaparecer ganha fademindist/fademaxdist pelo tamanho do modelo (lint.FADE_TABLE);
props encaixados em parede (janela, batente) e modelos >= 512u ficam sem fade de propósito.
detail-small (opcional): brushes de mundo pequenos/finos longe do vazio viram func_detail (lint checagem perf).

shaders: face de brush com material de modelo (VertexLitGeneric) não recebe lightmap e a luz sai errada (muda
com a distância). Cria uma cópia LightmappedGeneric do material com os mesmos parâmetros de textura em
materials/<prefixo>/<caminho original>.vmt e troca nas faces de brush (overlays/decals/props não mudam).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from srctools import VMF, Vec

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


def brush_angles(v: VMF) -> list[tuple[str, str]]:
    """Entidade de brush com angles diferente de zero: o Hammer desenha os brushes sem girar, o jogo gira o modelo em
    volta da origin (porta de garagem do rp_surdonoso, func_door_rotating "0 90 0": de pé no meio da rua). Zera: o jogo
    fica como o Hammer mostra (e o eixo das flags do func_door_rotating fica no mundo). Devolve [(entidade, angles)]."""
    out = []
    for e in v.entities:
        if not e.solids or e["classname"].lower() in ("func_detail", "worldspawn"):
            continue
        a = e["angles"].strip()
        try:
            nonzero = a and any(abs(float(x)) > 1e-6 for x in a.split())
        except ValueError:
            nonzero = False
        if nonzero:
            out.append((f'{e["classname"]} {e["targetname"] or "#" + str(e.id)}', a))
            e["angles"] = "0 0 0"
    return out


HINT_MATS = {"tools/toolshint", "tools/toolsskip"}
HINT_SNAP = 0.5     # face de hint a menos disso de uma face estrutural paralela é encostada nela


def snap_hint_planes(v: VMF) -> list[tuple[int, float]]:
    """Brush de hint com face quase coplanar (0 < distância < 0,5 u) a uma face estrutural paralela: o vbsp corta
    fatias finíssimas entre os dois planos, descarta os portais delas e, com o mapa sem leak, o FillOutside enche de
    sólido o que nenhuma entidade alcança — o vão de porta que o hint atravessa vira parede no jogo (celas do
    rp_surdonoso, hint 0,05 u fora do alinhamento das paredes). Encosta a face do hint no plano da parede.
    Só faces retas (normal num eixo); devolve [(id do brush, deslocamento)]."""
    def axial(side):
        n = side.normal()
        for ax in range(3):
            if abs(abs(n[ax]) - 1) < 1e-6:
                return ax, side.planes[0][ax]
        return None

    structural = []
    for b in v.brushes:
        if all(sd.mat.lower() in HINT_MATS for sd in b.sides):
            continue
        lo, hi = b.get_bbox()
        planes = [a for a in (axial(sd) for sd in b.sides) if a]
        structural.append((lo, hi, planes))
    out = []
    for b in v.brushes:
        if not all(sd.mat.lower() in HINT_MATS for sd in b.sides):
            continue
        lo, hi = b.get_bbox()
        near = [pl for slo, shi, pls in structural
                if all(slo[i] <= hi[i] + 1 and shi[i] >= lo[i] - 1 for i in range(3)) for pl in pls]
        for sd in b.sides:
            a = axial(sd)
            if not a:
                continue
            ax, c = a
            best = None
            for ax2, c2 in near:
                d = c2 - c
                if ax2 == ax and 1e-4 < abs(d) < HINT_SNAP and (best is None or abs(d) < abs(best)):
                    best = d
            if best is None:
                continue
            for pt in sd.planes:
                pt[ax] += best
            # vértices de precisão (vertices_plus do Hammer++) acompanham o plano
            for pt in (getattr(sd, "strata_points", None) or []):
                pt[ax] += best
            out.append((b.id, round(best, 4)))
    return out


def open_uncovered_areaportals(v: VMF, tol: float = 1.0) -> list[str]:
    """func_areaportal ligado a uma porta (target) que, fechada, não cobre a abertura do portal: com o portal fechado
    o motor não desenha a área de trás, e pela fresta entre a porta e o vão aparece o céu (portão do rp_surdonoso:
    portão 300×144 num vão 316×160). Mapas que vazam nunca mostram isso (o vbsp desliga os areaportais); fechado o
    leak, aparece. Deixa o portal sempre aberto (sem target, StartOpen 1): a vista fica igual à do mapa vazando.
    Compara as caixas no plano do portal (o eixo fino da caixa do portal é a normal). Devolve os nomes das portas."""
    doors: dict[str, list] = {}
    for e in v.entities:
        name = (e["targetname"] or "").lower()
        if name and e.solids and e["classname"].lower().startswith(("func_door", "prop_door", "func_movelinear")):
            doors.setdefault(name, []).extend(s.get_bbox() for s in e.solids)
    out = []
    for e in v.entities:
        if e["classname"].lower() != "func_areaportal" or not e["target"] or not e.solids:
            continue
        boxes = doors.get(e["target"].lower())
        if not boxes:
            continue        # porta de modelo (prop_door) ou nome em outra entidade: não dá para medir
        plo = [min(s.get_bbox()[0][i] for s in e.solids) for i in range(3)]
        phi = [max(s.get_bbox()[1][i] for s in e.solids) for i in range(3)]
        thin = min(range(3), key=lambda i: phi[i] - plo[i])
        axes = [i for i in range(3) if i != thin]
        dlo = [min(b[0][i] for b in boxes) for i in range(3)]
        dhi = [max(b[1][i] for b in boxes) for i in range(3)]
        if all(dlo[i] <= plo[i] + tol and dhi[i] >= phi[i] - tol for i in axes):
            continue
        out.append(e["target"])
        e["target"] = ""
        e["StartOpen"] = "1"
    return out


# brushes sem nada visível: não deviam tirar pedaço da face visível em que encostam
INVISIBLE_TOOLS = {"tools/toolsinvisibleladder", "tools/toolsplayerclip", "tools/toolsnpcclip", "tools/toolsclip",
                   "tools/toolsinvisible"}


def lift_tools_off_water(v: VMF, lift: float = 1.0) -> list[int]:
    """Brush só de ferramenta invisível (ladder, clip) apoiado exatamente no topo da água: o vbsp junta o detail ao
    mundo e apaga a parte da face de água que ele cobre, e pelo buraco aparece o fundo claro (escada de mão do canal
    do rp_surdonoso: retângulo azul-claro na base). Sobe o fundo do brush `lift` u, sem encostar na água.
    World, func_detail e func_ladder (o vbsp funde os dois ao mundo; as outras entidades de brush são modelos à parte e
    não cortam faces do mundo). Devolve os ids."""
    waters = []
    for b in v.brushes:
        for sd in b.sides:
            # a normal do srctools aponta para dentro do brush: o topo tem z = -1
            if "water" in sd.mat.lower() and sd.normal().z < -0.999:
                lo, hi = b.get_bbox()
                waters.append((sd.planes[0].z, lo, hi))
    if not waters:
        return []
    # o vbsp funde ao mundo o func_detail e o func_ladder (conteúdo de escada); as outras entidades de brush são modelos
    solids = list(v.brushes) + [s for e in v.entities if e["classname"].lower() in ("func_detail", "func_ladder")
                                for s in e.solids]
    out = []
    for b in solids:
        if not all(sd.mat.lower() in INVISIBLE_TOOLS for sd in b.sides):
            continue
        lo, hi = b.get_bbox()
        if hi.z - lo.z <= lift * 2:
            continue
        for sd in b.sides:
            if sd.normal().z < 0.999:          # o fundo (normal para dentro = +z)
                continue
            z = sd.planes[0].z
            if not any(abs(z - wz) < 0.01 and wlo.x < hi.x and whi.x > lo.x and wlo.y < hi.y and whi.y > lo.y
                       for wz, wlo, whi in waters):
                continue
            for pt in sd.planes:
                pt.z += lift
            for pt in (getattr(sd, "strata_points", None) or []):
                pt.z += lift
            out.append(b.id)
    return out


ALIGN_SKIP = ("tools/", "nature/blendrock", "skybox")
ALIGN_MIN = 128.0       # lado mínimo (u) da face girada para o material ser sugerido


def _poly_area(poly) -> float:
    tot = Vec()
    for i in range(len(poly)):
        tot += Vec.cross(poly[i], poly[(i + 1) % len(poly)])
    return tot.mag() / 2


def _uv_key(sd) -> tuple:
    """Alinhamento da face: eixos, escala e deslocamento de U e V (iguais = textura contínua entre as faces)."""
    return tuple((round(a.x, 4), round(a.y, 4), round(a.z, 4), round(a.scale, 4), round(a.offset, 2))
                 for a in (sd.uaxis, sd.vaxis))


def _rot_key(sd) -> tuple:
    """Eixos e escala, sem o deslocamento."""
    return tuple((round(a.x, 4), round(a.y, 4), round(a.z, 4), round(a.scale, 4)) for a in (sd.uaxis, sd.vaxis))


def misaligned_textures(v: VMF, touch: float = 0.5) -> list[dict]:
    """Faces vizinhas no mesmo plano e com o mesmo material, mas com alinhamento de textura diferente (rotação,
    escala ou deslocamento). No jogo, cada uma mostra outro pedaço da textura e a emenda vira um retângulo de tom
    diferente com borda reta (telhado do rp_surdonoso: o mesmo concreto a 0°, 90° e 180°), no vrad e no path tracing
    igual: é a cor da textura, não a luz. Vizinhas = polígonos que se encostam por uma aresta (não só pelo canto).
    Devolve um grupo por superfície contínua com mais de um alinhamento: o alinhamento de maior área (que fica) e as
    faces que destoam. Fica de fora: displacement (alinhamento na grade), ferramentas e céu."""
    from hammertools.core import geom
    planes: dict[tuple, list] = {}
    for solid in list(v.brushes) + [s for e in v.entities for s in e.solids]:
        if any(sd.is_disp for sd in solid.sides):
            continue
        for sd, poly in geom.face_polys(solid):
            mat = sd.mat.lower().replace("\\", "/")
            if len(poly) < 3 or mat.startswith(ALIGN_SKIP):
                continue
            n, p = geom.outward(sd)
            key = (mat, round(n.x, 3), round(n.y, 3), round(n.z, 3), round(n.dot(p), 1))
            planes.setdefault(key, []).append((sd, poly, n, solid.id))
    groups = []
    for (mat, *_), faces in planes.items():
        if len(faces) < 2 or len({_uv_key(f[0]) for f in faces}) < 2:
            continue
        n = faces[0][2]
        a = Vec(1, 0, 0) if abs(n.x) < 0.9 else Vec(0, 1, 0)
        u = Vec.cross(n, a).norm()
        w = Vec.cross(n, u).norm()
        boxes = []
        for _, poly, _, _ in faces:
            us = [q.dot(u) for q in poly]
            ws = [q.dot(w) for q in poly]
            boxes.append((min(us), max(us), min(ws), max(ws)))
        parent = list(range(len(faces)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        # vizinhas pela caixa no plano (faces de brush no mesmo plano são quase sempre retângulos alinhados)
        order = sorted(range(len(faces)), key=lambda i: boxes[i][0])
        for k, i in enumerate(order):
            bi = boxes[i]
            for j in order[k + 1:]:
                bj = boxes[j]
                if bj[0] > bi[1] + touch:
                    break
                ou = min(bi[1], bj[1]) - max(bi[0], bj[0])
                ow = min(bi[3], bj[3]) - max(bi[2], bj[2])
                if ou >= -touch and ow >= -touch and max(ou, ow) > 1:
                    parent[find(i)] = find(j)
        comps: dict[int, list[int]] = {}
        for i in range(len(faces)):
            comps.setdefault(find(i), []).append(i)
        for idx in comps.values():
            area: dict[tuple, float] = {}
            for i in idx:
                area[_uv_key(faces[i][0])] = area.get(_uv_key(faces[i][0]), 0) + _poly_area(faces[i][1])
            if len(area) < 2:
                continue
            best = max(area, key=area.get)
            ref = next(faces[i][0] for i in idx if _uv_key(faces[i][0]) == best)
            odd_i = [i for i in idx if _uv_key(faces[i][0]) != best]
            center = sum((geom.centroid(faces[i][1]) for i in idx), Vec()) / len(idx)
            # sugestão: face grande (os dois lados >= ALIGN_MIN) girada ou em outra escala; deslocamento sozinho e
            # face estreita costumam ser de propósito (friso, degrau, faixa encaixada na borda)
            big = any(min(boxes[i][1] - boxes[i][0], boxes[i][3] - boxes[i][2]) >= ALIGN_MIN
                      and _rot_key(faces[i][0]) != _rot_key(ref) for i in odd_i)
            groups.append({"material": mat, "ref": ref, "odd": [faces[i][0] for i in odd_i], "faces": len(idx),
                           "alignments": len(area), "area_odd": sum(a for k, a in area.items() if k != best),
                           "center": center, "suggested": big, "solids": sorted({faces[i][3] for i in idx})})
    return groups


def align_textures(v: VMF, materials: set[str] | None = None, groups: list[dict] | None = None) -> list[dict]:
    """Copia o alinhamento de maior área para as faces que destoam em cada grupo de misaligned_textures (eixos,
    escala e deslocamento: a textura passa a ser contínua). O lightmapscale de cada face fica. materials: só esses
    (None = todos). Devolve os grupos alinhados."""
    groups = [g for g in (misaligned_textures(v) if groups is None else groups) if materials is None or g["material"] in materials]
    for g in groups:
        ref = g["ref"]
        for sd in g["odd"]:
            sd.uaxis = ref.uaxis.copy()
            sd.vaxis = ref.vaxis.copy()
    return groups


def align_config(src: Path) -> Path:
    """Decisões de alinhamento do mapa, ao lado do VMF fonte: {"alinhar": [materiais], "ignorar": [materiais]}."""
    return src.with_suffix(".align.json")


def _read_align(path: Path) -> tuple[set[str], set[str]]:
    import json
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set(), set()
    low = lambda xs: {str(x).lower().replace("\\", "/") for x in xs or []}
    return low(d.get("alinhar")), low(d.get("ignorar"))


def resolve_alignment(v: VMF, src: Path, log=print, ask: bool = False, poll: float = 0.3) -> list[dict]:
    """Alinha só os materiais que o usuário escolheu (<mapa>.align.json). Se há material sugerido (face grande
    girada) ainda sem decisão: com ask (o EchoHammer compilando, HT_ALIGN_ASK=1) grava o pedido em
    <mapa>.align.pendente.json, imprime "ht-vbsp: PAUSA alinhamento: <pedido>" e espera a resposta em
    <mapa>.align.resposta.json ({"alinhar": [...], "ignorar": [...]}), que entra nas decisões guardadas; sem ask,
    só avisa. Devolve os grupos alinhados."""
    import json
    import time
    cfg = align_config(src)
    groups = misaligned_textures(v)
    yes, no = _read_align(cfg)
    by_mat: dict[str, list[dict]] = {}
    for g in groups:
        by_mat.setdefault(g["material"], []).append(g)
    undecided = {m: gs for m, gs in by_mat.items() if m not in yes and m not in no}
    suggested = sorted((m for m, gs in undecided.items() if any(g["suggested"] for g in gs)),
                       key=lambda m: -sum(g["area_odd"] for g in undecided[m]))
    if suggested and ask:
        pend = src.with_suffix(".align.pendente.json")
        resp = src.with_suffix(".align.resposta.json")
        resp.unlink(missing_ok=True)
        others = sorted((m for m in undecided if m not in suggested), key=lambda m: -sum(g["area_odd"] for g in undecided[m]))[:60]
        items = []
        for m in suggested + others:
            gs = sorted(undecided[m], key=lambda g: -g["area_odd"])
            c = gs[0]["center"]
            items.append({"material": m, "sugerido": m in suggested, "superficies": len(gs),
                          "faces": sum(len(g["odd"]) for g in gs), "area": round(sum(g["area_odd"] for g in gs)),
                          "centro": [round(c.x, 1), round(c.y, 1), round(c.z, 1)],
                          "solids": gs[0]["solids"][:200]})
        pend.write_text(json.dumps({"mapa": src.stem, "decisoes": str(cfg), "resposta": str(resp), "materiais": items},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"ht-vbsp: {len(suggested)} material(is) com faces grandes de textura girada esperando decisão "
            f"(alinhar ou deixar): " + ", ".join(suggested[:8]))
        log(f"ht-vbsp: PAUSA alinhamento: {pend}")
        while not resp.exists():
            time.sleep(poll)
        time.sleep(poll)       # quem responde termina de gravar
        a, i = _read_align(resp)
        resp.unlink(missing_ok=True)
        pend.unlink(missing_ok=True)
        yes |= a
        no |= i - a
        cfg.write_text(json.dumps({"alinhar": sorted(yes), "ignorar": sorted(no)}, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"ht-vbsp: alinhamento decidido: {len(a)} material(is) alinhado(s), {len(i - a)} deixado(s) como estão "
            f"(guardado em {cfg.name})")
    elif suggested:
        log(f"ht-vbsp: aviso: {len(suggested)} material(is) com faces grandes de textura girada (retângulos de tom "
            f"diferente no jogo): " + ", ".join(suggested[:8]) + f". Para alinhar, liste em {cfg.name} "
            f'("alinhar": [...]) ou compile pelo F9 do EchoHammer, que pergunta')
    return align_textures(v, yes, groups) if yes else []


def autofix_build(out: Path, gamedir: Path | None, map_stem: str, log=print) -> int:
    """Consertos seguros que o ht-vbsp aplica sozinho no build/ (o fonte não muda), para o lint não só avisar:
    - material de modelo em brush vira uma cópia LightmappedGeneric (com lightmap; antes a luz mudava com a distância,
      canteiro do rp_surdonoso), na pasta de materiais gerados do mapa, que o pack embute no BSP;
    - entidade de brush com angles diferente de zero fica com 0 0 0 (o jogo girava o modelo e o Hammer não mostra);
    - face de hint quase coplanar a uma parede encosta nela (senão o vão que o hint atravessa vira parede no jogo);
    - areaportal ligado a uma porta que não cobre o vão fica sempre aberto (senão a fresta mostra o céu);
    - brush de ferramenta invisível (ladder, clip) apoiado no topo da água sobe 1 u (senão abre buraco na água);
    - faces vizinhas no mesmo plano e material com alinhamento de textura diferente ficam com o da maior área
      (senão viram retângulos de tom diferente), só nos materiais escolhidos em <mapa>.align.json; o EchoHammer
      pausa a compilação para perguntar (resolve_alignment; HT_NO_ALIGN=1 desliga).
    Devolve quantos consertos (faces + entidades)."""
    from hammertools import autoprop
    from hammertools.core import vmf as vmfio
    v = vmfio.load(out)
    total = 0
    snapped = snap_hint_planes(v)
    if snapped:
        total += len(snapped)
        log(f"ht-vbsp: conserto automático: {len(snapped)} face(s) de hint encostada(s) na parede vizinha (a menos de "
            f"{HINT_SNAP} u dela, o vbsp fechava o vão como sólido): brushes " + ", ".join(sorted({str(i) for i, _ in snapped})))
    opened = open_uncovered_areaportals(v)
    if opened:
        total += len(opened)
        log(f"ht-vbsp: conserto automático: {len(opened)} areaportal(is) sempre aberto(s): a porta ligada não cobre o vão "
            f"e, fechada, deixava ver o céu pela fresta: " + ", ".join(opened))
    lifted = lift_tools_off_water(v)
    if lifted:
        total += len(lifted)
        log(f"ht-vbsp: conserto automático: {len(lifted)} brush(es) de ferramenta invisível apoiado(s) no topo da água "
            f"subiram 1 u (o vbsp apagava a água embaixo e o buraco aparecia claro): brushes " + ", ".join(map(str, lifted)))
    turned = brush_angles(v)
    if turned:
        total += len(turned)
        log(f"ht-vbsp: conserto automático: {len(turned)} entidade(s) de brush com angles zerados (o jogo girava o modelo "
            f"e o Hammer mostra sem girar): " + ", ".join(f"{n} ({a})" for n, a in turned))
    if os.environ.get("HT_NO_ALIGN") != "1":
        aligned = resolve_alignment(v, out.parent.parent / f"{out.stem}.vmf", log, ask=os.environ.get("HT_ALIGN_ASK") == "1")
        if aligned:
            nf = sum(len(g["odd"]) for g in aligned)
            total += nf
            mats = sorted({g["material"] for g in aligned})
            log(f"ht-vbsp: conserto automático: {nf} face(s) em {len(aligned)} superfície(s) com a textura alinhada à "
                f"vizinha (mesmo plano e material com rotação/escala/deslocamento diferente viravam retângulos de tom "
                f"diferente): " + ", ".join(mats[:8]) + (f" e mais {len(mats) - 8}" if len(mats) > 8 else ""))
    res = lint.Resources.from_game(str(gamedir), None, ()) if gamedir is not None else None
    if res is not None and res.read is not None:
        prefix = f"models/{autoprop.MODEL_DIR}/{autoprop.safe(map_stem)}/lm"
        r = fix_model_shaders(v, res, prefix)
        if r.faces:
            for mat, text in r.materials.items():
                p = Path(gamedir) / "materials" / f"{mat}.vmt"
                p.parent.mkdir(parents=True, exist_ok=True)
                if not p.exists() or p.read_text() != text:
                    p.write_text(text)
            total += r.faces
            log(f"ht-vbsp: conserto automático: {r.faces} face(s) de brush com material de modelo ganharam cópia "
                f"LightmappedGeneric ({', '.join(sorted(r.replaced))}): agora têm lightmap")
    if total:
        vmfio.save(v, out)
    return total

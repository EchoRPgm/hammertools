"""Áreas onde a luz do BSP publicado não vale mais: o que mudou entre o VMF que gerou a referência e o atual.

O bake do EchoHammer (`--reusar` + `--reusar-sujo`) mantém a luz da referência em tudo, menos nestas caixas (já com
o raio: sombra e rebote mudam em volta). Contam:
  - brush novo, apagado ou alterado (caixa ou material de alguma face), do mundo ou de entidade;
  - entidade com geometria ou modelo (prop_*, func_*) nova, apagada ou movida (origin, angles, model);
  - luz nova, apagada ou movida.
Não contam mudanças só de keyvalue (cor, brilho de luz, nome, saídas): a paleta de cor nova das lâmpadas não suja o
mapa inteiro; quem quer a luz nova compila sem referência.
"""
from __future__ import annotations

import json
from pathlib import Path

from srctools import VMF, Vec

from hammertools import diffvmf

RADIUS = 256.0
LIGHTS = ("light", "light_spot", "light_dynamic", "light_environment")
# entidades com geometria que faz sombra ou recebe luz; occluder, trigger, areaportal, clip, ladder etc. não mudam a luz
LIT_CLASSES = ("func_detail", "func_brush", "func_wall", "func_wall_toggle", "func_illusionary", "func_door",
               "func_door_rotating", "func_breakable", "func_breakable_surf", "func_movelinear", "func_rotating",
               "func_tracktrain", "func_physbox", "func_lod", "func_button", "func_rot_button")
GEOMETRY_KEYS = ("origin", "angles", "model", "modelscale", "skin")


def _box(lo: Vec, hi: Vec, r: float) -> list[float]:
    return [lo.x - r, lo.y - r, lo.z - r, hi.x + r, hi.y + r, hi.z + r]


def dirty_boxes(ref: VMF, cur: VMF, radius: float = RADIUS) -> list[list[float]]:
    res = diffvmf.compare(ref, cur)
    off = res.shift or Vec()
    sa, sb = diffvmf._solids(ref), diffvmf._solids(cur)
    ea, eb = {e.id: e for e in ref.entities}, {e.id: e for e in cur.entities}
    boxes = []

    def ent_box(e, shift=Vec()):
        if e.solids:
            lo, hi = e.get_bbox()
            return lo + shift, hi + shift
        o = diffvmf._vec(e.get("origin"))
        return (o + shift, o + shift) if o is not None else None

    def lit_owner(owner: str) -> bool:
        return owner == "mundo" or owner in LIT_CLASSES

    def light_detail(d: str) -> bool:
        """Detalhe de brush alterado que muda a luz: caixa ou material visível (trocar para nodraw é esconder uma face
        que ninguém via; trocar só o dono — mundo <-> func_detail — não muda nada para a luz)."""
        if d.startswith("dono "):
            return False
        if d.startswith("face ") and d.lower().endswith("tools/toolsnodraw"):
            return False
        return True

    for c in res.changes:
        if c.category == "brush":
            s = (sb if c.kind != "-" else sa).get(c.id)
            if s is None or not lit_owner(s[1]):
                continue
            if c.kind == "~" and not any(light_detail(d) for d in c.details):
                continue
            lo, hi = diffvmf._bbox(s[0])
            if c.kind == "-":
                lo, hi = lo + off, hi + off
            if c.kind == "~" and c.id in sa:
                alo, ahi = diffvmf._bbox(sa[c.id][0])
                lo, hi = Vec.bbox(lo, hi, alo + off, ahi + off)
            boxes.append(_box(lo, hi, radius))
            continue
        e = (eb if c.kind != "-" else ea).get(c.id)
        if e is None:
            continue
        cls = e["classname"]
        if e.solids:
            continue        # entidade de brush: os brushes dela já entram um a um (e trocar de dono não muda a luz)
        geometric = cls.startswith("prop_") or cls in LIGHTS
        if not geometric:
            continue
        if c.kind == "~" and not any(d.split(":")[0] in GEOMETRY_KEYS for d in c.details):
            continue                                   # só keyvalue (cor da luz, nome...): a luz antiga fica
        b = ent_box(e, off if c.kind == "-" else Vec())
        if b is not None:
            boxes.append(_box(b[0], b[1], radius))
        if c.kind == "~" and c.id in ea and (b2 := ent_box(ea[c.id], off)) is not None:
            boxes.append(_box(b2[0], b2[1], radius))
    # oculto na referência (o vbsp não compilava) e visível agora: geometria nova para a luz
    for i, (s, owner) in sb.items():
        if i in sa and lit_owner(owner) and _hidden(sa[i][0]) and not _hidden(s):
            lo, hi = diffvmf._bbox(s)
            boxes.append(_box(lo, hi, radius))
    return boxes


def _hidden(s) -> bool:
    return not s.vis_shown or getattr(s, "hidden", False)


def write(ref_vmf: Path, cur_vmf: Path, out: Path, radius: float = RADIUS) -> int:
    from hammertools.core import vmf as vmfio
    boxes = dirty_boxes(vmfio.load(ref_vmf), vmfio.load(cur_vmf), radius)
    out.write_text(json.dumps([[round(x, 1) for x in b] for b in boxes]))
    return len(boxes)

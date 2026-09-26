"""Leitura/escrita de VMF e manuseio dos marcadores ht_*."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from srctools import VMF, Keyvalues, Vec
from srctools.vmf import Entity, Solid

MARKER_PREFIX = "ht_"
MARKER_VISGROUP = "ht_markers"
GENERATED_VISGROUP = "ht_generated"
PREVIEW_VISGROUP = "ht_preview"


def load(path: str | Path) -> VMF:
    text = Path(path).read_text(encoding="utf-8")
    return VMF.parse(Keyvalues.parse(text, str(path)), preserve_ids=True)


def save(vmf: VMF, path: str | Path) -> None:
    Path(path).write_text(vmf.export(inc_version=True), encoding="utf-8")


# srctools 2.7.0 chama Solid.export(include_groups=not _is_worldspawn), o que está invertido:
# brushes do mundo PODEM ter visgroups (brushes de entidade não). Sem isso os visgroups
# ht_generated somem ao salvar. Corrige só para solids que pertencem ao worldspawn.
_orig_solid_export = Solid.export


def _solid_export(self, buffer, ind="", disp_multiblend=True, include_groups=True):
    if not include_groups and self.map is not None and self in self.map.brushes:
        include_groups = True
    return _orig_solid_export(self, buffer, ind, disp_multiblend, include_groups)


Solid.export = _solid_export  # type: ignore[method-assign]


def markers(vmf: VMF) -> list[Entity]:
    """Todas as entidades cujo classname começa com ht_."""
    return [e for e in vmf.entities if e["classname"].startswith(MARKER_PREFIX)]


def origin(ent: Entity) -> Vec:
    return Vec.from_str(ent["origin"])


def yaw_between(a: Vec, b: Vec) -> float:
    """Yaw (graus, Hammer) do vetor A->B projetado no plano XY."""
    return math.degrees(math.atan2(b.y - a.y, b.x - a.x))


def horizontal_dist(a: Vec, b: Vec) -> float:
    return math.hypot(b.x - a.x, b.y - a.y)


def is_on_grid(value: float, grid: float = 1.0, eps: float = 1e-3) -> bool:
    q = value / grid
    return abs(q - round(q)) < eps


END_SUFFIX = "_end"


AUX_SUFFIXES = ("_end", "_node", "_ctrl")


def base_class(classname: str) -> str:
    """ht_stairs_end / ht_pipe_node / ht_stairs_curve_ctrl -> classe base (a que tem o gerador)."""
    for suf in AUX_SUFFIXES:
        if classname.endswith(suf):
            return classname[: -len(suf)]
    return classname


def role_of(ent: Entity) -> str:
    """'end' / 'node' / 'ctrl' pelas classes auxiliares; senão o keyvalue `role` (compat), default 'start'."""
    for suf in AUX_SUFFIXES:
        if ent["classname"].endswith(suf):
            return suf[1:]
    return ent.get("role", "start")


@dataclass
class Group:
    """Marcadores que compartilham um targetname: ht_stairs 'escada1' + ht_stairs_end 'escada1'."""
    name: str
    classname: str
    ents: list[Entity] = field(default_factory=list)

    def by_role(self, role: str) -> Entity | None:
        for e in self.ents:
            if role_of(e) == role:
                return e
        return None


def group_markers(ents: list[Entity]) -> dict[str, Group]:
    """Agrupa por (classname base, targetname). Marcador sem targetname vira grupo próprio."""
    groups: dict[str, Group] = {}
    for e in ents:
        base = base_class(e["classname"])
        name = e.get("targetname") or f"{base}#{e.id}"
        key = f"{base}:{name}"
        groups.setdefault(key, Group(name=name, classname=base)).ents.append(e)
    return groups


def _visgroup(vmf: VMF, name: str, color=(255, 255, 255)):
    for vg in vmf.vis_tree:
        if vg.name == name:
            return vg
    return vmf.create_visgroup(name, color)


def park_marker(vmf: VMF, ent: Entity) -> None:
    """Esconde o marcador num visgroup em vez de apagar, pra permitir regenerar."""
    vg = _visgroup(vmf, MARKER_VISGROUP, (255, 128, 0))
    ent.visgroup_ids.add(vg.id)
    ent.hidden = True
    ent.vis_shown = False


def _place_solids(vmf: VMF, vg_id: int, solids: list[Solid], detail: bool, group_name: str) -> None:
    """Solids gerados: como func_detail (um por grupo, não corta visibilidade) ou brushes de mundo (selam)."""
    if not solids:
        return
    if detail:
        e = Entity(vmf, {"classname": "func_detail"}, solids=solids)
        e.visgroup_ids.add(vg_id)
        vmf.add_ent(e)
    else:
        for s in solids:
            s.visgroup_ids.add(vg_id)
            vmf.add_brush(s)


def add_generated(vmf: VMF, group_name: str, solids: list[Solid], ents: list[Entity], detail: bool = True) -> None:
    """Adiciona ao mapa e marca num visgroup por grupo (ht_generated/<nome>)."""
    parent = _visgroup(vmf, GENERATED_VISGROUP, (0, 200, 255))
    child = None
    for vg in parent.child_groups:
        if vg.name == group_name:
            child = vg
    if child is None:
        child = vmf.create_visgroup(group_name, (0, 200, 255))
        vmf.vis_tree.remove(child)
        parent.child_groups.append(child)
    _place_solids(vmf, child.id, solids, detail, group_name)
    for e in ents:
        e.visgroup_ids.add(child.id)
        if e.map is not vmf:
            vmf.add_ent(e)


def _find_visgroup(vmf: VMF, name: str):
    for vg in vmf.vis_tree:
        if vg.name == name:
            return vg
    return None


def _all_ids(vg) -> set[int]:
    ids = {vg.id}
    for c in vg.child_groups:
        ids |= _all_ids(c)
    return ids


def strip_visgroup(vmf: VMF, name: str) -> int:
    """Remove solids, entidades e o próprio visgroup (com filhos). Retorna quantos objetos removeu."""
    vg = _find_visgroup(vmf, name)
    if vg is None:
        return 0
    ids = _all_ids(vg)
    n = 0
    for s in [s for s in vmf.brushes if s.visgroup_ids & ids]:
        vmf.remove_brush(s); n += 1
    for e in [e for e in vmf.entities if e.visgroup_ids & ids]:
        vmf.remove_ent(e); n += 1
    vmf.vis_tree.remove(vg)
    return n


def add_preview(vmf: VMF, group_name: str, solids: list[Solid], ents: list[Entity], detail: bool = True) -> None:
    """Como add_generated, mas sob ht_preview (conteúdo descartável, regenerado a cada `ht preview`)."""
    parent = _visgroup(vmf, PREVIEW_VISGROUP, (255, 0, 200))
    child = vmf.create_visgroup(group_name, (255, 0, 200))
    vmf.vis_tree.remove(child)
    parent.child_groups.append(child)
    _place_solids(vmf, child.id, solids, detail, group_name)
    for e in ents:
        e.visgroup_ids.add(child.id)
        if e.map is not vmf:
            vmf.add_ent(e)


def detail_for(group: Group, default: bool) -> bool:
    """Keyvalue `detail` do marcador principal (1/0) sobrescreve o padrão do gerador."""
    start = group.by_role("start")
    val = start.get("detail", "") if start is not None else ""
    if val in ("0", "1"):
        return val == "1"
    return default

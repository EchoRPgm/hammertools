"""Helpers pra entidades: brush entities, outputs, direções."""
from __future__ import annotations

from srctools import VMF, Vec
from srctools.vmf import Entity, Output, Solid


def brush_ent(vmf: VMF, classname: str, solids: list[Solid], **kv) -> Entity:
    """Entidade de brush (func_*, trigger_*): os solids ficam DENTRO dela, não no mundo."""
    keys = {"classname": classname}
    keys.update({k: (str(v) if not isinstance(v, Vec) else str(v)) for k, v in kv.items()})
    e = Entity(vmf, keys, solids=solids)
    vmf.add_ent(e)
    return e


def out(ent: Entity, output: str, target: str, inp: str, param: str = "", delay: float = 0.0, once: bool = False) -> None:
    ent.add_out(Output(output, target, inp, param, delay, only_once=once))


def angles_str(pitch: float = 0, yaw: float = 0, roll: float = 0) -> str:
    return f"{pitch:.3f} {yaw:.3f} {roll:.3f}"

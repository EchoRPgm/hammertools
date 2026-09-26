"""Registro de geradores: classname do marcador -> função generate(vmf, group) -> Result."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from srctools import VMF
from srctools.vmf import Entity, Solid

from hammertools.core.vmf import Group


@dataclass
class Result:
    solids: list[Solid] = field(default_factory=list)
    ents: list[Entity] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    detail: bool = True  # solids viram um func_detail por grupo (não cortam visibilidade); o marcador pode forçar com detail=0/1


Generator = Callable[[VMF, Group], Result]
REGISTRY: dict[str, Generator] = {}
SINGLE: set[str] = set()  # geradores de marcador único (sem *_end)


def register(classname: str, single: bool = False):
    def deco(fn: Generator) -> Generator:
        REGISTRY[classname] = fn
        if single:
            SINGLE.add(classname)
        return fn
    return deco


from hammertools.generators import arch, door, elevator, fence, ladder, lights, pipe, railing, spawnroom, stairs, stairs_curve  # noqa: E402,F401  (registram ht_*)

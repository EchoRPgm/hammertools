"""`ht rename`: renomeia entidades por padrão (regex) e atualiza tudo que aponta pra elas.

Referências a um nome no VMF: `targetname` da própria entidade, alvo e parâmetro de outputs, e keyvalues que
guardam nomes de outras entidades (target, parentname, TemplateNN, filtername, damagefilter, ...). Nomes com
curinga (`porta*`) em outputs não são mexidos: vão pra lista de revisão. Grava sempre um VMF novo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from srctools import VMF

# keyvalues que guardam o NOME de outra entidade
NAME_KEYS = {
    "target", "parentname", "filtername", "damagefilter", "lightingorigin", "landmark", "entitytemplate", "template",
    "measureentity", "targetentityname", "sourceentityname", "lookatname", "pointcamera", "camera", "master",
    "npctemplate", "spawntarget", "attach1", "attach2", "constraintsystem", "entity1", "entity2", "nextkey",
} | {f"template{i:02d}" for i in range(1, 17)}


@dataclass
class RenameResult:
    mapping: dict[str, str] = field(default_factory=dict)
    entities: int = 0
    keyvalues: int = 0
    outputs: int = 0
    review: list[str] = field(default_factory=list)   # outputs com curinga que pegavam nomes renomeados


def rename(v: VMF, pattern: str, replacement: str, flags: int = re.IGNORECASE) -> RenameResult:
    rx = re.compile(pattern, flags)
    res = RenameResult()
    # 1) quais nomes mudam (nome inteiro precisa casar)
    for e in v.entities:
        name = e.get("targetname")
        if name and rx.fullmatch(name):
            new = rx.sub(replacement, name, count=1)
            if new != name:
                res.mapping[name.lower()] = new
    if not res.mapping:
        return res

    def new_name(n: str) -> str | None:
        if not n or n.endswith("*"):
            return None
        return res.mapping.get(n.lower())

    # curingas (porta*) que podem pegar nomes renomeados: não dá pra adivinhar o prefixo novo, vai pra revisão
    for e in v.entities:
        for o in e.outputs:
            if o.target.endswith("*") and any(old.startswith(o.target[:-1].lower()) for old in res.mapping):
                res.review.append(f"{e['classname']} '{e.get('targetname', '')}' {o.output} -> {o.target}")

    for e in v.entities:
        name = e.get("targetname")
        if name and name.lower() in res.mapping:
            e["targetname"] = res.mapping[name.lower()]
            res.entities += 1
        for key in list(e.keys()):
            if key.lower() in NAME_KEYS and key.lower() != "targetname":
                nn = new_name(e[key])
                if nn:
                    e[key] = nn
                    res.keyvalues += 1
        for o in e.outputs:
            nn = new_name(o.target)
            if nn:
                o.target = nn
                res.outputs += 1
            # parâmetro que é nome (ex.: SetParent <nome>, AddOutput "target nome")
            if o.params:
                parts = o.params.split(" ")
                changed = False
                for i, part in enumerate(parts):
                    nn = new_name(part)
                    if nn:
                        parts[i] = nn
                        changed = True
                if changed:
                    o.params = " ".join(parts)
                    res.outputs += 1
    return res

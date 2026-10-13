"""`ht diff a.vmf b.vmf`: diferenças legíveis entre dois VMFs, pelos IDs que o Hammer mantém.

Entidades: criadas, apagadas e, nas que ficaram, keyvalues e outputs mudados. Brushes (mundo e de entidade):
criados, apagados, movidos/redimensionados (bbox) e materiais trocados por face. Mapa deslocado inteiro (a versão
do autor movida: quase todas as entidades com o mesmo delta) é avisado e as posições são comparadas descontando o
deslocamento, senão tudo apareceria como mudado.

`--markdown` dá o resumo para o GitHub (resumo do job e comentário no PR, pela Action do repositório do mapa):
contagens, um bloco recolhível por grupo (tipo da mudança + classe) e um teto de tamanho.

Pra usar com git local:
    git config difftool.ht.cmd 'ht diff "$LOCAL" "$REMOTE"'
    git difftool -t ht -- mapa.vmf
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from srctools import VMF, Vec


@dataclass
class Change:
    kind: str                      # "+", "-", "~"
    category: str                  # "entidade" ou "brush"
    id: int
    label: str
    group: str                     # classe (entidade) ou dono (brush)
    pos: str = ""
    details: list[str] = field(default_factory=list)

    def line(self) -> str:
        where = f" em {self.pos}" if self.pos else ""
        return f"{self.kind} {self.category} {self.label}{where}"


@dataclass
class Result:
    changes: list[Change]
    shift: Vec | None = None
    shift_votes: tuple[int, int] = (0, 0)   # entidades com o delta dominante, entidades comparadas

    def count(self, category: str, kind: str) -> int:
        return sum(1 for c in self.changes if c.category == category and c.kind == kind)

    @property
    def summary(self) -> str:
        parts = []
        for cat, name in (("entidade", "entidades"), ("brush", "brushes")):
            bits = [f"{k}{self.count(cat, k)}" for k in ("+", "-", "~") if self.count(cat, k)]
            if bits:
                parts.append(f"{name} " + " ".join(b.replace("-", "−") for b in bits))
        return " · ".join(parts) if parts else "sem diferenças"


def _solids(v: VMF) -> dict:
    out = {s.id: (s, "mundo") for s in v.brushes}
    for e in v.entities:
        for s in e.solids:
            out[s.id] = (s, e["classname"])
    return out


def _kv(e) -> dict:
    return {k.lower(): e[k] for k in e.keys() if k.lower() not in ("id",)}


def _outs(e) -> set:
    return {f"{o.output} -> {o.target}.{o.input}({o.params}) +{o.delay:g}s x{o.times}" for o in e.outputs}


def _vec(text: str | None) -> Vec | None:
    try:
        return Vec.from_str(text) if text else None
    except ValueError:
        return None


def _g(v: float) -> str:
    return f"{v:g}"


def _p(v: Vec) -> str:
    return f"{_g(round(v.x, 2))} {_g(round(v.y, 2))} {_g(round(v.z, 2))}"


def _bbox(s) -> tuple[Vec, Vec]:
    return s.get_bbox()


def detect_shift(a: VMF, b: VMF, min_share: float = 0.5) -> tuple[Vec | None, int, int]:
    """Delta dominante entre os objetos de mesmo id (origem das entidades, caixa dos brushes): o mapa movido
    inteiro. O delta se ≥ min_share deles o têm e ele não é zero; senão None."""
    ea = {e.id: e for e in a.entities}
    votes: Counter = Counter()
    n = 0
    for e in b.entities:
        x = ea.get(e.id)
        if x is None:
            continue
        oa, ob = _vec(x.get("origin")), _vec(e.get("origin"))
        if oa is None or ob is None:
            continue
        n += 1
        d = ob - oa
        votes[(round(d.x), round(d.y), round(d.z))] += 1
    # brushes de mesmo id também votam (o canto mínimo da caixa): entidade sem origin não fica sem voto
    sa = _solids(a)
    for i, (s, _) in _solids(b).items():
        if i in sa:
            n += 1
            d = _bbox(s)[0] - _bbox(sa[i][0])[0]
            votes[(round(d.x), round(d.y), round(d.z))] += 1
    if not votes:
        return None, 0, 0
    (dx, dy, dz), k = votes.most_common(1)[0]
    if (dx, dy, dz) == (0, 0, 0) or k < n * min_share:
        return None, k, n
    return Vec(dx, dy, dz), k, n


def compare(a: VMF, b: VMF) -> Result:
    shift, k, n = detect_shift(a, b)
    off = shift or Vec(0, 0, 0)
    out: list[Change] = []
    ea = {e.id: e for e in a.entities}
    eb = {e.id: e for e in b.entities}
    name = lambda e: f"{e['classname']}" + (f" '{e.get('targetname')}'" if e.get("targetname") else "") + f" #{e.id}"
    for i in sorted(eb.keys() - ea.keys()):
        out.append(Change("+", "entidade", i, name(eb[i]), eb[i]["classname"], eb[i].get("origin", "")))
    for i in sorted(ea.keys() - eb.keys()):
        out.append(Change("-", "entidade", i, name(ea[i]), ea[i]["classname"], ea[i].get("origin", "")))
    for i in sorted(ea.keys() & eb.keys()):
        x, y = ea[i], eb[i]
        kx, ky = _kv(x), _kv(y)
        details = []
        for key in sorted(kx.keys() | ky.keys()):
            vx, vy = kx.get(key), ky.get(key)
            if vx == vy:
                continue
            if key == "origin" and shift is not None and (ox := _vec(vx)) and (oy := _vec(vy)) and (ox + off - oy).mag() < 0.01:
                continue          # só o deslocamento do mapa inteiro
            details.append(f"{key}: {vx if vx is not None else '∅'!r} → {vy if vy is not None else '∅'!r}")
        ox, oy = _outs(x), _outs(y)
        details += [f"+ output {o}" for o in sorted(oy - ox)] + [f"− output {o}" for o in sorted(ox - oy)]
        if details:
            out.append(Change("~", "entidade", i, name(y), y["classname"], y.get("origin", ""), details))
    sa, sb = _solids(a), _solids(b)
    for i in sorted(sb.keys() - sa.keys()):
        s, owner = sb[i]
        lo, hi = _bbox(s)
        mats = ", ".join(sorted({x.mat.lower() for x in s.sides}))
        out.append(Change("+", "brush", i, f"#{i} ({mats})", owner, _p((lo + hi) / 2)))
    for i in sorted(sa.keys() - sb.keys()):
        s, owner = sa[i]
        lo, hi = _bbox(s)
        mats = ", ".join(sorted({x.mat.lower() for x in s.sides}))
        out.append(Change("-", "brush", i, f"#{i} ({mats})", owner, _p((lo + hi) / 2 + off)))
    for i in sorted(sa.keys() & sb.keys()):
        (x, ox), (y, oy) = sa[i], sb[i]
        details = []
        (alo, ahi), (blo, bhi) = _bbox(x), _bbox(y)
        if (alo + off - blo).mag() > 0.01 or (ahi + off - bhi).mag() > 0.01:
            details.append(f"caixa ({_p(alo + off)})..({_p(ahi + off)}) → ({_p(blo)})..({_p(bhi)})")
        if ox != oy:
            details.append(f"dono {ox} → {oy}")
        mx = {s.id: s.mat.lower() for s in x.sides}
        my = {s.id: s.mat.lower() for s in y.sides}
        details += [f"face {f}: {mx[f]} → {my[f]}" for f in sorted(mx.keys() & my.keys()) if mx[f] != my[f]]
        if details:
            out.append(Change("~", "brush", i, f"#{i}", oy, _p((blo + bhi) / 2), details))
    return Result(out, shift, (k, n))


def diff(a: VMF, b: VMF) -> list[str]:
    """Linhas de texto (terminal / difftool)."""
    r = compare(a, b)
    lines = []
    if r.shift is not None:
        lines.append(f"mapa deslocado {_p(r.shift)} ({r.shift_votes[0]} de {r.shift_votes[1]} objetos): posições comparadas descontando")
    for c in r.changes:
        lines.append(c.line())
        lines += [f"    {d}" for d in c.details]
    return lines


GROUP_NAMES = {"+": "entraram", "-": "saíram", "~": "mudaram"}


def markdown(r: Result, title: str, per_group: int = 40, limit: int = 60000) -> str:
    """Resumo para o GitHub: título, contagens, aviso de deslocamento e um <details> por grupo (tipo + classe),
    os maiores primeiro, com até per_group itens cada; corta antes de `limit` caracteres (o comentário do GitHub
    aceita 65536)."""
    head = [f"### {title}", "", f"**{r.summary}**", ""]
    if r.shift is not None:
        head += [f"> Mapa deslocado **{_p(r.shift)}** ({r.shift_votes[0]} de {r.shift_votes[1]} objetos com o mesmo delta): "
                 "posições comparadas já descontando o deslocamento.", ""]
    groups: dict[tuple[str, str, str], list[Change]] = {}
    for c in r.changes:
        groups.setdefault((c.category, c.kind, c.group), []).append(c)
    order = sorted(groups.items(), key=lambda kv: (kv[0][0] != "entidade", "+-~".index(kv[0][1]), -len(kv[1]), kv[0][2]))
    body: list[str] = []
    size = sum(len(x) + 1 for x in head)
    cut = 0
    for (cat, kind, group), items in order:
        sign = kind.replace("-", "−")
        what = "brush(es)" if cat == "brush" else group
        owner = f" de {group}" if cat == "brush" and group != "mundo" else (" do mundo" if cat == "brush" else "")
        block = [f"<details><summary>{sign}{len(items)} {what}{owner} — {GROUP_NAMES[kind]}</summary>", ""]
        for c in items[:per_group]:
            where = f" em `{c.pos}`" if c.pos else ""
            block.append(f"- `{c.label}`{where}")
            block += [f"  - {d}" for d in c.details[:12]]
            if len(c.details) > 12:
                block.append(f"  - … e mais {len(c.details) - 12}")
        if len(items) > per_group:
            block.append(f"- … e mais {len(items) - per_group}")
        block += ["", "</details>"]
        text = "\n".join(block)
        if size + len(text) > limit:
            cut += 1
            continue
        body.append(text)
        size += len(text) + 1
    tail = [f"", f"_{cut} grupo(s) não couberam aqui: rode `ht diff` localmente para a lista inteira._"] if cut else []
    return "\n".join(head + body + tail) + "\n"

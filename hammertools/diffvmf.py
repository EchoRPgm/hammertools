"""`ht diff a.vmf b.vmf`: diferenças legíveis entre dois VMFs, pelos IDs que o Hammer mantém.

Entidades: criadas, apagadas e, nas que ficaram, keyvalues e outputs mudados. Brushes (mundo e de entidade):
criados, apagados, movidos/redimensionados (bbox) e materiais trocados por face. Pra usar com git:
    git config difftool.ht.cmd 'ht diff "$LOCAL" "$REMOTE"'
    git difftool -t ht -- mapa.vmf
"""
from __future__ import annotations

from srctools import VMF


def _solids(v: VMF) -> dict:
    out = {s.id: (s, "mundo") for s in v.brushes}
    for e in v.entities:
        for s in e.solids:
            out[s.id] = (s, f"{e['classname']} {e.get('targetname', '') or e.id}".strip())
    return out


def _kv(e) -> dict:
    return {k.lower(): e[k] for k in e.keys() if k.lower() not in ("id",)}


def _outs(e) -> set:
    return {f"{o.output} -> {o.target}.{o.input}({o.params}) +{o.delay:g}s x{o.times}" for o in e.outputs}


def _fmt_box(s) -> str:
    lo, hi = s.get_bbox()
    return f"({lo.x:g} {lo.y:g} {lo.z:g})..({hi.x:g} {hi.y:g} {hi.z:g})"


def diff(a: VMF, b: VMF) -> list[str]:
    lines = []
    ea = {e.id: e for e in a.entities}
    eb = {e.id: e for e in b.entities}
    label = lambda e: f"{e['classname']} '{e.get('targetname', '')}' #{e.id}"
    for i in sorted(eb.keys() - ea.keys()):
        lines.append(f"+ entidade {label(eb[i])} em {eb[i].get('origin', '-')}")
    for i in sorted(ea.keys() - eb.keys()):
        lines.append(f"- entidade {label(ea[i])} em {ea[i].get('origin', '-')}")
    for i in sorted(ea.keys() & eb.keys()):
        x, y = ea[i], eb[i]
        kx, ky = _kv(x), _kv(y)
        changes = [f"{k}: {kx.get(k, '∅')!r} -> {ky.get(k, '∅')!r}" for k in sorted(kx.keys() | ky.keys()) if kx.get(k) != ky.get(k)]
        ox, oy = _outs(x), _outs(y)
        changes += [f"+ output {o}" for o in sorted(oy - ox)] + [f"- output {o}" for o in sorted(ox - oy)]
        if changes:
            lines.append(f"~ entidade {label(y)}")
            lines += [f"    {c}" for c in changes]
    sa, sb = _solids(a), _solids(b)
    for i in sorted(sb.keys() - sa.keys()):
        s, owner = sb[i]
        lines.append(f"+ brush {i} ({owner}) {_fmt_box(s)} {sorted({x.mat.lower() for x in s.sides})}")
    for i in sorted(sa.keys() - sb.keys()):
        s, owner = sa[i]
        lines.append(f"- brush {i} ({owner}) {_fmt_box(s)}")
    for i in sorted(sa.keys() & sb.keys()):
        (x, ox), (y, oy) = sa[i], sb[i]
        changes = []
        if _fmt_box(x) != _fmt_box(y):
            changes.append(f"caixa {_fmt_box(x)} -> {_fmt_box(y)}")
        if ox != oy:
            changes.append(f"dono {ox} -> {oy}")
        mx = {s.id: s.mat.lower() for s in x.sides}
        my = {s.id: s.mat.lower() for s in y.sides}
        changes += [f"face {k}: {mx[k]} -> {my[k]}" for k in sorted(mx.keys() & my.keys()) if mx[k] != my[k]]
        if changes:
            lines.append(f"~ brush {i} ({oy})")
            lines += [f"    {c}" for c in changes]
    return lines

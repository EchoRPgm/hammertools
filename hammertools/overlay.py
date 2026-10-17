"""`ht overlay a.vmf b.vmf`: sobrepõe duas versões de um mapa por âncoras e mostra o que difere.

Âncoras = objetos com o mesmo id nas duas versões (o Hammer mantém os ids): cada um dá um deslocamento A -> B (origem
da entidade, canto mínimo do brush). O deslocamento dominante é a transformação (o autor move o mapa inteiro: no
rp_surdonoso, 255 -> 444 foi x -1024, y +3462 em 93% das âncoras); os outros deslocamentos com muitas âncoras
juntas viram aviso (região movida à parte).

Com A convertido para as coordenadas de B, cada objeto é:
  igual       mesmo id e mesma posição/caixa (tolerância `tol`);
  igual (id)  ids diferentes, mesma caixa e mesmos materiais (o autor recriou a peça);
  mudou       mesmo id, posição ou caixa diferente;
  só A / só B o resto.
As diferenças são agrupadas em células (padrão 512u) com um setpos cada; `--png` desenha a vista de cima com B em
cinza, só A em vermelho, só B em azul e mudou em laranja (`--box`/`--em` recorta).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from srctools import VMF, Vec


@dataclass
class Obj:
    key: tuple                 # ("solid"|"ent", id)
    kind: str                  # classname ou "brush"
    lo: Vec
    hi: Vec
    mats: frozenset = frozenset()
    owner: str = ""


@dataclass
class Result:
    shift: Vec
    anchors: int
    agree: int
    others: list = field(default_factory=list)          # (delta, n, lo, hi) em coordenadas de A
    status: dict = field(default_factory=dict)          # key de A ou B -> status
    a: dict = field(default_factory=dict)
    b: dict = field(default_factory=dict)

    def count(self, s: str) -> int:
        return sum(1 for v in self.status.values() if v == s)


def objects(v: VMF) -> dict:
    out = {}
    for s in v.brushes:
        lo, hi = s.get_bbox()
        out[("solid", s.id)] = Obj(("solid", s.id), "brush", lo, hi, frozenset(sd.mat.lower() for sd in s.sides), "mundo")
    for e in v.entities:
        cls = e["classname"]
        if e.solids:
            for s in e.solids:
                lo, hi = s.get_bbox()
                out[("solid", s.id)] = Obj(("solid", s.id), cls, lo, hi, frozenset(sd.mat.lower() for sd in s.sides), cls)
        if e.get("origin"):
            try:
                o = Vec.from_str(e["origin"])
            except ValueError:
                continue
            out[("ent", e.id)] = Obj(("ent", e.id), cls, o, o, frozenset({e.get("model", "").lower()}) - {""}, cls)
        elif e.solids:
            lo, hi = e.get_bbox()
            out[("ent", e.id)] = Obj(("ent", e.id), cls, lo, hi, frozenset(), cls)
    return out


def _r(v: Vec) -> tuple:
    return round(v.x), round(v.y), round(v.z)


def compare(a: VMF, b: VMF, tol: float = 1.0, min_region: int = 15) -> Result:
    A, B = objects(a), objects(b)
    votes: Counter = Counter()
    where: dict = defaultdict(list)
    for k in A.keys() & B.keys():
        d = _r(B[k].lo - A[k].lo)
        votes[d] += 1
        where[d].append(A[k].lo)
    if not votes:
        shift, n = Vec(), 0
    else:
        d, n = votes.most_common(1)[0]
        shift = Vec(*d)
    res = Result(shift, sum(votes.values()), n, a=A, b=B)
    # outros deslocamentos com âncoras juntas (região movida à parte, não edição pontual)
    for d, m in votes.most_common(12)[1:]:
        if m < min_region:
            continue
        ps = where[d]
        lo = Vec(min(p.x for p in ps), min(p.y for p in ps), min(p.z for p in ps))
        hi = Vec(max(p.x for p in ps), max(p.y for p in ps), max(p.z for p in ps))
        res.others.append((Vec(*d), m, lo, hi))
    st = res.status
    for k in A.keys() & B.keys():
        x, y = A[k], B[k]
        same = (x.lo + shift - y.lo).mag() <= tol and (x.hi + shift - y.hi).mag() <= tol
        st[("A",) + k] = st[("B",) + k] = "igual" if same else "mudou"
    # ids novos com a mesma peça: caixa (convertida) e materiais iguais
    only_b = defaultdict(list)
    for k in B.keys() - A.keys():
        y = B[k]
        only_b[(y.kind, _r(y.lo), _r(y.hi), y.mats)].append(k)
    for k in A.keys() - B.keys():
        x = A[k]
        sig = (x.kind, _r(x.lo + shift), _r(x.hi + shift), x.mats)
        if only_b.get(sig):
            kb = only_b[sig].pop()
            st[("A",) + k] = st[("B",) + kb] = "igual (id)"
        else:
            st[("A",) + k] = "só A"
    for k in B.keys() - A.keys():
        st.setdefault(("B",) + k, "só B")
    return res


def regions(res: Result, cell: float = 512.0) -> list:
    """Células com diferença (coordenadas de B): [(x, y, {status: n}, z_min, z_max, classes)] das maiores para as menores."""
    cells: dict = defaultdict(lambda: [Counter(), [], Counter()])
    for key, s in res.status.items():
        if s in ("igual", "igual (id)"):
            continue
        side, k = key[0], key[1:]
        o = res.a[k] if side == "A" else res.b[k]
        c = (o.lo + o.hi) / 2 + (res.shift if side == "A" else Vec())
        cl = cells[(int(c.x // cell), int(c.y // cell))]
        cl[0][s] += 1
        cl[1].append(c.z)
        cl[2][o.kind] += 1
    out = []
    for (cx, cy), (cnt, zs, kinds) in cells.items():
        out.append(((cx + 0.5) * cell, (cy + 0.5) * cell, dict(cnt), min(zs), max(zs), kinds.most_common(3)))
    return sorted(out, key=lambda r: -sum(r[2].values()))


COLORS = {"igual": (150, 150, 150), "igual (id)": (150, 150, 150), "só A": (230, 60, 50), "só B": (60, 110, 240),
          "mudou": (245, 160, 30)}


def render(res: Result, path, box=None, scale: float = 0.0, zmin=None, zmax=None, size: int = 2400) -> tuple:
    """PNG de cima, em coordenadas de B. box = (x0, y0, x1, y1); sem ela, a união das duas versões."""
    from PIL import Image, ImageDraw
    items = []
    for key, s in res.status.items():
        side, k = key[0], key[1:]
        if s in ("igual", "igual (id)") and side == "A":
            continue
        o = res.a[k] if side == "A" else res.b[k]
        lo, hi = (o.lo + res.shift, o.hi + res.shift) if side == "A" else (o.lo, o.hi)
        if zmin is not None and hi.z < zmin or zmax is not None and lo.z > zmax:
            continue
        if (hi - lo).mag() > 20000:        # casco de skybox do mapa inteiro: esconde o resto
            continue
        items.append((s, lo, hi, o.kind))
    if box is None:
        xs = [p for _, lo, hi, _ in items for p in (lo.x, hi.x)]
        ys = [p for _, lo, hi, _ in items for p in (lo.y, hi.y)]
        box = (min(xs), min(ys), max(xs), max(ys))
    x0, y0, x1, y1 = box
    upp = scale or max(x1 - x0, y1 - y0) / size
    w, h = max(1, int((x1 - x0) / upp)), max(1, int((y1 - y0) / upp))
    im = Image.new("RGB", (w, h), (18, 18, 22))
    dr = ImageDraw.Draw(im, "RGBA")
    P = lambda x, y: ((x - x0) / upp, (y1 - y) / upp)
    order = {"igual": 0, "igual (id)": 0, "mudou": 1, "só B": 2, "só A": 3}
    for s, lo, hi, kind in sorted(items, key=lambda i: order[i[0]]):
        if hi.x < x0 or lo.x > x1 or hi.y < y0 or lo.y > y1:
            continue
        c = COLORS[s]
        a, b = P(lo.x, hi.y), P(hi.x, lo.y)
        if (b[0] - a[0]) < 2 and (b[1] - a[1]) < 2:
            dr.ellipse([a[0] - 2, a[1] - 2, a[0] + 2, a[1] + 2], fill=c + (230,))
        else:
            fill = 40 if s in ("igual", "igual (id)") else 110
            dr.rectangle([a, b], fill=c + (fill,), outline=c + (220,))
    # grade de 1024u com rótulos
    g = 1024
    for gx in range(int(x0 // g) * g, int(x1) + g, g):
        dr.line([P(gx, y0), P(gx, y1)], fill=(255, 255, 255, 30))
        dr.text((P(gx, y1)[0] + 2, 2), str(gx), fill=(200, 200, 200, 160))
    for gy in range(int(y0 // g) * g, int(y1) + g, g):
        dr.line([P(x0, gy), P(x1, gy)], fill=(255, 255, 255, 30))
        dr.text((2, P(x0, gy)[1] + 2), str(gy), fill=(200, 200, 200, 160))
    ly = h - 16 * 5 - 8
    for i, (name, c) in enumerate((("igual", COLORS["igual"]), ("mudou", COLORS["mudou"]), ("só A", COLORS["só A"]), ("só B", COLORS["só B"]))):
        dr.rectangle([8, ly + i * 16, 20, ly + i * 16 + 12], fill=c + (255,))
        dr.text((26, ly + i * 16), name, fill=(230, 230, 230, 255))
    im.save(path)
    return w, h, upp


def report(res: Result, top: int = 20) -> list[str]:
    s = res.shift
    lines = [f"transformação A -> B: x {s.x:+g}, y {s.y:+g}, z {s.z:+g} ({res.agree} de {res.anchors} âncoras)"]
    for d, n, lo, hi in res.others:
        lines.append(f"  outro deslocamento {d.x:+g} {d.y:+g} {d.z:+g}: {n} âncoras em A x {lo.x:.0f}..{hi.x:.0f} y {lo.y:.0f}..{hi.y:.0f}")
    lines.append("objetos: " + ", ".join(f"{k} {res.count(k)}" for k in ("igual", "igual (id)", "mudou", "só A", "só B")))
    lines.append("regiões com diferença (coordenadas de B):")
    for x, y, cnt, z0, z1, kinds in regions(res)[:top]:
        lines.append(f"  setpos {x:.0f} {y:.0f} {(z0 + z1) / 2:.0f}  " + ", ".join(f"{k} {v}" for k, v in sorted(cnt.items()))
                     + f"  z {z0:.0f}..{z1:.0f}  ({', '.join(f'{c} {n}' for c, n in kinds)})")
    return lines

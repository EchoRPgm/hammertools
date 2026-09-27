"""Relatório HTML geral do `ht lint` (`--html`).

Abas: Painel (prioridades + pontos quentes somando todas as checagens) · Texturas · Texturas por região ·
Modelos · T-junctions · Leak · Geometria (nodraw, sobreposições, duplicados, grid) · Entidades (I/O e
marcadores). Cada localização tem botão de copiar `setpos` (console do jogo) e `xyz` (Hammer: Ctrl+Shift+G).

Áreas: o mapa é dividido em blocos fixos (padrão 1024u), numerados pelo total de problemas. Toda localização
carrega `data-area`; a barra de cima tem um filtro opcional por área e "Agrupar por área", que valem pra
todas as abas (JS). Os blocos são os mesmos do "Onde concentrar esforço" do painel.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from html import escape
from pathlib import Path

from srctools import Vec

from hammertools import lint as L

# ordem de prioridade no painel: o que quebra o mapa primeiro
PRIORITY = [
    ("leak", "erro", "Leak: o mapa vaza pro vazio", "Sem selo, o vbsp não gera VIS e a luz sai errada. Siga o caminho (pointfile) e tape o buraco."),
    ("markers", "erro", "Marcadores ht_* incompletos", "Falta o par (início/fim) de um gerador: a peça não é gerada."),
    ("outputs", "erro", "Outputs órfãos", "I/O mirando nome que não existe: o evento não acontece no jogo."),
    ("textures", "erro", "Texturas faltando", "Aparecem como xadrez rosa e preto. Instale o conteúdo (ht content) ou troque o material."),
    ("models", "erro", "Modelos faltando", "Aparecem como ERROR vermelho. Instale o conteúdo ou troque o prop."),
    ("tjunctions", "aviso", "T-junctions", "Cada vértice no meio da aresta de outra face obriga o vbsp a triangular a face; acima de 65536 índices a compilação para. Junte os blocos fatiados das regiões abaixo."),
    ("models", "aviso", "prop_static com modelo dinâmico", "O modelo não é static prop: vira prop_dynamic ou some. Troque por prop_dynamic."),
    ("nodraw", "aviso", "Nodraw à vista", "Face invisível virada pra área jogável: vira um buraco pro céu/vazio."),
    ("overlaps", "aviso", "Sobreposição com detail/entidade", "Face escondida não é cortada: desperdício e possível z-fighting."),
    ("duplicates", "aviso", "Brushes duplicados", "Dois brushes idênticos no mesmo lugar: z-fighting. Apague um."),
    ("grid", "aviso", "Fora do grid", "Vértices fracionários: risco de microfrestas e t-junctions."),
]


AREA = 1024.0  # tamanho do bloco de área; write() ajusta


def _akey(p: Vec) -> str:
    return f"{int(p.x // AREA)}_{int(p.y // AREA)}_{int(p.z // AREA)}"


def _coord(p: Vec) -> str:
    return f"{p.x:.0f} {p.y:.0f} {p.z:.0f}"


def _loc(p: Vec, d: str = "") -> str:
    return (f'<li data-area="{_akey(p)}"><code>{escape(_coord(p))}</code>{f"<span class=d>{escape(d)}</span>" if d else ""}'
            f'<button data-copy="setpos {escape(_coord(p + Vec(0, 0, 64)))}" title="copiar setpos (64u acima)">setpos</button>'
            f'<button data-copy="{escape(_coord(p))}" title="copiar coordenadas (Hammer: Ctrl+Shift+G)">xyz</button></li>')


def _table(head: list[str], rows: list[str], empty: str) -> str:
    if not rows:
        return f'<p class="ok">{escape(empty)}</p>'
    th = "".join(f'<th{" class=n" if h.startswith("#") or h in ("Usos", "Ocorr.", "Índices", "Vértices") else ""}>{escape(h.lstrip("#"))}</th>' for h in head)
    return f'<div class="tablewrap"><table><thead><tr>{th}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def _not_run(check: str, rep: L.Report) -> str | None:
    if check in rep.skipped:
        return f'<p class="warn">Checagem pulada: {escape(rep.skipped[check])}</p>'
    if check not in rep.ran:
        return f'<p class="sub">Não rodou (use <code>--only {check}</code> ou tire do <code>--skip</code>).</p>'
    return None


def hotspots(items, cell: float = 512.0) -> list[dict]:
    """Densidade por célula fixa de grade (não encadeia como o agrupamento por proximidade, que num mapa denso
    vira uma região só). Mesmo formato de lint.cluster_locations: count, center, lo, hi, materials, examples."""
    from collections import Counter
    cells: dict[tuple, list] = defaultdict(list)
    for name, p, d in items:
        cells[(int(p.x // cell), int(p.y // cell), int(p.z // cell))].append((name, p, d))
    out = []
    for lst in cells.values():
        pts = [p for _, p, _ in lst]
        center = sum(pts, Vec()) / len(pts)
        lo = Vec(min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))
        hi = Vec(max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))
        ex = sorted(lst, key=lambda t: (t[1] - center).mag())[: L.MAX_EXAMPLES]
        out.append({"count": len(lst), "center": center, "lo": lo, "hi": hi,
                    "materials": Counter(n for n, _, _ in lst).most_common(), "examples": [(p, d) for _, p, d in ex]})
    out.sort(key=lambda g: -g["count"])
    return out


# --------------------------------------------------------------------------- abas
def _tab_textures(rep: L.Report, radius: float) -> tuple[str, str, int, int]:
    items = sorted((i for i in rep.issues if i.check == "textures"), key=lambda i: (-i.count, i.name))
    folders = defaultdict(lambda: [0, 0])
    for i in items:
        folders[i.group][0] += 1
        folders[i.group][1] += i.count
    rows = []
    for i in items:
        more = f'<li class="more">+{i.count - len(i.examples)} uso(s)</li>' if i.count > len(i.examples) else ""
        rows.append(f'<tr data-folder="{escape(i.group)}" data-name="{escape(i.name)}"><td class="mat"><code>{escape(i.name)}</code></td>'
                    f'<td class="folder">{escape(i.group)}</td><td class="n">{i.count}</td>'
                    f'<td><ul>{"".join(_loc(p, d) for p, d in i.examples)}{more}</ul></td></tr>')
    chips = "".join(f'<button class="chip" data-folder="{escape(f)}">{escape(f)} <b>{n}</b></button>'
                    for f, (n, u) in sorted(folders.items(), key=lambda kv: -kv[1][1]))
    nr = _not_run("textures", rep)
    tex = nr or (f'<div class="chips">{chips}</div>' + _table(["Material", "Pasta", "Usos", f"Onde (até {L.MAX_EXAMPLES})"], rows, "Nenhuma textura faltando."))
    clusters = L.cluster_locations([(i.name, p, d) for i in items for p, d in i.locations], radius)
    crow = []
    for k, g in enumerate(clusters, 1):
        size = g["hi"] - g["lo"]
        mats = "".join(f'<li><code>{escape(m)}</code><span class="d">{c}×</span></li>' for m, c in g["materials"][:8])
        if len(g["materials"]) > 8:
            mats += f'<li class="more">+{len(g["materials"]) - 8} material(is)</li>'
        more = f'<li class="more">+{g["count"] - len(g["examples"])} ocorrência(s)</li>' if g["count"] > len(g["examples"]) else ""
        crow.append(f'<tr data-name="{escape(" ".join(m for m, _ in g["materials"]))}" data-folder="" data-areas="{_akey(g["center"])}"><td class="n">{k}</td>'
                    f'<td><code>{escape(_coord(g["center"]))}</code><div class="d">área ~{size.x:.0f}×{size.y:.0f}×{size.z:.0f}u</div>'
                    f'<button class="go" data-copy="setpos {escape(_coord(g["center"] + Vec(0, 0, 64)))}">setpos no centro</button></td>'
                    f'<td class="n">{g["count"]}</td><td><ul>{mats}</ul></td><td><ul>{"".join(_loc(p, d) for p, d in g["examples"])}{more}</ul></td></tr>')
    reg = nr or (f'<p class="sub">Ocorrências a até {radius:.0f}u umas das outras viram uma região, mesmo com materiais diferentes.</p>'
                 + _table(["#", "Centro", "Ocorr.", "Materiais", f"Onde (até {L.MAX_EXAMPLES})"], crow, "Nenhuma ocorrência."))
    return tex, reg, len(items), len(clusters)


def _tab_models(rep: L.Report) -> tuple[str, int]:
    nr = _not_run("models", rep)
    if nr:
        return nr, 0
    by = defaultdict(list)
    for i in rep.issues:
        if i.check == "models":
            by[(i.level, i.name or i.msg)].append(i)
    rows = []
    for (level, name), lst in sorted(by.items(), key=lambda kv: (kv[0][0] != "erro", -len(kv[1]), kv[0][1])):
        ex = [(i.pos, "") for i in lst if i.pos is not None][: L.MAX_EXAMPLES]
        more = f'<li class="more">+{len(lst) - len(ex)} prop(s)</li>' if len(lst) > len(ex) else ""
        what = "faltando" if level == "erro" else "não é static prop"
        rows.append(f'<tr data-name="{escape(name)}" data-folder="{escape(lst[0].group)}"><td><span class="lv {level}">{escape(what)}</span></td>'
                    f'<td class="mat"><code>{escape(name)}</code></td><td class="folder">{escape(lst[0].group)}</td><td class="n">{len(lst)}</td>'
                    f'<td><ul>{"".join(_loc(p, d) for p, d in ex)}{more}</ul></td></tr>')
    return _table(["Problema", "Modelo", "Pasta", "Usos", f"Onde (até {L.MAX_EXAMPLES})"], rows, "Nenhum problema de modelo."), len(by)


def _tab_tjunctions(rep: L.Report, radius: float) -> tuple[str, int]:
    nr = _not_run("tjunctions", rep)
    if nr:
        return nr, 0
    faces = rep.data.get("tjunctions", [])
    total = rep.data.get("tjunctions_total", 0)
    pts = [(f["mat"], f["center"], "") for f in faces for _ in range(f["extra"])]  # peso = vértices extras da face
    clusters = hotspots(pts)[:20]
    crow = []
    for k, g in enumerate(clusters, 1):
        size = g["hi"] - g["lo"]
        crow.append(f'<tr data-name="" data-folder="" data-areas="{_akey(g["center"])}"><td class="n">{k}</td><td><code>{escape(_coord(g["center"]))}</code>'
                    f'<div class="d">área ~{size.x:.0f}×{size.y:.0f}×{size.z:.0f}u</div>'
                    f'<button class="go" data-copy="setpos {escape(_coord(g["center"] + Vec(0, 0, 64)))}">setpos no centro</button></td>'
                    f'<td class="n">{g["count"]}</td><td><ul>{"".join(f"<li><code>{escape(m)}</code><span class=d>{c}×</span></li>" for m, c in g["materials"][:5])}</ul></td></tr>')
    rows = []
    for k, f in enumerate(faces[:300], 1):
        rows.append(f'<tr data-name="{escape(f["mat"].lower())}" data-folder="{escape(f["owner"])}"><td class="n">{k}</td>'
                    f'<td>{escape(f["owner"])} solid {f["solid"]} · face {f["face"]}<div class="d"><code>{escape(f["mat"])}</code></div></td>'
                    f'<td class="n">{f["extra"]}</td><td class="n">{f["idx"]}</td>'
                    f'<td><ul>{_loc(f["center"], "centro da face")}{"".join(_loc(p, d) for p, d in f["points"])}</ul></td></tr>')
    head = (f'<div class="stats"><div class="stat"><b>{len(faces)}</b><span>faces com t-junction</span></div>'
            f'<div class="stat"><b>{total}</b><span>índices estimados (teto: não desconta o que o vbsp remove)</span></div>'
            f'<div class="stat"><b>65536</b><span>limite do vbsp</span></div></div>'
            '<p class="sub">Como resolver à mão: nas regiões abaixo, junte blocos vizinhos que formam uma peça só '
            '(piso, parede, rodapé fatiados), alinhe emendas pra coincidirem com os vértices vizinhos, ou transforme acabamentos em prop. '
            '<code>ht optimize</code> junta sozinho blocos retangulares fatiados com a mesma textura (ajuda quando há piso/parede em fatias; vizinhos de tamanhos diferentes só à mão). Pra compilar já: o ht-vbsp usa <code>-notjunc</code> sozinho se estourar.</p>')
    return (head + "<h3>Onde mais tem t-junction (blocos de 512u)</h3>" + _table(["#", "Centro", "Vértices", "Materiais"], crow, "Nenhuma.")
            + f"<h3>Faces que mais gastam índices (até 300)</h3>" + _table(["#", "Face", "Vértices", "Índices", "Onde (centro + pontos exatos)"], rows, "Nenhuma.")), len(faces)


def _tab_generic(rep: L.Report, checks: list[str]) -> tuple[str, int]:
    parts, n = [], 0
    for c in checks:
        nr = _not_run(c, rep)
        items = [i for i in rep.issues if i.check == c]
        n += len(items)
        rows = [f'<tr data-name="{escape(i.msg.lower())}" data-folder=""><td><span class="lv {i.level}">{escape(i.level)}</span></td>'
                f'<td>{escape(i.msg)}</td><td><ul>{_loc(i.pos) if i.pos is not None else ""}</ul></td></tr>' for i in items[:500]]
        parts.append(f"<h3>{escape(L.LABELS[c])} <span class='d'>{len(items)}</span></h3>" + (nr or _table(["Nível", "Problema", "Onde"], rows, "Nada encontrado.")))
    return "".join(parts), n


def _tab_leak(rep: L.Report) -> tuple[str, int]:
    nr = _not_run("leak", rep)
    if nr:
        return nr, 0
    items = [i for i in rep.issues if i.check == "leak"]
    if not items:
        return '<p class="ok">Sem leak: nenhuma entidade alcança o vazio.</p>', 0
    path = rep.leak_path
    step = max(1, len(path) // 12)
    pts = "".join(_loc(p, f"passo {k * step + 1}/{len(path)}") for k, p in enumerate(path[::step]))
    rows = [f'<tr data-name="" data-folder=""><td>{escape(i.msg)}</td><td><ul>{_loc(i.pos) if i.pos is not None else ""}</ul></td></tr>' for i in items]
    return (f'<p class="warn">O caminho abaixo vai da primeira entidade até o vazio; o buraco está onde ele atravessa uma parede. '
            f'Com <code>--pointfile</code> sai um .lin pra carregar no Hammer (Map &gt; Load Pointfile).</p>'
            f"<h3>Caminho do leak</h3><ul class='path'>{pts}</ul>" + "<h3>Entidades no vazio</h3>" + _table(["Entidade", "Onde"], rows, "")), len(items)


# --------------------------------------------------------------------------- painel
def _dashboard(rep: L.Report, radius: float) -> str:
    errs = len(rep.errors)
    warns = len(rep.issues) - errs
    cards = []
    for check, level, title, what in PRIORITY:
        if check not in rep.ran:
            continue
        items = [i for i in rep.issues if i.check == check and i.level == level]
        if check == "tjunctions":
            faces = rep.data.get("tjunctions", [])
            total = rep.data.get("tjunctions_total", 0)
            if not faces:
                continue
            risk = total > L.MAX_PRIMINDICES
            top = [(f"{f['owner']} solid {f['solid']} ({f['mat']})", f"~{f['idx']} índices", f["center"]) for f in faces[:3]]
            cards.append((("aviso" if not risk else "risco"), title, f"{len(faces)} faces · ~{total} índices estimados (limite 65536)", what, top, "tj"))
            continue
        if not items:
            continue
        if check in ("textures", "models") and level == "erro":
            agg = defaultdict(lambda: [0, None])
            for i in items:
                agg[i.name][0] += max(i.count, 1)
                agg[i.name][1] = agg[i.name][1] or i.pos
            ranked = sorted(agg.items(), key=lambda kv: -kv[1][0])
            top = [(n, f"{c} uso(s)", p) for n, (c, p) in ranked[:3]]
            summary = f"{len(agg)} {'materiais' if check == 'textures' else 'modelos'} · {sum(c for c, _ in agg.values())} usos"
        else:
            top = [(i.msg, "", i.pos) for i in items[:3]]
            summary = f"{len(items)} ocorrência(s)"
        tab = {"textures": "tex", "models": "mdl", "leak": "leak", "markers": "ent", "outputs": "ent"}.get(check, "geo")
        cards.append((level, title, summary, what, top, tab))
    card_html = []
    for level, title, summary, what, top, tab in cards:
        li = "".join(f'<li{f" data-area={_akey(p)}" if p is not None else ""}><span class="nm">{escape(n)}</span>{f"<span class=d>{escape(extra)}</span>" if extra else ""}'
                     + (f'<button data-copy="setpos {escape(_coord(p + Vec(0, 0, 64)))}">setpos</button>' if p is not None else "") + "</li>"
                     for n, extra, p in top)
        card_html.append(f'<div class="card {level}"><div class="ch"><span class="lv {level}">{"erro" if level == "erro" else "risco" if level == "risco" else "aviso"}</span>'
                         f'<h3>{escape(title)}</h3></div><p class="sum">{escape(summary)}</p><p class="what">{escape(what)}</p>'
                         f'<ul>{li}</ul><button class="open" data-goto="{tab}">ver detalhes</button></div>')
    # pontos quentes: todas as posições de todas as checagens
    pts = []
    for i in rep.issues:
        if i.check == "textures":
            pts += [(("erro", "textures"), p, "") for p, _ in i.locations]
        elif i.pos is not None:
            pts.append(((i.level, i.check), i.pos, ""))
    for f in rep.data.get("tjunctions", [])[:2000]:
        pts.append((("aviso", "tjunctions"), f["center"], ""))
    hot = hotspots(pts, AREA)
    hot.sort(key=lambda g: (-sum(c for (lv, _), c in g["materials"] if lv == "erro"), -g["count"]))
    hrows = []
    for k, g in enumerate(hot[:8], 1):
        size = g["hi"] - g["lo"]
        br = "".join(f'<span class="tag {lv}">{escape(L.LABELS[c])} {n}</span>' for (lv, c), n in g["materials"])
        key = _akey(g["center"])
        hrows.append(f'<tr data-name="" data-folder="" data-areas="{key}"><td class="n">{k}</td><td><code>{escape(_coord(g["center"]))}</code>'
                     f'<div class="d">área ~{size.x:.0f}×{size.y:.0f}×{size.z:.0f}u</div>'
                     f'<button class="go" data-copy="setpos {escape(_coord(g["center"] + Vec(0, 0, 64)))}">setpos no centro</button> '
                     f'<button class="go" data-area-go="{key}">filtrar esta área</button></td>'
                     f'<td class="n">{g["count"]}</td><td>{br}</td></tr>')
    ok_checks = [L.LABELS[c] for c in L.ALL_CHECKS if c in rep.ran and c not in rep.skipped and not any(i.check == c for i in rep.issues)
                 and not (c == "tjunctions" and rep.data.get("tjunctions"))]
    return (f'<div class="stats"><div class="stat"><b class="e">{errs}</b><span>erros</span></div><div class="stat"><b>{warns}</b><span>avisos</span></div>'
            f'<div class="stat"><b class="g">{len(ok_checks)}</b><span>checagens limpas</span></div></div>'
            + (f'<p class="sub">Limpas: {escape(", ".join(ok_checks))}</p>' if ok_checks else "")
            + "".join(f'<p class="warn">Pulada: {escape(L.LABELS[c])} — {escape(w)}</p>' for c, w in rep.skipped.items())
            + '<h2>Prioridades</h2><div class="cards">' + ("".join(card_html) or '<p class="ok">Nada a resolver.</p>') + "</div>"
            + f"<h2>Onde concentrar esforço</h2><p class='sub'>Blocos de {AREA:.0f}u que juntam mais problemas (todas as checagens), erros primeiro. "
            "O mesmo bloco é a área do filtro lá em cima.</p>"
            + _table(["#", "Centro", "Ocorr.", "O quê"], hrows, "Nenhuma ocorrência com posição."))


def _areas(rep: L.Report) -> list[dict]:
    """Blocos com problema, do mais carregado pro menos: chave, total, centro e composição por checagem."""
    pts = []
    for i in rep.issues:
        if i.check == "textures":
            pts += [(i.check, p) for p, _ in i.locations]
        elif i.pos is not None:
            pts.append((i.check, i.pos))
    pts += [("tjunctions", f["center"]) for f in rep.data.get("tjunctions", [])]
    cells: dict[str, list] = defaultdict(list)
    for c, p in pts:
        cells[_akey(p)].append((c, p))
    out = []
    for k, lst in cells.items():
        center = sum((p for _, p in lst), Vec()) / len(lst)
        out.append({"k": k, "n": len(lst), "c": _coord(center),
                    "w": ", ".join(f"{L.LABELS[c]} {n}" for c, n in Counter(c for c, _ in lst).most_common(3))})
    out.sort(key=lambda a: -a["n"])
    return out


# --------------------------------------------------------------------------- página
CSS = """
:root { --bg:#f7f7f5; --fg:#1d1d1b; --muted:#6b6b66; --card:#fff; --line:#e3e2de; --accent:#c2410c; --err:#b91c1c; --warn:#a16207; --ok:#15803d; --chip:#efeeea; --code:#f1f0ec; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#161615; --fg:#ecebe7; --muted:#9a9993; --card:#1f1f1d; --line:#2e2e2b; --accent:#fb923c; --err:#f87171; --warn:#facc15; --ok:#4ade80; --chip:#2a2a27; --code:#262624; } }
:root[data-theme="dark"] { --bg:#161615; --fg:#ecebe7; --muted:#9a9993; --card:#1f1f1d; --line:#2e2e2b; --accent:#fb923c; --err:#f87171; --warn:#facc15; --ok:#4ade80; --chip:#2a2a27; --code:#262624; }
* { box-sizing:border-box } body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:1240px; margin:0 auto; padding:24px 16px 48px; } h1 { font-size:22px; margin:0 0 4px } h2 { font-size:17px; margin:26px 0 8px } h3 { font-size:15px; margin:20px 0 8px }
.sub { color:var(--muted); margin:0 0 14px } .warn { color:var(--warn) } .ok { padding:14px; color:var(--ok) } .d { color:var(--muted); font-size:12px }
.stats { display:flex; gap:12px; flex-wrap:wrap; margin:0 0 14px } .stat { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 14px; min-width:120px }
.stat b { display:block; font-size:22px; color:var(--accent) } .stat b.e { color:var(--err) } .stat b.g { color:var(--ok) } .stat span { color:var(--muted); font-size:13px }
.tabs { display:flex; gap:2px; border-bottom:1px solid var(--line); margin:10px 0 16px; overflow-x:auto; overflow-y:hidden; scrollbar-width:thin }
.tab { border:0; background:transparent; color:var(--muted); font:inherit; padding:8px 12px; cursor:pointer; border-bottom:2px solid transparent; margin-bottom:-1px; white-space:nowrap }
.tab.on { color:var(--fg); border-bottom-color:var(--accent); font-weight:600 } .tab b { font-weight:500; color:var(--muted); font-size:12px }
.panel[hidden], .tools[hidden], [hidden] { display:none !important } .tools { display:flex; gap:8px; margin:0 0 12px; flex-wrap:wrap; align-items:center }
select { padding:8px 10px; border-radius:8px; border:1px solid var(--line); background:var(--card); color:var(--fg); font:inherit; max-width:100% }
label.tg { display:flex; gap:6px; align-items:center; color:var(--muted); font-size:14px; cursor:pointer; white-space:nowrap }
tr.grp td { background:var(--chip); font-size:13px; padding:6px 12px } tr.grp b { color:var(--accent) }
.areanote { color:var(--accent); font-size:13px; margin:0 0 10px }
input[type=search] { flex:1 1 240px; padding:8px 10px; border-radius:8px; border:1px solid var(--line); background:var(--card); color:var(--fg); font:inherit }
.chips { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:12px } .chip { border:1px solid var(--line); background:var(--chip); color:var(--fg); border-radius:999px; padding:4px 10px; cursor:pointer; font:inherit; font-size:13px } .chip.on { border-color:var(--accent); color:var(--accent) }
.tablewrap { overflow-x:auto; background:var(--card); border:1px solid var(--line); border-radius:10px } table { width:100%; border-collapse:collapse; min-width:680px }
th, td { text-align:left; padding:9px 12px; border-bottom:1px solid var(--line); vertical-align:top } th { font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); background:var(--card) }
td.n, th.n { text-align:right; font-variant-numeric:tabular-nums; width:70px } td.folder { color:var(--muted); white-space:nowrap } td.mat code { font-weight:600 }
code { font-family:ui-monospace,"JetBrains Mono",monospace; font-size:13px; background:var(--code); padding:1px 5px; border-radius:4px }
ul { list-style:none; margin:0; padding:0; display:grid; gap:4px } li { display:flex; gap:8px; align-items:center; flex-wrap:wrap } li.more { color:var(--muted); font-size:12px }
li button, button.go, button.open { border:1px solid var(--line); background:transparent; color:var(--fg); border-radius:6px; padding:1px 7px; font-size:12px; cursor:pointer }
li button:hover, button.go:hover, button.open:hover { border-color:var(--accent); color:var(--accent) } button.go { margin-top:6px }
.lv { font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.04em; padding:1px 6px; border-radius:4px; border:1px solid currentColor } .lv.erro { color:var(--err) } .lv.aviso { color:var(--warn) } .lv.risco { color:var(--accent) }
.tag { display:inline-block; font-size:12px; margin:0 6px 4px 0; padding:1px 7px; border-radius:999px; background:var(--chip) } .tag.erro { color:var(--err) } .tag.aviso { color:var(--warn) }
.cards { display:grid; grid-template-columns:repeat(auto-fill, minmax(320px, 1fr)); gap:12px }
.card { background:var(--card); border:1px solid var(--line); border-left:4px solid var(--warn); border-radius:10px; padding:12px 14px; display:flex; flex-direction:column; gap:6px }
.card.erro { border-left-color:var(--err) } .card.risco { border-left-color:var(--accent) } .ch { display:flex; gap:8px; align-items:center } .card h3 { margin:0 } .card .sum { margin:0; font-weight:600 } .card .what { margin:0; color:var(--muted); font-size:13px }
.card .nm { font-family:ui-monospace,monospace; font-size:12px; overflow-wrap:anywhere } .card button.open { align-self:flex-start; margin-top:4px }
ul.path { gap:2px } #toast { position:fixed; bottom:16px; left:50%; transform:translateX(-50%); background:var(--fg); color:var(--bg); padding:6px 12px; border-radius:8px; opacity:0; transition:opacity .2s; font-size:13px; pointer-events:none }
"""

JS = """
const tabs = [...document.querySelectorAll('.tab')];
const q = document.getElementById('q'), sel = document.getElementById('area'), grp = document.getElementById('group');
const AREAS = JSON.parse(document.getElementById('areas').textContent);
const rank = {}; AREAS.forEach((a, i) => rank[a.k] = i);
const areaLabel = k => k in rank ? `#${rank[k] + 1} · ${AREAS[rank[k]].c} · ${AREAS[rank[k]].n} problema(s)` : 'sem área';
AREAS.forEach((a, i) => { const o = document.createElement('option'); o.value = a.k; o.textContent = `#${i + 1} · centro ${a.c} · ${a.n} problema(s) — ${a.w}`; sel.appendChild(o); });
let folder = '', cur = 'dash';
// cada linha: áreas (das localizações ou data-areas) e a principal (a que mais aparece; empate = a mais carregada)
const rows = [...document.querySelectorAll('.panel tbody tr')];
rows.forEach((r, i) => {
  r._i = i;
  const ks = [...r.querySelectorAll('li[data-area]')].map(li => li.dataset.area).concat(r.dataset.areas ? r.dataset.areas.split(' ') : []);
  r._areas = new Set(ks);
  const c = {}; ks.forEach(k => c[k] = (c[k] || 0) + 1);
  r._main = Object.keys(c).sort((a, b) => (c[b] - c[a]) || ((rank[a] ?? 1e9) - (rank[b] ?? 1e9)))[0] || '';
});
function show(id) {
  cur = id;
  tabs.forEach(t => t.classList.toggle('on', t.dataset.tab === id));
  document.querySelectorAll('.panel').forEach(p => p.hidden = p.id !== 'p-' + id);
  q.hidden = id === 'dash';
  try { localStorage.setItem('ht-tab', id); } catch (_) {}
}
function regroup() {
  document.querySelectorAll('tr.grp').forEach(h => h.remove());
  document.querySelectorAll('.panel tbody').forEach(tb => {
    const rs = [...tb.rows];
    rs.sort(grp.checked ? (a, b) => ((rank[a._main] ?? 1e9) - (rank[b._main] ?? 1e9)) || (a._i - b._i) : (a, b) => a._i - b._i);
    rs.forEach(r => tb.appendChild(r));
    if (!grp.checked) return;
    const cols = tb.closest('table').querySelectorAll('thead th').length;
    let last = null;
    rs.forEach(r => {
      if (r._main === last) return;
      last = r._main;
      const h = document.createElement('tr'); h.className = 'grp'; h._main = r._main;
      h.innerHTML = `<td colspan="${cols}"><b>Área ${areaLabel(r._main)}</b></td>`;
      tb.insertBefore(h, r);
    });
  });
}
function apply() {
  const t = q.value.toLowerCase(), a = sel.value;
  rows.forEach(r => {
    const pan = r.closest('.panel').id;
    const txt = pan === 'p-dash' || ((!folder || !r.dataset.folder || r.dataset.folder === folder) && (!t || (r.dataset.name || '').includes(t) || (r.dataset.folder || '').includes(t) || r.textContent.toLowerCase().includes(t)));
    r.hidden = !(txt && (!a || r._areas.has(a)));
  });
  // localizações fora da área somem de todas as listas (cartões do painel, caminho do leak, exemplos)
  document.querySelectorAll('li[data-area]').forEach(li => li.hidden = !!a && li.dataset.area !== a);
  document.querySelectorAll('tr.grp').forEach(h => {
    let n = h.nextElementSibling, vis = 0;
    while (n && !n.classList.contains('grp')) { if (!n.hidden) vis++; n = n.nextElementSibling; }
    h.hidden = !vis;
    const b = h.querySelector('b'); if (b) b.nextSibling ? b.nextSibling.textContent = ` · ${vis} linha(s)` : b.insertAdjacentText('afterend', ` · ${vis} linha(s)`);
  });
  // tabela sem nada visível: some e dá lugar a um aviso
  document.querySelectorAll('.panel .tablewrap').forEach(w => {
    const any = [...w.querySelectorAll('tbody tr:not(.grp)')].some(r => !r.hidden);
    w.hidden = !any;
    let n = w.nextElementSibling;
    if (!n || !n.classList.contains('none')) { n = document.createElement('p'); n.className = 'none sub'; n.textContent = 'Nada nesta área / filtro.'; w.after(n); }
    n.hidden = any;
  });
  // número da aba: com filtro de área, quantas linhas da aba caem nela
  tabs.forEach(tb => {
    const b = tb.querySelector('b'); if (!b) return;
    if (b.dataset.all === undefined) b.dataset.all = b.textContent;
    const pr = [...document.querySelectorAll('#p-' + tb.dataset.tab + ' tbody tr:not(.grp)')];
    b.textContent = a ? `${pr.filter(r => !r.hidden).length} na área` : b.dataset.all;
  });
  const note = document.getElementById('areanote');
  note.hidden = !a; note.textContent = a ? `Mostrando só a área ${areaLabel(a)} em todas as abas.` : '';
  try { localStorage.setItem('ht-area', a); localStorage.setItem('ht-group', grp.checked ? '1' : ''); } catch (_) {}
}
tabs.forEach(t => t.addEventListener('click', () => show(t.dataset.tab)));
document.querySelectorAll('[data-goto]').forEach(b => b.addEventListener('click', () => { show(b.dataset.goto); window.scrollTo(0, 0); }));
document.querySelectorAll('[data-area-go]').forEach(b => b.addEventListener('click', () => { sel.value = b.dataset.areaGo; apply(); window.scrollTo(0, 0); }));
q.addEventListener('input', apply);
sel.addEventListener('change', apply);
grp.addEventListener('change', () => { regroup(); apply(); });
document.querySelectorAll('.chip').forEach(c => c.addEventListener('click', () => {
  folder = folder === c.dataset.folder ? '' : c.dataset.folder;
  document.querySelectorAll('.chip').forEach(x => x.classList.toggle('on', x.dataset.folder === folder)); apply();
}));
try {
  const s = localStorage.getItem('ht-tab'); if (s && document.getElementById('p-' + s)) show(s);
  const a = localStorage.getItem('ht-area'); if (a && a in rank) sel.value = a;
  grp.checked = localStorage.getItem('ht-group') === '1';
} catch (_) {}
show(cur); regroup(); apply();
const toast = document.getElementById('toast');
document.addEventListener('click', e => {
  const b = e.target.closest('button[data-copy]'); if (!b) return;
  const txt = b.dataset.copy;
  const done = () => { toast.textContent = 'copiado: ' + txt; toast.style.opacity = 1; setTimeout(() => toast.style.opacity = 0, 1400); };
  (navigator.clipboard ? navigator.clipboard.writeText(txt) : Promise.reject()).then(done).catch(() => {
    const a = document.createElement('textarea'); a.value = txt; document.body.appendChild(a); a.select();
    try { document.execCommand('copy'); done(); } catch (_) {} a.remove();
  });
});
"""


def write(rep: L.Report, path: Path, map_name: str, cluster_radius: float = 256.0, area_size: float = 1024.0) -> Path:
    global AREA
    AREA = float(area_size)
    tex, reg, n_tex, n_reg = _tab_textures(rep, cluster_radius)
    mdl, n_mdl = _tab_models(rep)
    tj, n_tj = _tab_tjunctions(rep, cluster_radius)
    leak, n_leak = _tab_leak(rep)
    geo, n_geo = _tab_generic(rep, ["nodraw", "overlaps", "duplicates", "grid"])
    ent, n_ent = _tab_generic(rep, ["markers", "outputs"])
    panels = [("dash", "Painel", None, _dashboard(rep, cluster_radius)), ("tex", "Texturas", n_tex, tex), ("reg", "Texturas por região", n_reg, reg),
              ("mdl", "Modelos", n_mdl, mdl), ("tj", "T-junctions", n_tj, tj), ("leak", "Leak", n_leak, leak),
              ("geo", "Geometria", n_geo, geo), ("ent", "Entidades", n_ent, ent)]
    tabs = "".join(f'<button class="tab{" on" if k == 0 else ""}" data-tab="{pid}">{escape(t)}{f" <b>{n}</b>" if n is not None else ""}</button>'
                   for k, (pid, t, n, _) in enumerate(panels))
    areas_json = json.dumps(_areas(rep)).replace("</", "<\\/")
    body = "".join(f'<section class="panel" id="p-{pid}"{"" if k == 0 else " hidden"}>{html}</section>' for k, (pid, _, _, html) in enumerate(panels))
    page = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lint do mapa</title><style>{CSS}</style></head><body><main>
<h1>Lint: {escape(map_name)}</h1>
<p class="sub">{escape(datetime.now().strftime("%d/%m/%Y %H:%M"))} · fontes: {escape(str(rep.stats.get("recursos", "")))}</p>
<div class="tabs">{tabs}</div>
<div class="tools" id="tools"><input type="search" id="q" placeholder="Filtrar a aba (nome, pasta, texto)" hidden>
<select id="area" title="Área = bloco de {AREA:.0f}u; vale pra todas as abas"><option value="">Todas as áreas</option></select>
<label class="tg"><input type="checkbox" id="group"> Agrupar por área</label></div>
<p class="areanote" id="areanote" hidden></p>
{body}
<p class="sub" style="margin-top:18px"><b>setpos</b> copia um comando pro console do jogo (64u acima do ponto); <b>xyz</b> copia as coordenadas pro Hammer++ (Ctrl+Shift+G).</p>
</main><div id="toast">copiado</div>
<script type="application/json" id="areas">{areas_json}</script>
<script>{JS}</script></body></html>"""
    path = Path(path)
    path.write_text(page, encoding="utf-8")
    return path

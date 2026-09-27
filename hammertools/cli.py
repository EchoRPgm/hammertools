"""CLI `ht`: build, list-markers, lint."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hammertools.core import vmf as vmfio
from hammertools.generators import REGISTRY, SINGLE


def cmd_list(args) -> int:
    v = vmfio.load(args.vmf)
    groups = vmfio.group_markers(vmfio.markers(v))
    if not groups:
        print("nenhum marcador ht_* no mapa")
        return 0
    for g in groups.values():
        roles = ", ".join(f"{vmfio.role_of(e)}@{e['origin']}" for e in g.ents)
        print(f"{g.classname:14} {g.name:20} {roles}")
    return 0


def build(src: Path, out: Path, game: str | None = None, cubemaps: bool = False) -> tuple[int, int, list[str]]:
    """Retorna (grupos processados, solids gerados, warnings)."""
    from hammertools.core import models
    models.GAMEDIR = game
    v = vmfio.load(src)
    vmfio.strip_visgroup(v, vmfio.PREVIEW_VISGROUP)  # preview é descartável; o build regenera tudo
    groups = vmfio.group_markers(vmfio.markers(v))
    warnings: list[str] = []
    n_solids = 0
    for g in groups.values():
        gen = REGISTRY.get(g.classname)
        if gen is None:
            warnings.append(f"{g.classname}: sem gerador registrado")
            continue
        res = gen(v, g)
        warnings.extend(res.warnings)
        vmfio.add_generated(v, g.name, res.solids, res.ents, vmfio.detail_for(g, res.detail))
        n_solids += len(res.solids)
        for e in g.ents:
            vmfio.park_marker(v, e)
    if cubemaps:
        from hammertools.generators.cubemaps import auto_cubemaps
        n = auto_cubemaps(v)
        vmfio.add_generated(v, "cubemaps_auto", [], [e for e in v.entities if e["classname"] == "env_cubemap" and not e.visgroup_ids], True)
        warnings.append(f"cubemaps automáticos: {n} env_cubemap sob luzes")
    vmfio.save(v, out)
    return len(groups), n_solids, warnings


def preview(src: Path, game: str | None = None) -> tuple[int, int, list[str]]:
    """Gera a geometria DENTRO do mapa fonte (visgroup ht_preview), sem esconder marcadores.
    Roda de novo = apaga o preview anterior e regenera. Retorna (grupos, solids, warnings)."""
    from hammertools.core import models
    models.GAMEDIR = game
    v = vmfio.load(src)
    vmfio.strip_visgroup(v, vmfio.PREVIEW_VISGROUP)
    groups = vmfio.group_markers(vmfio.markers(v))
    warnings: list[str] = []
    n_solids = 0
    for g in groups.values():
        gen = REGISTRY.get(g.classname)
        if gen is None:
            warnings.append(f"{g.classname}: sem gerador registrado")
            continue
        res = gen(v, g)
        warnings.extend(res.warnings)
        vmfio.add_preview(v, g.name, res.solids, res.ents, vmfio.detail_for(g, res.detail))
        n_solids += len(res.solids)
    vmfio.save(v, src)
    return len(groups), n_solids, warnings


def clear_preview(src: Path) -> int:
    v = vmfio.load(src)
    n = vmfio.strip_visgroup(v, vmfio.PREVIEW_VISGROUP)
    vmfio.save(v, src)
    return n


def cmd_preview(args) -> int:
    src = Path(args.vmf)
    if src.stem.endswith("_built"):
        print("recuse: preview é pro VMF fonte", file=sys.stderr)
        return 2
    if args.clear:
        n = clear_preview(src)
        print(f"{src}: preview removido ({n} objeto(s)); recarregue no Hammer++")
        return 0
    n_groups, n_solids, warnings = preview(src, args.game)
    for w in warnings:
        print(f"aviso: {w}", file=sys.stderr)
    print(f"{src}: preview de {n_groups} marcador(es), {n_solids} brush(es) no visgroup ht_preview (recarregue no Hammer++)")
    return 0


def cmd_build(args) -> int:
    src = Path(args.vmf)
    if src.stem.endswith("_built"):
        print("recuse: não faça build de um _built.vmf, use o VMF fonte", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else src.with_name(f"{src.stem}_built.vmf")
    out.parent.mkdir(parents=True, exist_ok=True)
    n_groups, n_solids, warnings = build(src, out, args.game, args.cubemaps)
    for w in warnings:
        print(f"aviso: {w}", file=sys.stderr)
    print(f"{out}: {n_groups} marcador(es), {n_solids} brush(es) gerados")
    return 0


def cmd_lint(args) -> int:
    from hammertools import lint
    v = vmfio.load(args.vmf)
    checks = set(lint.ALL_CHECKS)
    if args.only:
        checks = {c.strip() for c in args.only.split(",")}
    if args.skip:
        checks -= {c.strip() for c in args.skip.split(",")}
    bad = checks - set(lint.ALL_CHECKS)
    if bad:
        print(f"checagem desconhecida: {', '.join(sorted(bad))} (válidas: {', '.join(lint.ALL_CHECKS)})", file=sys.stderr)
        return 2
    need_res = checks & {"textures", "models", "leak", "nodraw", "perf"}
    res = lint.Resources.from_game(args.game, args.bsp, args.extra or ()) if need_res else lint.Resources()
    compiled = Path(args.compiled) if args.compiled else None
    if compiled is None and "phantom" in checks:
        guess = Path(args.vmf).with_suffix(".bsp")  # o ht-vbsp copia o .bsp pra junto do fonte
        if guess.exists() and guess.stat().st_mtime >= Path(args.vmf).stat().st_mtime:
            compiled = guess
    rep = lint.run(v, res, checks, grid=args.grid, detail_grid=args.detail_grid, voxel=args.voxel, compiled=compiled)
    ign = Path(args.ignore) if args.ignore else Path(args.vmf).with_suffix(".lintignore.json")
    if ign.exists():
        import json
        n = lint.apply_ignore(rep, json.loads(ign.read_text()))
        print(f"{n} ocorrência(s) ignorada(s) por {ign.name}")
    if "tjunctions" in rep.ran:
        fixp = Path(args.tjfix) if args.tjfix else Path(args.vmf).with_suffix(".tjfix.json")
        if fixp.exists():
            import json
            lint.apply_tjfix(rep, json.loads(fixp.read_text()), stale=fixp.stat().st_mtime < Path(args.vmf).stat().st_mtime)
    print(lint.format_report(rep, args.max))
    if args.html is not None:
        out = Path(args.html) if args.html else Path(args.vmf).with_suffix(".lint.html")
        lint.write_html(rep, out, Path(args.vmf).name, args.cluster_radius, args.area_size)
        print(f"relatório: {out}")
        if not args.no_open:
            import webbrowser
            webbrowser.open(out.resolve().as_uri())
    if rep.leak_path and args.pointfile:
        pf = Path(args.vmf).with_suffix(".lin")
        lint.write_pointfile(pf, rep.leak_path)
        print(f"pointfile do leak: {pf} (Hammer++: Map > Load Pointfile)")
    return 1 if rep.errors else 0


def cmd_content(args) -> int:
    """Monta a pasta de conteúdo do mapa (dependências que o jogo ainda não enxerga)."""
    import logging, shutil
    logging.getLogger("srctools").setLevel(logging.ERROR)
    from hammertools import content, lint
    from hammertools.core.gma import find_addons
    gd = lint._find_game(args.game)
    if gd is None:
        print("pasta do jogo não encontrada (use --game)", file=sys.stderr)
        return 2
    vmf_path = Path(args.vmf)
    v = vmfio.load(vmf_path)
    stem = vmf_path.stem.removesuffix("_built")
    out = Path(args.out) if args.out else gd / "addons" / f"{stem}_content"
    # o que o jogo já enxerga (VPKs + jogos montados + addons), SEM a própria pasta de saída
    res_game = lint.Resources.from_game(gd, None, (), addons=True)
    from srctools.game import Game
    fs = Game(gd).get_filesystem()
    for mdir in lint._mountable_games(gd):
        for sub in Game(mdir).get_filesystem().systems:
            fs.add_sys(sub[0] if isinstance(sub, tuple) else sub)
    from hammertools.core.gma import AddonIndex
    gmas = find_addons(gd)
    idx = AddonIndex(gmas)
    out_prefix = str(out.resolve())

    def game_has(p):
        p = content.norm(p)
        if p in idx:
            return True
        try:
            f = fs[p]
            return not str(getattr(f, "path", "")).startswith(out_prefix) and out_prefix not in str(getattr(f.sys, "path", ""))
        except FileNotFoundError:
            return False

    def game_read(p):
        p = content.norm(p)
        try:
            with fs[p].open_bin() as f:
                return f.read()
        except FileNotFoundError:
            return idx.read(p) if p in idx else None

    sources: list = []
    for b in args.bsp or []:
        sources.append(content.source_bsp(Path(b)))
    for d in args.extra or []:
        sources.append(content.source_dir(Path(d)))
    for g in args.gma or []:
        sources.append(content.source_gma(Path(g)))
    auto = [] if args.no_auto else content.map_bsps_in_addons(gmas, stem, args.all_map_paks)
    sources += auto
    print("fontes:", *(f"  - {s.name}" for s in sources) or ["  (nenhuma)"], sep="\n")
    res = content.resolve(v, game_has, game_read, sources)
    print(f"{res.roots} recursos citados pelo mapa; {len(res.in_game)} arquivos o jogo já tem; {len(res.copy)} a copiar; {len(res.missing)} faltando")
    if args.dry_run:
        for p, src in sorted(res.copy.items())[: args.max]:
            print(f"  + {p}  ({src})")
    else:
        if out.exists() and args.clean:
            shutil.rmtree(out)
        n = content.write(res, sources, out, f"{stem} content")
        print(f"gravados {n} arquivos em {out}")
    if res.missing:
        print("faltando (em nenhuma fonte):")
        for m in sorted(res.missing)[: args.max]:
            print(f"  - {m}")
        if len(res.missing) > args.max:
            print(f"  ... +{len(res.missing) - args.max}")
    return 0


def cmd_optimize(args) -> int:
    """Junta blocos retangulares fatiados (reduz t-junctions) num VMF novo."""
    from hammertools import optimize
    src = Path(args.vmf)
    out = Path(args.out) if args.out else src.with_name(f"{src.stem}_opt.vmf")
    if out.resolve() == src.resolve():
        print("recuse: a saída não pode ser o próprio fonte", file=sys.stderr)
        return 2
    v = vmfio.load(src)
    before = after = None
    if not args.no_measure:
        from hammertools import lint
        before = lint.run(v, lint.Resources(), {"tjunctions"}).data.get("tjunctions_total", 0)
    classify = optimize.default_classify
    try:
        from hammertools import lint as _lint
        seals = _lint.Resources.from_game(args.game).material_seals
        nonseal = _lint.NONSEAL_TOOLS
        if seals is not None:
            def classify(m: str) -> str:
                if m in nonseal or (m.startswith("tools/") and m != _lint.NODRAW):
                    return m
                return "solid" if m.startswith("tools/") or seals(m) else "translucent"
    except Exception as e:  # sem jogo: modo conservador
        print(f"aviso: sem os materiais do jogo ({e}); só junta brushes com o mesmo conjunto de materiais", file=sys.stderr)
    res = optimize.optimize(v, classify)
    if not args.no_measure:
        after = lint.run(v, lint.Resources(), {"tjunctions"}).data.get("tjunctions_total", 0)
    n = sum(res.merged.values())
    print(f"{res.boxes} caixas alinhadas de {res.solids} brushes; {n} junção(ões): "
          + (", ".join(f"{k} {c}" for k, c in res.merged.most_common()) or "nenhuma"))
    if before is not None:
        pct = 100 * (before - after) / before if before else 0
        print(f"t-junctions (índices estimados): {before} -> {after} ({pct:.0f}% a menos; limite do vbsp 65536)")
    if args.dry_run:
        return 0
    vmfio.save(v, out)
    print(f"gravado: {out}")
    return 0


def cmd_pack(args) -> int:
    """Embute no BSP compilado o conteúdo que o mapa usa e o GMod base não tem."""
    from hammertools import content, lint, pack
    src = Path(args.vmf)
    bsp_in = Path(args.bsp) if args.bsp else src.with_suffix(".bsp")
    if not bsp_in.exists():
        print(f"não achei o BSP compilado ({bsp_in}); use --bsp", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else bsp_in.with_name(f"{bsp_in.stem}_packed.bsp")
    gd = lint._find_game(args.game)
    dirs = [Path(d) for d in (args.source or [])] or [gd / "addons" / f"{src.stem}_content"]
    sources = [content.source_dir(d) for d in dirs if Path(d).is_dir()]
    sources += [content.source_gma(Path(g)) for g in (args.gma or [])]
    if not sources:
        print(f"nenhuma fonte de conteúdo existe ({', '.join(map(str, dirs))}); rode `ht content` antes ou passe --source", file=sys.stderr)
        return 2
    has, read = pack.base_filesystem(gd, mount=not args.no_css)
    r = pack.pack(vmfio.load(src), bsp_in, out, sources, has, read, dry_run=args.dry_run)
    from collections import Counter
    kinds = Counter(p.split("/")[0] for p in r.added)
    print(f"{len(r.added)} arquivo(s) embutidos ({r.bytes_added / 1e6:.1f} MB): " + ", ".join(f"{k} {n}" for k, n in kinds.most_common()))
    print(f"{r.kept} já estavam no pakfile; {len(r.missing)} dependência(s) não achadas em nenhuma fonte")
    for m in sorted(r.missing)[: args.max]:
        print(f"  faltando: {m}")
    if not args.dry_run:
        print(f"gravado: {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


def _out_path(args, suffix: str) -> Path:
    src = Path(args.vmf)
    out = Path(args.out) if args.out else src.with_name(f"{src.stem}_{suffix}.vmf")
    if out.resolve() == src.resolve():
        raise SystemExit("recuse: a saída não pode ser o próprio fonte")
    return out


def cmd_rename(args) -> int:
    from hammertools import rename
    v = vmfio.load(args.vmf)
    r = rename.rename(v, args.pattern, args.replacement)
    for old, new in sorted(r.mapping.items()):
        print(f"  {old} -> {new}")
    print(f"{len(r.mapping)} nome(s); {r.entities} entidade(s), {r.keyvalues} keyvalue(s), {r.outputs} output(s) atualizados")
    for line in r.review:
        print(f"  revisar (curinga): {line}")
    if r.mapping and not args.dry_run:
        out = _out_path(args, "renomeado")
        vmfio.save(v, out)
        print(f"gravado: {out}")
    return 0


def cmd_retexture(args) -> int:
    from hammertools import retexture
    table = retexture.load_table(args.table) if args.table else []
    table += [tuple(x.split("=", 1)) for x in (args.set or [])]
    table = [(a.lower().replace("\\", "/"), b) for a, b in table]
    if not table:
        print("nada a trocar: use --table arquivo.toml ([materiais] \"origem\" = \"destino\") ou --set origem=destino", file=sys.stderr)
        return 2
    size_of = None
    if args.rescale:
        from hammertools import lint
        res = lint.Resources.from_game(args.game, args.bsp)
        size_of = lambda m: lint.texture_size(res, m)
    v = vmfio.load(args.vmf)
    r = retexture.retexture(v, table, size_of)
    for src, n in r.used.items():
        print(f"  {src}: {n}")
    print(f"{r.faces} face(s) e {r.entities} entidade(s) trocadas")
    if not args.dry_run:
        out = _out_path(args, "retex")
        vmfio.save(v, out)
        print(f"gravado: {out}")
    return 0


def cmd_lightmap(args) -> int:
    from hammertools import lightmap
    v = vmfio.load(args.vmf)
    mixed = lightmap.report(v)
    print(f"{len(mixed)} material(is) com escalas de lightmap misturadas (emendas de luz visíveis):")
    for m, c in sorted(mixed.items(), key=lambda kv: -sum(kv[1].values()))[: args.max]:
        print(f"  {m}: " + ", ".join(f"{k} ({n} faces)" for k, n in c.most_common()))
    rules = [(a, int(b)) for a, b in (x.split("=", 1) for x in (args.set or []))]
    if not rules and not args.uniform:
        return 0
    n = lightmap.normalize(v, rules, uniform=args.uniform)
    print(f"{n} face(s) mudaram de escala")
    if not args.dry_run:
        out = _out_path(args, "lightmap")
        vmfio.save(v, out)
        print(f"gravado: {out}")
    return 0


def cmd_detail(args) -> int:
    from hammertools import fix, lint
    v = vmfio.load(args.vmf)
    n = fix.fix_small_world(v, lint.Resources.from_game(args.game))
    print(f"{n} brush(es) de mundo pequenos/finos longe do vazio -> func_detail")
    if n and not args.dry_run:
        out = _out_path(args, "detail")
        vmfio.save(v, out)
        print(f"gravado: {out}  (compile e confira leak: o ht-vbsp avisa)")
    return 0


def cmd_diff(args) -> int:
    from hammertools import diffvmf
    lines = diffvmf.diff(vmfio.load(args.a), vmfio.load(args.b))
    print("\n".join(lines) if lines else "sem diferenças")
    return 0


def cmd_fix(args) -> int:
    """Consertos automáticos seguros num VMF novo (hoje: material de modelo em brush -> cópia LightmappedGeneric)."""
    from hammertools import fix, lint
    src = Path(args.vmf)
    out = Path(args.out) if args.out else src.with_name(f"{src.stem}_fix.vmf")
    if out.resolve() == src.resolve():
        print("recuse: a saída não pode ser o próprio fonte", file=sys.stderr)
        return 2
    res = lint.Resources.from_game(args.game, args.bsp)
    v = vmfio.load(src)
    r = fix.fix_model_shaders(v, res, args.prefix or f"{src.stem}_fix")
    for old, new in r.replaced.items():
        print(f"  {old} -> {new}")
    print(f"{len(r.replaced)} material(is) de modelo trocados em {r.faces} face(s) de brush")
    if not args.no_fade:
        print(f"{fix.fix_fades(v, res)} prop_static ganharam distância de desaparecer")
    if args.detail_small:
        print(f"{fix.fix_small_world(v, res)} brush(es) de mundo pequenos -> func_detail")
    if args.dry_run:
        return 0
    content = Path(args.content) if args.content else lint._find_game(args.game) / "addons" / f"{src.stem}_content"
    for p in fix.write_materials(r, content):
        print(f"  gravado {p}")
    vmfio.save(v, out)
    print(f"gravado: {out}  (os .vmt novos precisam ir junto com o mapa: pasta de conteúdo ou pakfile)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ht", description="hammertools: marcadores ht_* -> geometria")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build", help="gera geometria dos marcadores num novo VMF")
    p.add_argument("vmf"); p.add_argument("-o", "--out"); p.add_argument("--game", help="pasta com gameinfo.txt (ou env HT_GAME) pra ler modelos")
    p.add_argument("--cubemaps", action="store_true", help="também planta um env_cubemap sob cada luz (sem repetir vizinhos)"); p.set_defaults(fn=cmd_build)
    p = sub.add_parser("preview", help="gera a geometria dentro do próprio VMF fonte (visgroup ht_preview) pra ver no Hammer++")
    p.add_argument("vmf"); p.add_argument("--game", help="pasta com gameinfo.txt (ou env HT_GAME)")
    p.add_argument("--clear", action="store_true", help="só remove o visgroup ht_preview do fonte"); p.set_defaults(fn=cmd_preview)
    p = sub.add_parser("list-markers", help="lista marcadores ht_* do mapa")
    p.add_argument("vmf"); p.set_defaults(fn=cmd_list)
    p = sub.add_parser("lint", help="checagens pré-compile (texturas, modelos, leak, nodraw, duplicados, sobreposição, grid, I/O)")
    p.add_argument("vmf")
    p.add_argument("--game", help="pasta com gameinfo.txt (padrão: HT_GAME ou a instalação do GMod)")
    p.add_argument("--bsp", help="BSP compilado do mapa: conta os arquivos embutidos (pakfile) como existentes")
    p.add_argument("--extra", action="append", help="pasta extra com materials/ e models/ (repetível)")
    p.add_argument("--only", help="só estas checagens, separadas por vírgula")
    p.add_argument("--skip", help="pular estas checagens")
    p.add_argument("--grid", type=float, default=1.0)
    p.add_argument("--detail-grid", action="store_true", help="também checa grade em func_detail")
    p.add_argument("--voxel", type=float, help="resolução do teste de leak/nodraw (padrão automático)")
    p.add_argument("--pointfile", action="store_true", help="grava <mapa>.lin com o caminho do leak")
    p.add_argument("--max", type=int, default=15, help="máximo de itens listados por categoria")
    p.add_argument("--html", nargs="?", const="", default=None, metavar="ARQUIVO",
                   help="gera o relatório geral (painel de prioridades + abas por checagem) e abre no navegador; padrão <mapa>.lint.html")
    p.add_argument("--no-open", action="store_true", help="com --html: só grava, não abre o navegador")
    p.add_argument("--cluster-radius", type=float, default=256.0, help="com --html: distância máxima (u) pra juntar ocorrências na aba 'Por região'")
    p.add_argument("--ignore", help="regiões a ignorar (padrão <mapa>.lintignore.json): {\"regions\": [{\"box\": [[x,y,z],[x,y,z]], \"checks\": [\"nodraw\"], \"motivo\": \"...\"}]}")
    p.add_argument("--compiled", help="BSP compilado deste VMF, pra checagem de faces fantasma (padrão: <mapa>.bsp se for mais novo que o VMF)")
    p.add_argument("--tjfix", help="registro da compilação (padrão <mapa>.tjfix.json, gravado pelo ht-vbsp): marca as t-junctions resolvidas")
    p.add_argument("--area-size", type=float, default=1024.0, help="com --html: tamanho (u) do bloco de área do filtro/agrupamento por área")
    p.set_defaults(fn=cmd_lint)
    p = sub.add_parser("content", help="monta a pasta de conteúdo do mapa (dependências que o jogo não tem) em garrysmod/addons/<mapa>_content")
    p.add_argument("vmf")
    p.add_argument("-o", "--out", help="pasta de saída (padrão: <jogo>/addons/<mapa>_content)")
    p.add_argument("--game", help="pasta com gameinfo.txt (padrão: HT_GAME ou a instalação do GMod)")
    p.add_argument("--bsp", action="append", help="BSP com conteúdo embutido (repetível)")
    p.add_argument("--extra", action="append", help="pasta com materials/ models/ sound/ (repetível)")
    p.add_argument("--gma", action="append", help="addon .gma como fonte (repetível)")
    p.add_argument("--no-auto", action="store_true", help="não usar automaticamente BSPs de mapa com nome parecido dentro dos addons")
    p.add_argument("--all-map-paks", action="store_true", help="usar o conteúdo embutido de TODOS os mapas dos addons")
    p.add_argument("--clean", action="store_true", help="apaga a pasta de saída antes de gravar")
    p.add_argument("--dry-run", action="store_true", help="só lista, não grava")
    p.add_argument("--max", type=int, default=30)
    p.set_defaults(fn=cmd_content)
    p = sub.add_parser("rename", help="renomeia entidades por regex e atualiza outputs e keyvalues que apontam pra elas")
    p.add_argument("vmf"); p.add_argument("pattern", help="regex do nome inteiro, ex.: 'porta_(\\d+)'")
    p.add_argument("replacement", help="ex.: 'door_\\1'"); p.add_argument("-o", "--out"); p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_rename)
    p = sub.add_parser("retexture", help="troca materiais por tabela (blockout -> final)")
    p.add_argument("vmf"); p.add_argument("--table", help="TOML com [materiais] \"origem\" = \"destino\" (curinga permitido)")
    p.add_argument("--set", action="append", help="origem=destino (repetível)"); p.add_argument("-o", "--out")
    p.add_argument("--rescale", action="store_true", help="ajusta a escala pra textura nova ocupar o mesmo espaço (lê o tamanho dos .vtf)")
    p.add_argument("--game"); p.add_argument("--bsp"); p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_retexture)
    p = sub.add_parser("lightmap", help="relatório e padronização da escala de lightmap por material")
    p.add_argument("vmf"); p.add_argument("--set", action="append", help="material=escala (curinga permitido), ex.: 'nature/*=32'")
    p.add_argument("--uniform", action="store_true", help="material sem regra usa a escala mais comum dele no mapa")
    p.add_argument("-o", "--out"); p.add_argument("--dry-run", action="store_true"); p.add_argument("--max", type=int, default=20)
    p.set_defaults(fn=cmd_lightmap)
    p = sub.add_parser("detail", help="mapa pronto: brushes de mundo pequenos/finos longe do vazio -> func_detail")
    p.add_argument("vmf"); p.add_argument("--game"); p.add_argument("-o", "--out"); p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_detail)
    p = sub.add_parser("diff", help="diferenças legíveis entre dois VMFs por ID (entidades, keyvalues, outputs, brushes, materiais)")
    p.add_argument("a"); p.add_argument("b")
    p.set_defaults(fn=cmd_diff)
    p = sub.add_parser("pack", help="embute no BSP compilado o conteúdo que o mapa usa e o GMod base não tem (pakfile)")
    p.add_argument("vmf"); p.add_argument("--bsp", help="BSP compilado (padrão: <mapa>.bsp)")
    p.add_argument("-o", "--out", help="padrão: <bsp>_packed.bsp")
    p.add_argument("--game"); p.add_argument("--source", action="append", help="pasta com materials/ models/ sound/ (padrão: <jogo>/addons/<mapa>_content)")
    p.add_argument("--gma", action="append", help="addon .gma como fonte")
    p.add_argument("--no-css", action="store_true", help="embute também o que vem do CS:S (por padrão conta como montado)")
    p.add_argument("--dry-run", action="store_true"); p.add_argument("--max", type=int, default=20)
    p.set_defaults(fn=cmd_pack)
    p = sub.add_parser("fix", help="consertos automáticos seguros num VMF novo (material de modelo em brush, fade de props; --detail-small)")
    p.add_argument("vmf"); p.add_argument("-o", "--out", help="padrão: <mapa>_fix.vmf")
    p.add_argument("--game"); p.add_argument("--bsp", help="BSP com conteúdo embutido (pra achar os .vmt)")
    p.add_argument("--content", help="pasta onde gravar os .vmt novos (padrão: <jogo>/addons/<mapa>_content)")
    p.add_argument("--prefix", help="pasta dos materiais novos dentro de materials/ (padrão: <mapa>_fix)")
    p.add_argument("--no-fade", action="store_true", help="não mexe na distância de desaparecer dos prop_static")
    p.add_argument("--detail-small", action="store_true", help="converte brushes de mundo pequenos/finos longe do vazio em func_detail")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_fix)
    p = sub.add_parser("optimize", help="junta blocos retangulares fatiados com a mesma textura (menos t-junctions) num VMF novo")
    p.add_argument("vmf"); p.add_argument("-o", "--out", help="padrão: <mapa>_opt.vmf")
    p.add_argument("--game", help="pasta com gameinfo.txt (padrão: HT_GAME ou a instalação do GMod): diz quais materiais são translúcidos/água")
    p.add_argument("--dry-run", action="store_true", help="só mede, não grava")
    p.add_argument("--no-measure", action="store_true", help="não calcula t-junctions antes/depois (mais rápido)")
    p.set_defaults(fn=cmd_optimize)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())


# ---------------------------------------------------------------------------
# ht-vbsp: substituto transparente do vbsp.exe pro gameconfig do Hammer++.
# Hammer chama: <BSP> -game <gamedir> <path\file>. Aqui: ht build no fonte ->
# build\<file>.vmf, vbsp real sobre o gerado, e .bsp/.prt/.lin/.log copiados de
# volta pra <path>\<file>.* pra vvis/vrad/copy do próprio Hammer seguirem normais.
# ---------------------------------------------------------------------------
import os
import shutil
import subprocess


def _find_real_vbsp(gamedir: Path | None) -> Path | None:
    env = os.environ.get("HT_VBSP")
    if env and Path(env).exists():
        return Path(env)
    if gamedir:
        for rel in ("bin/win64/vbsp.exe", "bin/vbsp.exe", "bin/win64/vbsp", "bin/vbsp"):
            cand = gamedir.parent / rel
            if cand.exists():
                return cand
    return None


def _run_streaming(cmd: list[str]) -> tuple[int, str]:
    """Roda repassando a saída em tempo real (janela de compilação do Hammer) e devolve (rc, texto)."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)
    lines = []
    for line in p.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        lines.append(line)
    return p.wait(), "".join(lines)


PHANTOM_MIN_AREA = 16.0     # o laço confere e desfaz se vazar; lasca sem brush de outra textura no plano fica pro lint
PHANTOM_ROUNDS = 2


def _fix_phantoms(real: Path, opts: list[str], out: Path) -> tuple[int, dict]:
    """Faces do mundo desenhadas errado (fantasma: superfície que não existe no VMF; vazada: textura de outro brush
    coplanar). Causa no vbsp: FindPortalSide usa a textura da primeira face coplanar da folha. Conserto: no plano
    do problema, os brushes de mundo de textura minoritária viram func_detail (faces próprias, sem esse caminho),
    só no build/, e recompila com as mesmas opções; até 2 rodadas, volta pro anterior se falhar ou vazar."""
    from hammertools import bspcheck
    saved = [".bsp", ".prt", ".lin", ".log", ".vmf"]
    rep = {"found": 0, "detail": [], "left": 0}

    def problems():
        return [f for f in bspcheck.world_face_problems(vmfio.load(out), out.with_suffix(".bsp")) if f["area"] >= PHANTOM_MIN_AREA]
    try:
        found = problems()
    except Exception as e:  # BSP ilegível: não arrisca
        return 0, {"erro": str(e)}
    rep["found"] = rep["left"] = len(found)
    for _ in range(PHANTOM_ROUNDS):
        if not found:
            break
        for f in found:
            c = f["center"]
            what = "fantasma" if f["kind"] == "fantasma" else f"vazada (devia ser {f['expected']})"
            print(f"ht-vbsp: face {what} {f['material']} (~{f['area']:.0f}u²) em setpos {c.x:.0f} {c.y:.0f} {c.z + 64:.0f}", flush=True)
        v = vmfio.load(out)
        ids = bspcheck.detail_candidates(v, found)
        if not ids:
            print("ht-vbsp: nenhum brush de mundo pra separar ali; fica pro lint.", flush=True)
            break
        for ext in saved:  # guarda o resultado bom atual
            if out.with_suffix(ext).exists():
                shutil.copy2(out.with_suffix(ext), out.with_name(out.stem + "_ok" + ext))
        bspcheck.to_detail(v, ids)
        vmfio.save(v, out)
        print(f"ht-vbsp: {len(ids)} acabamento(s) de mundo -> func_detail ({', '.join(map(str, ids))}); recompilando.", flush=True)
        rc, text = _run_streaming([str(real), *opts, str(out.with_suffix(""))])
        low = text.lower()
        if rc != 0 or not out.with_suffix(".bsp").exists() or "too many" in low or "leaked" in low:
            print("ht-vbsp: a recompilação falhou ou vazou; fico com a compilação anterior.", flush=True)
            for ext in saved:
                f = out.with_name(out.stem + "_ok" + ext)
                if f.exists():
                    shutil.move(f, out.with_suffix(ext))
            return 0, rep
        rep["detail"] += ids
        found = problems()
        rep["left"] = len(found)
    for ext in saved:
        f = out.with_name(out.stem + "_ok" + ext)
        if f.exists():
            f.unlink()
    if rep["found"]:
        print(f"ht-vbsp: faces do mundo com problema: {rep['found']} achada(s), {rep['left']} restante(s) (detail só no build/).", flush=True)
    return 0, rep


TJ_STEPS = (100, 200, 400, 800, 1600, 3200)
LIMIT = 65536            # índices de t-junction e vértices únicos (vbsp)
MAX_MODELS = 1024        # MAX_MAP_MODELS
TJ_INDEX_GOAL = 0.90     # meta: sobrar 10% de índices pra editar o mapa sem estourar de novo
TJ_VERT_CAP = 0.97       # trava: não passar de 97% dos vértices
TJ_MODEL_CAP = 0.90      # trava: não passar de 90% dos modelos


def _brush_models(v) -> int:
    """Modelos que o BSP vai ter: o mundo + cada entidade de brush (func_detail vira mundo, não conta)."""
    return 1 + sum(1 for e in v.entities if e.solids and e["classname"] != "func_detail")


def _fix_tjunctions(real: Path, args: list[str], out: Path) -> tuple[int, dict]:
    """Estourou o teto de t-junctions: converte os func_detail que mais custam em func_brush (a BSP do modelo corta
    as faces e a t-junction some), dobrando a quantidade. Não para no primeiro que compila: segue até sobrar 10% de
    índices, respeitando as travas de vértices (97%) e modelos (90%, previsto antes de compilar e conferido no BSP).
    Fica com a melhor tentativa que compilou; nenhuma = -notjunc. Mexe só no build/, nunca no fonte."""
    from hammertools import optimize
    from hammertools.lint import bsp_counts
    base = out.with_name(out.stem + "_base.vmf")
    shutil.copy2(out, base)
    v0 = vmfio.load(base)
    ranked = optimize.rank_detail_tjunctions(v0)
    models0 = _brush_models(v0)
    print(f"\nht-vbsp: estourou o teto de t-junctions do vbsp ({LIMIT} índices). {len(ranked)} func_detail causam t-junctions;\n"
          "ht-vbsp: convertendo os piores em func_brush (a BSP do modelo corta as faces) e recompilando.\n"
          f"ht-vbsp: meta: índices <= {TJ_INDEX_GOAL:.0%}; travas: vértices <= {TJ_VERT_CAP:.0%}, modelos <= {TJ_MODEL_CAP:.0%} de {MAX_MODELS}.\n", flush=True)
    best = None   # (k, n, contagens)
    saved = [".bsp", ".prt", ".lin", ".log"]
    tried = 0
    for k in TJ_STEPS + (len(ranked),):
        k = min(k, len(ranked))
        if k <= tried:
            continue
        tried = k
        v = vmfio.load(base)
        n = optimize.detail_to_brush(v, ranked[:k])
        predicted = models0 + n
        if predicted > TJ_MODEL_CAP * MAX_MODELS:
            print(f"ht-vbsp: {k} func_detail daria {predicted} modelos (trava {int(TJ_MODEL_CAP * MAX_MODELS)}); paro aqui.", flush=True)
            break
        vmfio.save(v, out)
        print(f"ht-vbsp: tentativa: {k} func_detail -> {n} func_brush (~{predicted} modelos)", flush=True)
        rc, text = _run_streaming([str(real), *args[:-1], str(out.with_suffix(""))])
        low = text.lower()
        if "too many t-junctions" in low:
            continue
        if not (rc == 0 and out.with_suffix(".bsp").exists() and "too many" not in low and "max_map" not in low):
            print("ht-vbsp: estourou outro teto do vbsp; mais conversão só piora.", flush=True)
            break
        try:
            c = bsp_counts(out.with_suffix(".bsp"))
        except Exception:
            c = {}
        if c and (c["vertices"] > TJ_VERT_CAP * LIMIT or c["models"] > TJ_MODEL_CAP * MAX_MODELS):
            print(f"ht-vbsp: compilou mas passou das travas (vértices {c['vertices']}, modelos {c['models']}); fico com a anterior.", flush=True)
            break
        best = (k, n, c)
        for ext in saved:  # guarda esta, a próxima tentativa sobrescreve
            f = out.with_suffix(ext)
            if f.exists():
                shutil.copy2(f, out.with_name(out.stem + "_best" + ext))
        shutil.copy2(out, out.with_name(out.stem + "_best.vmf"))
        if not c or c["indices"] <= TJ_INDEX_GOAL * LIMIT:
            break
        print(f"ht-vbsp: compilou com {c['indices']} índices ({c['indices'] / LIMIT:.0%}); buscando mais folga.", flush=True)
    if best is None:
        shutil.copy2(base, out)
        print("\nht-vbsp: não coube nos tetos do vbsp convertendo detail; recompilando com -notjunc.\n"
              "ht-vbsp: efeito colateral possível: brilhos finos nas emendas (veja a aba T-junctions do `ht lint --html`).\n", flush=True)
        rc, _ = _run_streaming([str(real), *args[:-1], "-notjunc", str(out.with_suffix(""))])
        return rc, {"result": "notjunc"}
    k, n, c = best
    for ext in saved + [".vmf"]:
        f = out.with_name(out.stem + "_best" + ext)
        if f.exists():
            shutil.move(f, out.with_suffix(ext))
    folga = (f": índices {c['indices']}/{LIMIT}, vértices {c['vertices']}/{LIMIT}, modelos {c['models']}/{MAX_MODELS}" if c else "")
    print(f"\nht-vbsp: t-junctions consertadas com {k} func_detail -> {n} func_brush{folga} "
          "(só no build/, o fonte continua com func_detail).\n", flush=True)
    chosen = set(ranked[:k])
    solids = [s.id for e in v0.by_class["func_detail"] if e.id in chosen for s in e.solids]
    return 0, {"result": "convertido", "func_detail": k, "func_brush": n, "solids": solids}


def vbsp_main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("uso: ht-vbsp [opções do vbsp] -game <gamedir> <path\\file>", file=sys.stderr)
        return 2
    map_arg = Path(args[-1])
    src = map_arg if map_arg.suffix.lower() == ".vmf" else map_arg.with_suffix(".vmf")
    gamedir = None
    for i, a in enumerate(args[:-1]):
        if a.lower() == "-game" and i + 1 < len(args):
            gamedir = Path(args[i + 1])
    real = _find_real_vbsp(gamedir)
    if real is None:
        print("ht-vbsp: não achei o vbsp.exe real (defina HT_VBSP)", file=sys.stderr)
        return 2

    out_dir = src.parent / "build"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / src.name
    # compile é o "check final": o fonte sai limpo de preview (desligue com HT_KEEP_PREVIEW=1)
    if os.environ.get("HT_KEEP_PREVIEW") != "1":
        n_prev = clear_preview(src)
        if n_prev:
            print(f"ht-vbsp: preview removido do fonte ({n_prev} objeto(s)); recarregue o mapa no Hammer++ antes de salvar de novo")
    n_groups, n_solids, warnings = build(src, out, str(gamedir) if gamedir else None)
    from hammertools.lint import active_cordon, hidden_count
    built = vmfio.load(out)
    n_hidden = hidden_count(built)
    if n_hidden:
        print(f"\nht-vbsp: AVISO: {n_hidden} objeto(s) oculto(s) no Hammer não serão compilados (mostre tudo com "
              "Ctrl+Shift+H se quiser o mapa inteiro).\n", flush=True)
    box = active_cordon(built)
    if box:
        print(f"\nht-vbsp: AVISO: cordon ativo, só a caixa {box[0]}..{box[1]} será compilada (o resto fica de fora e as bordas "
              "dão leak). Desligue em Map > Cordon se quiser o mapa inteiro.\n", flush=True)
    for w in warnings:
        print(f"ht-vbsp aviso: {w}", file=sys.stderr)
    print(f"ht-vbsp: {n_groups} marcador(es) -> {n_solids} brush(es) em {out}")

    # -onlyents precisa do .bsp anterior ao lado do vmf de entrada
    prev = src.with_suffix(".bsp")
    if prev.exists():
        shutil.copy2(prev, out.with_suffix(".bsp"))

    cmd = [str(real), *args[:-1], str(out.with_suffix(""))]
    rc, text = _run_streaming(cmd)
    notjunc = "-notjunc" in (a.lower() for a in args)
    info = {"result": "notjunc" if notjunc else "direto"}
    if "too many t-junctions" in text.lower() and not notjunc:
        rc, info = _fix_tjunctions(real, args, out)
    if rc == 0 and "-onlyents" not in (a.lower() for a in args) and os.environ.get("HT_NO_PHANTOM") != "1":
        extra = ["-notjunc"] if info.get("result") == "notjunc" and not notjunc else []
        rc, info["phantom"] = _fix_phantoms(real, [*args[:-1], *extra], out)
    # registro pro `ht lint` marcar quais t-junctions a compilação resolveu (<mapa>.tjfix.json ao lado do fonte)
    if rc == 0 and "-onlyents" not in (a.lower() for a in args):
        import json, time
        info["quando"] = time.strftime("%Y-%m-%d %H:%M")
        try:
            from hammertools.lint import bsp_counts
            info.update(bsp_counts(out.with_suffix(".bsp")))
        except Exception as e:  # BSP ilegível não impede o registro
            info["erro_bsp"] = str(e)
        src.with_suffix(".tjfix.json").write_text(json.dumps(info))
    for ext in (".bsp", ".prt", ".lin", ".log"):
        f = out.with_suffix(ext)
        if f.exists():
            shutil.copy2(f, src.with_suffix(ext))
    return rc

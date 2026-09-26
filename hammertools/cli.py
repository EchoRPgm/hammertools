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


def build(src: Path, out: Path, game: str | None = None) -> tuple[int, int, list[str]]:
    """Retorna (grupos processados, solids gerados, warnings)."""
    from hammertools.generators import fence
    fence.GAMEDIR = game
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
    vmfio.save(v, out)
    return len(groups), n_solids, warnings


def preview(src: Path, game: str | None = None) -> tuple[int, int, list[str]]:
    """Gera a geometria DENTRO do mapa fonte (visgroup ht_preview), sem esconder marcadores.
    Roda de novo = apaga o preview anterior e regenera. Retorna (grupos, solids, warnings)."""
    from hammertools.generators import fence
    fence.GAMEDIR = game
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
    n_groups, n_solids, warnings = build(src, out, args.game)
    for w in warnings:
        print(f"aviso: {w}", file=sys.stderr)
    print(f"{out}: {n_groups} marcador(es), {n_solids} brush(es) gerados")
    return 0


def cmd_lint(args) -> int:
    v = vmfio.load(args.vmf)
    problems: list[str] = []
    # marcadores incompletos
    for g in vmfio.group_markers(vmfio.markers(v)).values():
        if g.classname not in REGISTRY:
            continue
        if g.classname in SINGLE:
            if g.by_role("start") is None:
                problems.append(f"marcador {g.name} ({g.classname}) sem o marcador principal")
        elif g.by_role("start") is None or g.by_role("end") is None:
            problems.append(f"marcador {g.name} ({g.classname}) sem par start/end")
    # outputs apontando pra targetname inexistente (targetnames são case-insensitive no Source)
    names = {e["targetname"].lower() for e in v.entities if e.get("targetname")}
    classnames = {e["classname"].lower() for e in v.entities}
    for e in v.entities:
        for out in e.outputs:
            t = out.target
            if not t or t.startswith("!") or "*" in t:
                continue
            if t.lower() in names or t.lower() in classnames:
                continue
            problems.append(f"{e['classname']} '{e.get('targetname', '?')}' -> output {out.output} mira '{t}' que não existe")
    # brushes fora do grid (mundo e entidades), um aviso por solid
    grid = args.grid
    owners = [(s, "mundo") for s in v.brushes] + [(s, e["classname"]) for e in v.entities for s in e.solids]
    for s, owner in owners:
        bad = [side for side in s.sides if any(not vmfio.is_on_grid(c, grid) for p in side.planes for c in (p.x, p.y, p.z))]
        if bad:
            kind = "displacement" if any(side.is_disp for side in s.sides) else "brush"
            problems.append(f"{owner} solid {s.id} ({kind}): {len(bad)} face(s) fora do grid {grid}")
    for p in problems:
        print(p)
    print(f"{len(problems)} problema(s)")
    return 1 if problems else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ht", description="hammertools: marcadores ht_* -> geometria")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build", help="gera geometria dos marcadores num novo VMF")
    p.add_argument("vmf"); p.add_argument("-o", "--out"); p.add_argument("--game", help="pasta com gameinfo.txt (ou env HT_GAME) pra ler modelos"); p.set_defaults(fn=cmd_build)
    p = sub.add_parser("preview", help="gera a geometria dentro do próprio VMF fonte (visgroup ht_preview) pra ver no Hammer++")
    p.add_argument("vmf"); p.add_argument("--game", help="pasta com gameinfo.txt (ou env HT_GAME)")
    p.add_argument("--clear", action="store_true", help="só remove o visgroup ht_preview do fonte"); p.set_defaults(fn=cmd_preview)
    p = sub.add_parser("list-markers", help="lista marcadores ht_* do mapa")
    p.add_argument("vmf"); p.set_defaults(fn=cmd_list)
    p = sub.add_parser("lint", help="checagens pré-compile")
    p.add_argument("vmf"); p.add_argument("--grid", type=float, default=1.0); p.set_defaults(fn=cmd_lint)
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
    for w in warnings:
        print(f"ht-vbsp aviso: {w}", file=sys.stderr)
    print(f"ht-vbsp: {n_groups} marcador(es) -> {n_solids} brush(es) em {out}")

    # -onlyents precisa do .bsp anterior ao lado do vmf de entrada
    prev = src.with_suffix(".bsp")
    if prev.exists():
        shutil.copy2(prev, out.with_suffix(".bsp"))

    rc = subprocess.call([str(real), *args[:-1], str(out.with_suffix(""))])
    for ext in (".bsp", ".prt", ".lin", ".log"):
        f = out.with_suffix(ext)
        if f.exists():
            shutil.copy2(f, src.with_suffix(ext))
    return rc

"""`ht compile`: a compilação inteira do mapa (ht-vbsp, vvis, vrad, cópia para maps/, pack), sem depender do Hammer++.

Tudo o que a compilação precisa para sair certa fica aqui, e não na configuração de quem chama (EchoHammer, sequência do
Hammer++, linha de comando):
- vbsp pelo ht-vbsp (marcadores, leak, t-junctions, auto-prop, limite de coordenadas...);
- vvis e vrad do jogo (GarrysMod/bin ou bin/win64, pelo Wine fora do Windows), por um caminho só de minúsculas quando
  preciso: o vvis/vrad passam o caminho do mapa para minúsculas e o Z: do Wine diferencia ("Can't create LogFile");
- o vrad ganha -StaticPropLighting sozinho quando o BSP tem props do auto-prop: iluminado só pela origem (que fica
  dentro da própria colisão) o prop gerado sai preto; os outros props têm disablevertexlighting e não mudam;
- perfis como os do Hammer++: normal, rápido (vvis -fast, vrad -bounce 2 -noextra) e final (vrad -final ...).
"""
from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

PROP_LIGHT = ["-StaticPropLighting"]   # só os props gerados usam (os outros saem com disablevertexlighting)
RAD_PROFILES = {"normal": [], "rapido": ["-bounce", "2", "-noextra"],
                "final": ["-final", "-StaticPropLighting", "-StaticPropPolys", "-TextureShadows"]}


def find_tool(gamedir: Path, name: str) -> Path | None:
    """vvis/vrad do jogo, ao lado do vbsp real (HT_VVIS/HT_VRAD mandam)."""
    env = os.environ.get(f"HT_{name.upper()}")
    if env and Path(env).exists():
        return Path(env)
    for rel in (f"bin/win64/{name}.exe", f"bin/{name}.exe", f"bin/win64/{name}", f"bin/{name}"):
        cand = gamedir.parent / rel
        if cand.exists():
            return cand
    return None


def wine_safe_dir(d: Path) -> Path:
    """Pasta do mapa para .exe pelo Wine: com maiúscula no caminho, um link só de minúsculas para a pasta real."""
    d = d.resolve()
    if os.name == "nt" or str(d) == str(d).lower():
        return d
    root = Path(tempfile.gettempdir()) / "ht-wine"
    root.mkdir(parents=True, exist_ok=True)
    link = root / f"{d.name.lower()}-{hashlib.sha1(str(d).encode()).hexdigest()[:8]}"
    if link.is_symlink() and Path(os.readlink(link)) != d:
        link.unlink()
    if not link.exists():
        link.symlink_to(d, target_is_directory=True)
    return link


def install_bsp(bsp: Path, dest: Path) -> None:
    """Copia o .bsp para maps/ sem sobrescrever no lugar: grava ao lado e troca de uma vez (rename). Sobrescrever com o
    mapa aberto no jogo fazia o motor ler os modelos do pakfile nas posições do arquivo antigo ("Error Vertex File ...
    id N should be 1448297545", que é o "IDSV" do .vvd). Com a troca, quem está com o mapa aberto segue no antigo inteiro
    e a próxima carga pega o novo inteiro."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.novo")
    shutil.copy2(bsp, tmp)
    try:
        os.replace(tmp, dest)
    except PermissionError:
        tmp.unlink(missing_ok=True)       # Windows: o jogo com o mapa aberto trava o arquivo
        raise RuntimeError(f"{dest} está em uso (mapa aberto no jogo?): feche o mapa e copie de novo")


def has_generated_props(bsp: Path) -> bool:
    from hammertools import autoprop
    try:
        return any(f"/{autoprop.MODEL_DIR}/" in m for m in autoprop.bsp_static_models(bsp))
    except (OSError, ValueError, IndexError):
        return False


def rad_args(profile: str, bsp: Path, extra: list[str]) -> list[str]:
    args = list(RAD_PROFILES[profile])
    if has_generated_props(bsp):
        args += [a for a in PROP_LIGHT if a not in args and a not in extra]
    return args + extra


def run(vmf: Path, game: Path, vis: str = "full", rad: str = "normal", ht_flags: list[str] | None = None,
        vbsp_args: list[str] | None = None, vis_args: list[str] | None = None, rad_args_extra: list[str] | None = None,
        copy: bool = True, pack: bool = False) -> int:
    from hammertools import cli
    vmf = vmf.resolve()
    noext = vmf.with_suffix("")
    bsp = vmf.with_suffix(".bsp")
    say = lambda m: print(f"ht compile: {m}", flush=True)

    say(f"vbsp (ht-vbsp) de {vmf.name}")
    # perfil final: luz por vértice em todos os props (como no Hammer++); senão só nos gerados pelo auto-prop
    if rad == "final":
        os.environ["HT_ALL_PROP_LIGHT"] = "1"
    else:
        os.environ.pop("HT_ALL_PROP_LIGHT", None)
    rc = cli.vbsp_main([*(ht_flags or []), *(vbsp_args or []), "-game", str(game), str(noext)])
    if rc != 0 or not bsp.exists():
        say(f"vbsp falhou (saída {rc}); parado")
        return rc or 1
    target = wine_safe_dir(vmf.parent) / vmf.stem
    tool_target = lambda exe: str(target) if str(exe).lower().endswith(".exe") else str(noext)
    if vis != "off":
        vvis = find_tool(game, "vvis")
        if vvis is None:
            say("vvis não encontrado ao lado do vbsp (defina HT_VVIS)")
            return 2
        args = [str(vvis), *(["-fast"] if vis == "fast" else []), *(vis_args or []), "-game", str(game), tool_target(vvis)]
        say("vvis " + " ".join(args[1:-3]))
        rc, _ = cli._run_streaming(args)
        if rc != 0:
            say(f"vvis falhou (saída {rc}); parado")
            return rc
    if rad != "off":
        vrad = find_tool(game, "vrad")
        if vrad is None:
            say("vrad não encontrado ao lado do vbsp (defina HT_VRAD)")
            return 2
        flags = rad_args(rad, bsp, rad_args_extra or [])
        say("vrad " + " ".join(flags))
        rc, _ = cli._run_streaming([str(vrad), *flags, "-game", str(game), tool_target(vrad)])
        if rc != 0:
            say(f"vrad falhou (saída {rc}); parado")
            return rc
    if pack:
        say("ht pack")
        rc = cli.main(["pack", str(vmf), "--game", str(game), "--bsp", str(bsp), "--out", str(bsp)])
        if rc != 0:
            say("ht pack falhou; o BSP segue sem o conteúdo embutido")
    if copy:
        dest = game / "maps" / bsp.name
        install_bsp(bsp, dest)
        say(f"copiado para {dest}")
    say("pronto")
    return 0


def cmd_compile(args) -> int:
    from hammertools import cli, lint
    game = lint._find_game(args.game)
    if game is None:
        print("pasta do jogo não encontrada (use --game)", file=sys.stderr)
        return 2
    ht_flags = [f for f in cli.VBSP_FLAGS if getattr(args, f.lstrip("-").replace("-", "_"), False)]
    return run(Path(args.vmf), Path(game), args.vis, args.rad, ht_flags, shlex.split(args.vbsp_args or ""),
               shlex.split(args.vis_args or ""), shlex.split(args.rad_args or ""), not args.no_copy, args.pack)


def add_parser(sub) -> None:
    from hammertools import cli
    p = sub.add_parser("compile", help="compila o mapa inteiro (ht-vbsp, vvis, vrad, cópia para maps/) sem depender do Hammer++")
    p.add_argument("vmf")
    p.add_argument("--game", help="pasta com gameinfo.txt (padrão: HT_GAME ou a instalação do GMod)")
    p.add_argument("--vis", choices=["full", "fast", "off"], default="full")
    p.add_argument("--rad", choices=["normal", "rapido", "final", "off"], default="normal",
                   help="normal; rapido (-bounce 2 -noextra); final (-final -StaticPropLighting -StaticPropPolys -TextureShadows)")
    p.add_argument("--vbsp-args", help="argumentos extras do vbsp (entre aspas)")
    p.add_argument("--vis-args", help="argumentos extras do vvis")
    p.add_argument("--rad-args", help="argumentos extras do vrad")
    p.add_argument("--no-copy", action="store_true", help="não copia o .bsp para <jogo>/maps")
    p.add_argument("--pack", action="store_true", help="embute no BSP o conteúdo que o GMod base não tem (ht pack)")
    for f, (_, _, desc) in cli.VBSP_FLAGS.items():
        p.add_argument(f, action="store_true", help=desc)
    p.set_defaults(fn=cmd_compile)

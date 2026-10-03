"""`ht setup`: integra o hammertools ao Hammer++ do GMod (Windows).

- FGD em `bin/win64/hammerplusplus/hammertools.fgd`, convertido pra cp1252 (o Hammer++ não lê UTF-8);
- `ht-lint.cmd` ao lado do `ht.exe` (o Hammer passa `$path\\$file` com espaço no fim e sem extensão);
- gameconfig do Hammer++: "BSP" do jogo do GMod aponta pro `ht-vbsp.exe` (que chama o vbsp real) e o FGD entra nos
  GameDataN;
- sequências "ht lint" (grava <mapa>.lin se houver leak) e "ht final" (vbsp do gameconfig, que deve ser o
  ht-vbsp; vvis completo; vrad -final com luz por vértice nos props; cópia pro maps) em
  `hammerplusplus_sequences.cfg`, só se ainda não existirem (não sobrescreve ajustes do usuário).

Idempotente; o `ht update` roda `ht setup --refresh` depois de instalar (atualiza o FGD; sem Hammer++ não faz nada).
O Hammer++ só relê FGD e sequências ao reabrir.
"""
from __future__ import annotations

import re
import shutil
import sys
from importlib import resources
from pathlib import Path

SEQ_FILE = "hammerplusplus_sequences.cfg"
HEADER = re.compile(r'^("Command Sequences"\s*\r?\n\{\r?\n)')

LINT_CMD = ('@echo off\r\nsetlocal\r\nset "in=%*"\r\nset "in=%in:"=%"\r\n:trim\r\n'
            'if "%in:~-1%"==" " (set "in=%in:~0,-1%" & goto trim)\r\n'
            '"%~dp0ht.exe" lint "%in%.vmf" --pointfile --game "{gamedir}"\r\n')


def _step(i: int, special: int, run: str | None, parms: str) -> str:
    r = f'\t\t\t"run"\t\t"{run}"\r\n' if run else ""
    return (f'\t\t"{i}"\r\n\t\t{{\r\n\t\t\t"enable"\t\t"1"\r\n\t\t\t"specialcmd"\t\t"{special}"\r\n{r}'
            f'\t\t\t"parms"\t\t"{parms}"\r\n\t\t}}\r\n')


def _sequence(name: str, steps: list[str]) -> str:
    return f'\t"{name}"\r\n\t{{\r\n' + "".join(steps) + "\t}\r\n"


def sequences(lint_cmd: Path) -> dict[str, str]:
    g = "-game $gamedir $path\\$file"
    return {
        "ht lint": _sequence("ht lint", [_step(1, 0, str(lint_cmd), "$path\\$file")]),
        "ht final": _sequence("ht final", [
            _step(0, 0, "$bsp_exe", g),
            _step(1, 0, "$vis_exe", g),
            _step(2, 0, "$light_exe", "-final -StaticPropLighting -StaticPropPolys -TextureShadows " + g),
            _step(3, 257, None, "$path\\$file.bsp $bspdir\\$file.bsp"),
        ]),
    }


def add_sequences(cfg: str, seqs: dict[str, str]) -> tuple[str, list[str]]:
    """Insere as sequências que faltam logo após o cabeçalho. Devolve (texto, nomes adicionados)."""
    added = []
    for name, block in seqs.items():
        if f'"{name}"' in cfg:
            continue
        if not HEADER.search(cfg):
            raise ValueError(f"{SEQ_FILE} sem o cabeçalho \"Command Sequences\"")
        cfg = HEADER.sub(lambda m: m.group(1) + block, cfg, count=1)
        added.append(name)
    return cfg, added


GAMECONFIG = "hammerplusplus_gameconfig.txt"
_TOKEN = re.compile(r'"([^"]*)"|(\{)|(\})')


def _kv_pairs(text: str):
    """Pares chave/valor do KeyValues do gameconfig: (caminho de blocos, chave, valor, início, fim do valor).
    Os caminhos usam \\ sem escape (formato da Valve), por isso não passa pelo parser do srctools."""
    stack: list[str] = []
    toks = [(m.group(1), m.group(2), m.group(3), m.start(1), m.end(1)) for m in _TOKEN.finditer(text)]
    i = 0
    while i < len(toks):
        s, ob, cb, a, b = toks[i]
        if cb:
            if stack:
                stack.pop()
            i += 1
            continue
        if ob or i + 1 >= len(toks):
            i += 1
            continue
        nxt = toks[i + 1]
        if nxt[1]:                       # "chave" {
            stack.append(s)
            i += 2
        elif nxt[0] is not None:         # "chave" "valor"
            yield tuple(stack), s, nxt[0], nxt[3], nxt[4]
            i += 2
        else:
            i += 1


def _same_path(a: str, b: Path) -> bool:
    norm = lambda x: str(x).replace("/", "\\").rstrip("\\").lower()
    return norm(a) == norm(b)


def patch_gameconfig(text: str, gamedir: Path, vbsp: Path, fgd: Path) -> tuple[str, list[str]]:
    """No jogo cujo GameDir é `gamedir`: BSP -> ht-vbsp e o FGD do hammertools nos GameDataN. Só texto mexido
    é o necessário (o resto do arquivo fica igual)."""
    pairs = list(_kv_pairs(text))
    games = {path[2] for path, key, val, _a, _b in pairs
             if len(path) == 3 and path[:2] == ("Configs", "Games") and key == "GameDir" and _same_path(val, gamedir)}
    edits: list[tuple[int, int, str]] = []
    changes: list[str] = []
    for game in sorted(games):
        hpairs = [(k, v, a, b) for path, k, v, a, b in pairs if path == ("Configs", "Games", game, "Hammer")]
        bsp = next(((v, a, b) for k, v, a, b in hpairs if k == "BSP"), None)
        if bsp and not _same_path(bsp[0], vbsp):
            edits.append((bsp[1], bsp[2], str(vbsp)))
            changes.append(f"{game}: BSP {bsp[0]} -> {vbsp}")
        datas = [(k, v, a, b) for k, v, a, b in hpairs if k.lower().startswith("gamedata")]
        if datas and not any(Path(v.replace("\\", "/")).name.lower() == fgd.name.lower() for _k, v, _a, _b in datas):
            last = max(datas, key=lambda d: d[3])
            n = 1 + max(int("".join(c for c in k if c.isdigit()) or 0) for k, *_ in datas)
            line_start = text.rfind("\n", 0, last[2]) + 1
            indent = re.match(r"[ \t]*", text[line_start:]).group(0)
            line_end = text.find("\n", last[3])
            line_end = len(text) if line_end < 0 else line_end + 1
            nl = "\r\n" if text[line_end - 2:line_end] == "\r\n" else "\n"
            edits.append((line_end, line_end, f'{indent}"GameData{n}"\t\t"{fgd}"{nl}'))
            changes.append(f"{game}: FGD GameData{n} = {fgd}")
    for a, b, rep in sorted(edits, reverse=True):
        text = text[:a] + rep + text[b:]
    return text, changes


def hammer_dir(game_root: Path) -> Path:
    return game_root / "bin" / "win64" / "hammerplusplus"


def find_game_root(game: str | None) -> Path | None:
    """Pasta GarrysMod (a que tem bin/ e garrysmod/). Aceita a raiz ou a pasta garrysmod (gameinfo.txt)."""
    from hammertools.lint import _find_game
    if game:
        p = Path(game)
        if (p / "garrysmod" / "gameinfo.txt").exists():
            return p
        if (p / "gameinfo.txt").exists():
            return p.parent
    gamedir = _find_game(None)
    return gamedir.parent if gamedir else None


def fgd_bytes() -> bytes:
    text = resources.files("hammertools").joinpath("hammertools.fgd").read_text(encoding="utf-8")
    return text.encode("cp1252")


def setup(game_root: Path, bin_dir: Path, log=print) -> bool:
    hdir = hammer_dir(game_root)
    if not hdir.is_dir():
        log(f"ht setup: Hammer++ não encontrado em {hdir}")
        return False
    (hdir / "hammertools.fgd").write_bytes(fgd_bytes())
    log(f"FGD: {hdir / 'hammertools.fgd'}")
    lint_cmd = bin_dir / "ht-lint.cmd"
    lint_cmd.write_bytes(LINT_CMD.format(gamedir=game_root / "garrysmod").encode("ascii", "replace"))
    log(f"atalho do lint: {lint_cmd}")
    gc = hdir / GAMECONFIG
    vbsp = bin_dir / "ht-vbsp.exe"
    if gc.exists():
        raw = gc.read_bytes().decode("cp1252")
        new, changes = patch_gameconfig(raw, game_root / "garrysmod", vbsp, hdir / "hammertools.fgd")
        if changes:
            shutil.copy2(gc, gc.with_suffix(".txt.bak"))
            gc.write_bytes(new.encode("cp1252"))
        log("gameconfig: " + ("; ".join(changes) if changes else "já usa o ht-vbsp e o FGD") + f" ({gc})")
    else:
        log(f"gameconfig: {gc} não existe (abra o Hammer++ uma vez, feche e rode `ht setup` de novo)")
    cfg_path = hdir / SEQ_FILE
    if cfg_path.exists():
        raw = cfg_path.read_bytes().decode("cp1252")
        new, added = add_sequences(raw, sequences(lint_cmd))
        if added:
            shutil.copy2(cfg_path, cfg_path.with_suffix(".cfg.bak"))
            cfg_path.write_bytes(new.encode("cp1252"))
        log(f"sequências: {', '.join(added) if added else 'já estavam lá'} ({cfg_path})")
    else:
        log(f"sequências: {cfg_path} não existe (abra o Hammer++ uma vez e rode `ht setup` de novo)")
    return True


def cmd_setup(args) -> int:
    root = find_game_root(args.game)
    if root is None:
        if args.refresh:
            return 0        # depois de um update, máquina sem GMod (ex.: Linux): nada a integrar
        print("ht setup: não achei o GMod; passe --game <pasta GarrysMod>", file=sys.stderr)
        return 1
    bin_dir = Path(shutil.which("ht") or sys.argv[0]).resolve().parent
    ok = setup(root, bin_dir)
    if ok:
        print("pronto; reabra o Hammer++ (com ele aberto, ele regrava o gameconfig ao fechar e desfaz a mudança)")
    return 0 if ok or args.refresh else 1

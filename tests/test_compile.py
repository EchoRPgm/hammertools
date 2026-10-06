import os
import stat
import sys
from pathlib import Path

from hammertools import compile as htc
from hammertools.core import vmf as vmfio


def _tool(path: Path, log: Path, writes_bsp: bool = False) -> Path:
    """Compilador falso: anota os argumentos (e o vbsp cria o .bsp)."""
    body = f'#!/bin/sh\necho "$(basename "$0") $*" >> "{log}"\n'
    if writes_bsp:
        body += 'for a in "$@"; do last="$a"; done\necho bsp > "$last.bsp"\n'
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def test_compile_runs_vbsp_vis_rad_with_profile_and_copies(room, tmp_path, monkeypatch):
    game = tmp_path / "GarrysMod" / "garrysmod"
    (game.parent / "bin").mkdir(parents=True)
    log = tmp_path / "log.txt"
    vbsp = _tool(game.parent / "bin" / "vbsp", log, writes_bsp=True)
    _tool(game.parent / "bin" / "vvis", log)
    _tool(game.parent / "bin" / "vrad", log)
    src = tmp_path / "Mapas" / "m.vmf"            # pasta com maiúscula (o caminho só de minúsculas é para o Wine)
    src.parent.mkdir()
    vmfio.save(room, src)
    monkeypatch.setenv("HT_VBSP", str(vbsp))
    for k in ("HT_NO_PHANTOM", "HT_NO_UPDATE", "HT_AUTOPROP"):
        monkeypatch.setenv(k, "1" if k != "HT_AUTOPROP" else "0")
    monkeypatch.setattr(htc, "has_generated_props", lambda bsp: True)
    rc = htc.run(src, game, vis="fast", rad="rapido")
    assert rc == 0
    steps = log.read_text().splitlines()
    names = [s.split()[0] for s in steps]
    assert names == ["vbsp", "vvis", "vrad"]
    assert "-fast" in steps[1]
    # perfil rápido + luz por vértice por causa dos props gerados (sem mexer na sombra dos outros props)
    assert "-bounce 2 -noextra -StaticPropLighting" in steps[2] and "-StaticPropPolys" not in steps[2]
    assert (game / "maps" / "m.bsp").exists()


def test_final_profile_does_not_repeat_prop_flags(monkeypatch, tmp_path):
    monkeypatch.setattr(htc, "has_generated_props", lambda bsp: True)
    args = htc.rad_args("final", tmp_path / "m.bsp", [])
    assert args.count("-StaticPropLighting") == 1 and "-final" in args
    monkeypatch.setattr(htc, "has_generated_props", lambda bsp: False)
    assert htc.rad_args("normal", tmp_path / "m.bsp", ["-bounce", "8"]) == ["-bounce", "8"]


def test_wine_safe_dir_is_lowercase_link_to_same_folder(tmp_path):
    if os.name == "nt":
        return
    d = tmp_path / "Projetos" / "Mapa"
    d.mkdir(parents=True)
    (d / "x.txt").write_text("ok")
    safe = htc.wine_safe_dir(d)
    assert str(safe) == str(safe).lower() and (safe / "x.txt").read_text() == "ok"
    assert htc.wine_safe_dir(d) == safe


def test_install_bsp_replaces_atomically_keeping_open_readers_on_old_file(tmp_path):
    """O jogo com o mapa aberto lia o pakfile novo nas posições do antigo: a troca é por rename (inode novo)."""
    if os.name == "nt":
        return
    dest = tmp_path / "maps" / "m.bsp"
    dest.parent.mkdir()
    dest.write_bytes(b"ANTIGO" * 10)
    reader = open(dest, "rb")                 # o jogo com o mapa aberto
    new = tmp_path / "m.bsp"
    new.write_bytes(b"NOVO")
    htc.install_bsp(new, dest)
    assert dest.read_bytes() == b"NOVO"
    assert reader.read() == b"ANTIGO" * 10     # quem já tinha aberto continua no arquivo antigo inteiro
    reader.close()
    assert not list(dest.parent.glob(".*novo"))

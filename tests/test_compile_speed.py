"""Atalhos de tempo da compilação: têm de dar o mesmo resultado do caminho longo."""
import json
import sys

from hammertools import seal
from hammertools.cli import vbsp_main
from hammertools.core import vmf as vmfio


def _room_with_hole(tmp_path):
    from test_seal import _room
    src = tmp_path / "mapsrc" / "m.vmf"
    src.parent.mkdir()
    vmfio.save(_room(hole=True), src)
    return src


def test_leak_rounds_use_leaktest_and_unsealed_map_still_gets_a_bsp(tmp_path, monkeypatch, capsys):
    """Passada que vaza para no leak (-leaktest); sem selar, uma passada inteira no fim grava o BSP vazado."""
    src = _room_with_hole(tmp_path)
    fake = tmp_path / "vbsp.py"
    fake.write_text(
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[-1])\n"
        "log = p.with_name('calls.txt'); log.write_text((log.read_text() if log.exists() else '') + ('L' if '-leaktest' in sys.argv else 'F'))\n"
        "print('**** leaked ****')\n"
        "p.with_suffix('.lin').write_text('200 500 200\\n1008 512 96\\n1400 512 96\\n')\n"
        "if '-leaktest' not in sys.argv: p.with_suffix('.bsp').write_text('vazado')\n")
    monkeypatch.setenv("HT_VBSP", sys.executable)
    monkeypatch.setenv("HT_NO_PHANTOM", "1")
    monkeypatch.setattr(seal, "coarse_classifier", lambda *a, **k: None)
    monkeypatch.setattr(seal, "seal_at_pointfile", lambda *a, **k: [])
    vbsp_main([str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))])
    out = capsys.readouterr().out
    calls = (tmp_path / "mapsrc" / "build" / "calls.txt").read_text()
    assert calls.startswith("L") and calls.endswith("F") and "F" not in calls[:-1], calls
    assert "AINDA VAZA" in out and src.with_suffix(".bsp").read_text() == "vazado"


def test_no_seal_keeps_full_pass(tmp_path, monkeypatch):
    src = _room_with_hole(tmp_path)
    fake = tmp_path / "vbsp.py"
    fake.write_text("import sys, pathlib; p = pathlib.Path(sys.argv[-1]); p.with_suffix('.bsp').write_text(' '.join(sys.argv))")
    monkeypatch.setenv("HT_VBSP", sys.executable)
    monkeypatch.setenv("HT_NO_SEAL", "1")
    monkeypatch.setenv("HT_NO_PHANTOM", "1")
    assert vbsp_main([str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))]) == 0
    assert "-leaktest" not in src.with_suffix(".bsp").read_text()


# vbsp falso das t-junctions: conversão nunca cabe (o build tem func_brush), -notjunc compila; registra cada
# chamada pelo diretório onde rodou
FAKE_PAR = (
    "import sys, json, pathlib, time\n"
    "p = pathlib.Path(sys.argv[-1]); txt = p.with_suffix('.vmf').read_text()\n"
    "log = pathlib.Path({log!r}); log.write_text((log.read_text() if log.exists() else '') + p.parent.name + ('+nj' if '-notjunc' in sys.argv else '') + ';')\n"
    "if '-notjunc' in sys.argv: time.sleep({nj_sleep}); p.with_suffix('.bsp').write_text(json.dumps({{'notjunc': 1}})); sys.exit(0)\n"
    "conv = 4 - txt.count('\"func_detail\"')\n"
    "if conv == 0 or not {conv_ok}: print('Too many t-junctions to fix up! (1 prims, max 32768 :: 65550 indices, max 65536)'); sys.exit(1)\n"
    "p.with_suffix('.bsp').write_text(json.dumps({{'conv': conv, 'indices': 50000, 'vertices': 50000, 'models': 10, 'prims': 1, 'faces': 1}}))\n")


def _run_par(room, tmp_path, monkeypatch, conv_ok: bool, nj_sleep: float = 0.0):
    from hammertools import lint
    from test_vbsp_wrapper import _room_with_detail_tjunctions
    monkeypatch.setattr(lint, "bsp_counts", lambda p: json.loads(open(p).read()))
    src = tmp_path / "mapsrc" / "m.vmf"
    src.parent.mkdir()
    vmfio.save(_room_with_detail_tjunctions(room), src)
    log = tmp_path / "calls.txt"
    fake = tmp_path / "vbsp.py"
    fake.write_text(FAKE_PAR.format(log=str(log), conv_ok=conv_ok, nj_sleep=nj_sleep))
    monkeypatch.setenv("HT_VBSP", sys.executable)
    monkeypatch.delenv("HT_PARALLEL", raising=False)
    rc = vbsp_main([str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))])
    return rc, json.loads(src.with_suffix(".tjfix.json").read_text()), json.loads(src.with_suffix(".bsp").read_text()), log.read_text()


def test_tjfix_notjunc_spare_compiles_alongside_and_is_adopted(room, tmp_path, monkeypatch, capsys):
    rc, fix, bsp, calls = _run_par(room, tmp_path, monkeypatch, conv_ok=False)
    out = capsys.readouterr().out
    assert rc == 0 and fix["result"] == "notjunc" and bsp == {"notjunc": 1}
    assert "notjunc+nj;" in calls and calls.count("build;") == 2      # original + conversão; o -notjunc foi a reserva
    assert "já compilava em paralelo" in out
    build = tmp_path / "mapsrc" / "build"
    assert not (build / "paralelo").exists()
    assert "func_brush" not in (build / "m.vmf").read_text()            # o build volta ao original, como em série


def test_tjfix_spare_is_dropped_when_conversion_fits(room, tmp_path, monkeypatch):
    rc, fix, bsp, calls = _run_par(room, tmp_path, monkeypatch, conv_ok=True, nj_sleep=30)
    assert rc == 0 and fix["result"] == "convertido" and bsp["conv"] >= 1
    assert not (tmp_path / "mapsrc" / "build" / "paralelo").exists()


def test_tjfix_serial_when_parallel_disabled(room, tmp_path, monkeypatch):
    monkeypatch.setenv("HT_PARALLEL", "0")
    from hammertools import cli
    monkeypatch.setattr(cli, "_parallel_enabled", lambda: False)
    rc, fix, bsp, calls = _run_par(room, tmp_path, monkeypatch, conv_ok=False)
    assert fix["result"] == "notjunc" and bsp == {"notjunc": 1} and calls == "build;build;build+nj;"


def test_game_resources_built_once_per_process(tmp_path):
    from hammertools import lint
    gd = tmp_path / "garrysmod"
    gd.mkdir()
    (gd / "gameinfo.txt").write_text('"GameInfo"\n{\n"game" "x"\n"FileSystem"\n{\n"SearchPaths"\n{\n"game" "|gameinfo_path|."\n}\n}\n}\n')
    a = lint.Resources.from_game(str(gd), None, ())
    assert lint.Resources.from_game(str(gd), None, ()) is a
    assert lint.Resources.from_game(str(gd), None, (str(tmp_path),)) is not a    # pasta extra: monta de novo

import os, stat, sys
from pathlib import Path

from hammertools.cli import vbsp_main
from hammertools.core import vmf as vmfio
from conftest import gen_solids, all_solids


def test_wrapper_builds_and_calls_real_vbsp(room, tmp_path, monkeypatch):
    room.create_ent("ht_stairs", origin="0 0 0", targetname="e")
    room.create_ent("ht_stairs_end", origin="128 0 64", targetname="e")
    src = tmp_path / "mapsrc" / "m.vmf"; src.parent.mkdir()
    vmfio.save(room, src)
    # vbsp falso: registra args e cria um .bsp ao lado do vmf que recebeu
    fake = tmp_path / "vbsp.py"
    fake.write_text("import sys, pathlib; p = pathlib.Path(sys.argv[-1]); p.with_suffix('.bsp').write_text(' '.join(sys.argv[1:])); p.with_suffix('.prt').write_text('prt')")
    monkeypatch.setenv("HT_VBSP", sys.executable)
    # HT_VBSP aponta pro python; passamos o script como primeira "opção" do vbsp
    rc = vbsp_main([str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))])
    assert rc == 0
    built = tmp_path / "mapsrc" / "build" / "m.vmf"
    assert built.exists() and len(all_solids(vmfio.load(built))) == 6 + 8 + 1  # sala + degraus + playerclip
    assert src.with_suffix(".bsp").read_text().endswith(str(built.with_suffix("")))
    assert src.with_suffix(".prt").exists()


def test_wrapper_clears_preview_from_source(room, tmp_path, monkeypatch):
    from hammertools.cli import preview
    room.create_ent("ht_stairs", origin="0 0 0", targetname="e", playerclip="0")
    room.create_ent("ht_stairs_end", origin="128 0 64", targetname="e")
    src = tmp_path / "mapsrc" / "m.vmf"; src.parent.mkdir()
    vmfio.save(room, src)
    preview(src)
    assert len(all_solids(vmfio.load(src))) == 6 + 8
    fake = tmp_path / "vbsp.py"
    fake.write_text("import sys, pathlib; pathlib.Path(sys.argv[-1]).with_suffix('.bsp').write_text('x')")
    monkeypatch.setenv("HT_VBSP", sys.executable)
    monkeypatch.delenv("HT_KEEP_PREVIEW", raising=False)
    assert vbsp_main([str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))]) == 0
    v = vmfio.load(src)
    assert len(all_solids(v)) == 6 and all(vg.name != "ht_preview" for vg in v.vis_tree)   # fonte limpo
    assert len(all_solids(vmfio.load(tmp_path / "mapsrc" / "build" / "m.vmf"))) == 6 + 8    # build com a escada


def test_wrapper_retries_with_notjunc(room, tmp_path, monkeypatch, capsys):
    src = tmp_path / "mapsrc" / "m.vmf"; src.parent.mkdir()
    vmfio.save(room, src)
    fake = tmp_path / "vbsp.py"
    fake.write_text(
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[-1])\n"
        "if '-notjunc' not in sys.argv:\n"
        "    print('FixTjuncs...'); print('Too many t-junctions to fix up! (3382 prims, max 32768 :: 65556 indices, max 65536)'); sys.exit(1)\n"
        "p.with_suffix('.bsp').write_text('ok')\n")
    monkeypatch.setenv("HT_VBSP", sys.executable)
    rc = vbsp_main([str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))])
    out = capsys.readouterr().out
    assert rc == 0 and "recompilando com -notjunc" in out and src.with_suffix(".bsp").read_text() == "ok"

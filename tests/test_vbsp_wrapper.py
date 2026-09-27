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


def _room_with_detail_tjunctions(room):
    """Laje de detail com blocos de detail cujos cantos caem no meio das arestas dela."""
    from srctools import Vec
    from srctools.vmf import Entity
    slab = room.make_prism(Vec(-256, -64, 0), Vec(256, 64, 16), "dev/dev_measuregeneric01b").solid
    room.add_ent(Entity(room, {"classname": "func_detail"}, solids=[slab]))
    for x in (-160, -32, 96):
        blk = room.make_prism(Vec(x, 64, 0), Vec(x + 48, 96, 40), "dev/dev_measuregeneric01b").solid
        room.add_ent(Entity(room, {"classname": "func_detail"}, solids=[blk]))
    return room


FAKE_TJ = (
    "import sys, pathlib\n"
    "p = pathlib.Path(sys.argv[-1]); txt = p.with_suffix('.vmf').read_text()\n"
    "if '-notjunc' in sys.argv: p.with_suffix('.bsp').write_text('notjunc'); sys.exit(0)\n"
    "if 'func_brush' not in txt: print('Too many t-junctions to fix up! (1 prims, max 32768 :: 65556 indices, max 65536)'); sys.exit(1)\n"
    "{on_brush}\n"
    "p.with_suffix('.bsp').write_text('convertido')\n")


def test_wrapper_fixes_tjunctions_by_converting_detail(room, tmp_path, monkeypatch, capsys):
    src = tmp_path / "mapsrc" / "m.vmf"; src.parent.mkdir()
    vmfio.save(_room_with_detail_tjunctions(room), src)
    fake = tmp_path / "vbsp.py"
    fake.write_text(FAKE_TJ.format(on_brush=""))
    monkeypatch.setenv("HT_VBSP", sys.executable)
    rc = vbsp_main([str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))])
    out = capsys.readouterr().out
    assert rc == 0 and src.with_suffix(".bsp").read_text() == "convertido"
    assert "t-junctions consertadas" in out
    built = vmfio.load(tmp_path / "mapsrc" / "build" / "m.vmf")
    assert built.by_class["func_brush"] and all(e["vrad_brush_cast_shadows"] == "1" for e in built.by_class["func_brush"])
    assert not vmfio.load(src).by_class["func_brush"]  # fonte intocado
    import json
    fix = json.loads(src.with_suffix(".tjfix.json").read_text())
    assert fix["result"] == "convertido" and fix["solids"] and fix["func_brush"] >= 1


def test_wrapper_falls_back_to_notjunc_when_vertices_overflow(room, tmp_path, monkeypatch, capsys):
    src = tmp_path / "mapsrc" / "m.vmf"; src.parent.mkdir()
    vmfio.save(_room_with_detail_tjunctions(room), src)
    fake = tmp_path / "vbsp.py"
    fake.write_text(FAKE_TJ.format(on_brush="print('Too many unique verts, max = 65536 (map has too much brush geometry)'); sys.exit(1)"))
    monkeypatch.setenv("HT_VBSP", sys.executable)
    rc = vbsp_main([str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))])
    out = capsys.readouterr().out
    assert rc == 0 and src.with_suffix(".bsp").read_text() == "notjunc" and "recompilando com -notjunc" in out
    assert not vmfio.load(tmp_path / "mapsrc" / "build" / "m.vmf").by_class["func_brush"]  # build volta ao original
    import json
    assert json.loads(src.with_suffix(".tjfix.json").read_text())["result"] == "notjunc"


def test_rank_and_convert_detail():
    from srctools import VMF
    from hammertools import optimize
    v = _room_with_detail_tjunctions(VMF())
    slab = next(e for e in v.by_class["func_detail"] if e.solids[0].get_bbox()[1].x - e.solids[0].get_bbox()[0].x > 400)
    ranked = optimize.rank_detail_tjunctions(v)
    assert ranked[0] == slab.id  # a laje recebe os vértices dos 3 blocos: é a que mais custa
    n = optimize.detail_to_brush(v, ranked)
    # blocos com centro em x < 0 caem no bloco de área vizinho: 2 func_brush, todos os solids preservados
    assert n == len(v.by_class["func_brush"]) == 2 and sum(len(e.solids) for e in v.by_class["func_brush"]) == len(ranked)
    assert not v.by_class["func_detail"]


FAKE_COUNTS = (
    "import sys, json, pathlib\n"
    "p = pathlib.Path(sys.argv[-1]); txt = p.with_suffix('.vmf').read_text()\n"
    "log = p.with_name('calls.txt'); log.write_text(log.read_text() + 'x' if log.exists() else 'x')\n"
    "if '-notjunc' in sys.argv: p.with_suffix('.bsp').write_text(json.dumps({'notjunc': 1})); sys.exit(0)\n"
    "conv = 4 - txt.count('\"func_detail\"')\n"
    "idx = 70000 - 5000 * conv\n"
    "if idx > 65536: print('Too many t-junctions to fix up! (1 prims, max 32768 :: 65550 indices, max 65536)'); sys.exit(1)\n"
    "p.with_suffix('.bsp').write_text(json.dumps({'conv': conv, 'indices': idx, 'vertices': 50000, 'models': {models}, 'prims': 1, 'faces': 1}))\n")


def _run_counts(room, tmp_path, monkeypatch, models_expr, **patch):
    import json
    from hammertools import cli, lint
    monkeypatch.setattr(cli, "TJ_STEPS", (1, 2, 3))
    for k, val in patch.items():
        monkeypatch.setattr(cli, k, val)
    monkeypatch.setattr(lint, "bsp_counts", lambda p: json.loads(Path(p).read_text()))
    src = tmp_path / "mapsrc" / "m.vmf"; src.parent.mkdir()
    vmfio.save(_room_with_detail_tjunctions(room), src)
    fake = tmp_path / "vbsp.py"
    fake.write_text(FAKE_COUNTS.replace("{models}", models_expr))
    monkeypatch.setenv("HT_VBSP", sys.executable)
    rc = vbsp_main([str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))])
    return rc, json.loads(src.with_suffix(".tjfix.json").read_text()), json.loads(src.with_suffix(".bsp").read_text()), tmp_path / "mapsrc" / "build" / "calls.txt"


def test_tjfix_keeps_converting_until_index_margin(room, tmp_path, monkeypatch):
    # 1 convertido: 65000 índices (passa, mas 99%); 2: 60000 (92%); 3: 55000 (84%) -> para no 3
    rc, fix, bsp, _ = _run_counts(room, tmp_path, monkeypatch, "10")
    assert rc == 0 and fix["func_detail"] == 3 and bsp["conv"] == 3 and bsp["indices"] == 55000


def test_tjfix_model_cap_keeps_best_previous(room, tmp_path, monkeypatch):
    # modelos crescem 100 por conversão: 1 -> 900 (<= 921), 2 -> 1000 (passa da trava) => fica com a de 1, arquivos restaurados
    rc, fix, bsp, _ = _run_counts(room, tmp_path, monkeypatch, "800 + 100 * conv")
    assert rc == 0 and fix["func_detail"] == 1 and bsp["conv"] == 1
    assert "func_brush" in (tmp_path / "mapsrc" / "build" / "m.vmf").read_text()  # build = a tentativa escolhida


def test_tjfix_predicted_models_skip_compile(room, tmp_path, monkeypatch):
    # teto de modelos minúsculo: a previsão (mundo + 1 func_brush = 2 > 90% de 2) barra antes de compilar -> -notjunc
    rc, fix, bsp, calls = _run_counts(room, tmp_path, monkeypatch, "10", MAX_MODELS=2)
    assert rc == 0 and fix["result"] == "notjunc" and bsp == {"notjunc": 1}
    assert calls.read_text() == "xx"  # só a compilação original e a -notjunc: nenhuma tentativa de conversão


def _phantom(area=5000.0):
    from srctools import Vec
    pts = [Vec(64, -32, 0), Vec(64, 32, 0), Vec(64, 32, 96), Vec(64, -32, 96)]
    return {"face": 1, "material": "concrete/x", "area": area, "center": Vec(64, 0, 48), "normal": Vec(1, 0, 0), "points": pts}


def test_wrapper_covers_phantom_faces_with_hint(room, tmp_path, monkeypatch, capsys):
    import json
    from hammertools import bspcheck
    calls = {"n": 0}
    def fake_phantoms(v, bsp, min_area=16.0):
        calls["n"] += 1
        # antes do hint: uma face fantasma; depois (build com hint): nenhuma
        return [] if any(all(x.mat.lower() == "tools/toolshint" for x in s.sides) for s in v.brushes) else [_phantom()]
    monkeypatch.setattr(bspcheck, "phantom_faces", fake_phantoms)
    src = tmp_path / "mapsrc" / "m.vmf"; src.parent.mkdir()
    vmfio.save(room, src)
    fake = tmp_path / "vbsp.py"
    fake.write_text("import sys, pathlib; pathlib.Path(sys.argv[-1]).with_suffix('.bsp').write_text('ok')")
    monkeypatch.setenv("HT_VBSP", sys.executable)
    monkeypatch.delenv("HT_NO_PHANTOM", raising=False)
    assert vbsp_main([str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))]) == 0
    built = vmfio.load(tmp_path / "mapsrc" / "build" / "m.vmf")
    hints = [s for s in built.brushes if all(x.mat.lower() == "tools/toolshint" for x in s.sides)]
    assert len(hints) == 1
    lo, hi = hints[0].get_bbox()
    assert (lo.x, hi.x) == (56, 64) and (lo.y, hi.y) == (-32, 32)  # 8u pra trás da face (normal +x)
    fix = json.loads(src.with_suffix(".tjfix.json").read_text())["phantom"]
    assert fix["found"] == 1 and fix["left"] == 0 and len(fix["hints"]) == 1
    assert not any(all(x.mat.lower() == "tools/toolshint" for x in s.sides) for s in vmfio.load(src).brushes)  # fonte intocado


def test_wrapper_phantom_fix_reverts_when_recompile_fails(room, tmp_path, monkeypatch):
    import json
    from hammertools import bspcheck
    monkeypatch.setattr(bspcheck, "phantom_faces", lambda v, bsp, min_area=16.0: [_phantom()])
    src = tmp_path / "mapsrc" / "m.vmf"; src.parent.mkdir()
    vmfio.save(room, src)
    fake = tmp_path / "vbsp.py"
    # compila limpo sem hint; com hint no vmf, "estoura"
    fake.write_text("import sys, pathlib\np = pathlib.Path(sys.argv[-1])\n"
                    "if 'toolshint' in p.with_suffix('.vmf').read_text().lower(): print('Too many t-junctions to fix up!'); sys.exit(1)\n"
                    "p.with_suffix('.bsp').write_text('bom')\n")
    monkeypatch.setenv("HT_VBSP", sys.executable)
    assert vbsp_main([str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))]) == 0
    assert src.with_suffix(".bsp").read_text() == "bom"
    assert "toolshint" not in (tmp_path / "mapsrc" / "build" / "m.vmf").read_text().lower()  # build restaurado
    assert json.loads(src.with_suffix(".tjfix.json").read_text())["phantom"]["hints"] == []


def test_hint_box_for_phantom_pair_matches_validated_fix():
    """Par da entrada da escada do rp_surdonoso: a caixa tem que ser exatamente a validada no vbsp."""
    from srctools import Vec
    from hammertools import bspcheck
    big = {"area": 28820, "normal": Vec(1, 0, 0), "points": [Vec(3257, -11066, -376), Vec(3257, -11066, -256), Vec(3257, -10826, -256), Vec(3257, -10826, -376)]}
    small = {"area": 17280, "normal": Vec(-1, 0, 0), "points": [Vec(3257, -10970, -256), Vec(3257, -10970, -376), Vec(3257, -10826, -376), Vec(3257, -10826, -256)]}
    assert bspcheck.hint_boxes([big, small]) == [(Vec(3249, -10970, -376), Vec(3257, -10826, -256))]
    # sem par: pra trás da face
    assert bspcheck.hint_boxes([big]) == [(Vec(3249, -11066, -376), Vec(3257, -10826, -256))]

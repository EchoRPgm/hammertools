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


def test_tjfix_computes_conversion_and_compiles_once(room, tmp_path, monkeypatch):
    # o estouro (65550) e o custo estimado de cada func_detail dão o k; uma compilação só com ele
    rc, fix, bsp, calls = _run_counts(room, tmp_path, monkeypatch, "10")
    assert rc == 0 and fix["result"] == "convertido" and bsp["conv"] == fix["func_detail"] >= 1
    assert bsp["indices"] <= 65536
    assert calls.read_text() == "xx"  # a original + a calculada: nenhuma tentativa às cegas
    assert fix["detail_ids"] and fix["est_idx"] > 0


def test_tjfix_remembers_result_next_compile(room, tmp_path, monkeypatch):
    # segunda compilação do mesmo mapa (sem mudar): repete a conversão gravada, sem estourar de novo
    rc, fix, bsp, calls = _run_counts(room, tmp_path, monkeypatch, "10")
    assert calls.read_text() == "xx"
    src = tmp_path / "mapsrc" / "m.vmf"
    fake = tmp_path / "vbsp.py"
    assert vbsp_main([str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))]) == 0
    assert calls.read_text() == "xxx"  # uma compilação só, já convertida
    import json
    again = json.loads(src.with_suffix(".tjfix.json").read_text())
    assert again["result"] == "convertido" and again.get("memoria") and again["func_detail"] == fix["func_detail"]


def test_tjfix_remembers_notjunc(room, tmp_path, monkeypatch):
    # teto de modelos minúsculo: vira -notjunc; a próxima compilação já vai direto com -notjunc
    rc, fix, bsp, calls = _run_counts(room, tmp_path, monkeypatch, "10", MAX_MODELS=2)
    assert fix["result"] == "notjunc" and calls.read_text() == "xx"
    src = tmp_path / "mapsrc" / "m.vmf"
    assert vbsp_main([str(tmp_path / "vbsp.py"), "-game", str(tmp_path / "game"), str(src.with_suffix(""))]) == 0
    assert calls.read_text() == "xxx"
    monkeypatch.setenv("HT_TJ_RETRY", "1")                 # pedir recálculo volta ao caminho normal
    assert vbsp_main([str(tmp_path / "vbsp.py"), "-game", str(tmp_path / "game"), str(src.with_suffix(""))]) == 0
    assert calls.read_text() == "xxxxx"


def test_tjfix_model_cap_after_compile_goes_notjunc(room, tmp_path, monkeypatch):
    # o BSP da conversão calculada passa da trava de modelos: não tenta outra, vai de -notjunc com o build original
    rc, fix, bsp, calls = _run_counts(room, tmp_path, monkeypatch, "1000")
    assert rc == 0 and fix["result"] == "notjunc" and bsp == {"notjunc": 1}
    assert calls.read_text() == "xxx"
    assert "func_brush" not in (tmp_path / "mapsrc" / "build" / "m.vmf").read_text()


def test_tjfix_predicted_models_skip_compile(room, tmp_path, monkeypatch):
    # teto de modelos minúsculo: a previsão (mundo + 1 func_brush = 2 > 90% de 2) barra antes de compilar -> -notjunc
    rc, fix, bsp, calls = _run_counts(room, tmp_path, monkeypatch, "10", MAX_MODELS=2)
    assert rc == 0 and fix["result"] == "notjunc" and bsp == {"notjunc": 1}
    assert calls.read_text() == "xx"  # só a compilação original e a -notjunc: nenhuma tentativa de conversão


def _problem(area=5000.0):
    from srctools import Vec
    pts = [Vec(64, -32, 0), Vec(64, 32, 0), Vec(64, 32, 96), Vec(64, -32, 96)]
    return {"face": 1, "material": "concrete/x", "kind": "vazada", "expected": "brick/y", "area": area,
            "center": Vec(64, 0, 48), "normal": Vec(1, 0, 0), "points": pts}


def _is_detail(v, sid):
    return any(s.id == sid for e in v.by_class["func_detail"] for s in e.solids)


def test_wrapper_moves_minority_trim_to_detail(room, tmp_path, monkeypatch):
    import json
    from hammertools import bspcheck
    monkeypatch.setattr(bspcheck, "world_face_problems",
                        lambda v, bsp, min_area=16.0: [] if v.by_class["func_detail"] else [_problem()])
    monkeypatch.setattr(bspcheck, "detail_candidates", lambda v, probs: [v.brushes[0].id])
    src = tmp_path / "mapsrc" / "m.vmf"; src.parent.mkdir()
    vmfio.save(room, src)
    first = vmfio.load(src).brushes[0].id
    fake = tmp_path / "vbsp.py"
    fake.write_text("import sys, pathlib; pathlib.Path(sys.argv[-1]).with_suffix('.bsp').write_text('ok')")
    monkeypatch.setenv("HT_VBSP", sys.executable)
    monkeypatch.delenv("HT_NO_PHANTOM", raising=False)
    assert vbsp_main([str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))]) == 0
    assert _is_detail(vmfio.load(tmp_path / "mapsrc" / "build" / "m.vmf"), first)
    fix = json.loads(src.with_suffix(".tjfix.json").read_text())["phantom"]
    assert fix["found"] == 1 and fix["left"] == 0 and fix["detail"] == [first]
    assert not vmfio.load(src).by_class["func_detail"]  # fonte intocado


def test_wrapper_trim_fix_reverts_when_recompile_leaks(room, tmp_path, monkeypatch):
    import json
    from hammertools import bspcheck
    monkeypatch.setattr(bspcheck, "world_face_problems", lambda v, bsp, min_area=16.0: [_problem()])
    monkeypatch.setattr(bspcheck, "detail_candidates", lambda v, probs: [v.brushes[0].id])
    src = tmp_path / "mapsrc" / "m.vmf"; src.parent.mkdir()
    vmfio.save(room, src)
    fake = tmp_path / "vbsp.py"
    fake.write_text("import sys, pathlib\np = pathlib.Path(sys.argv[-1])\n"
                    "if 'func_detail' in p.with_suffix('.vmf').read_text(): print('**** leaked ****'); sys.exit(1)\n"
                    "p.with_suffix('.bsp').write_text('bom')\n")
    monkeypatch.setenv("HT_VBSP", sys.executable)
    assert vbsp_main([str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))]) == 0
    assert src.with_suffix(".bsp").read_text() == "bom"
    assert not vmfio.load(tmp_path / "mapsrc" / "build" / "m.vmf").by_class["func_detail"]
    assert json.loads(src.with_suffix(".tjfix.json").read_text())["phantom"]["detail"] == []


def test_detail_candidates_keeps_dominant_texture():
    """Fachada do rp_surdonoso em miniatura: tijolo (maior área) fica no mundo, concreto e metal viram detail."""
    from srctools import VMF, Vec
    from hammertools import bspcheck
    v = VMF()
    brick = v.make_prism(Vec(0, 0, 40), Vec(8, 96, 124), "brick/tijolo").solid
    band = v.make_prism(Vec(0, 0, 0), Vec(8, 96, 40), "concrete/faixa").solid
    frame = v.make_prism(Vec(0, 96, 0), Vec(8, 104, 124), "metal/batente").solid
    for s in (brick, band, frame):
        v.add_brush(s)
    prob = {"normal": Vec(1, 0, 0), "center": Vec(8, 50, 60),
            "points": [Vec(8, 0, 0), Vec(8, 104, 0), Vec(8, 104, 124), Vec(8, 0, 124)]}
    assert bspcheck.detail_candidates(v, [prob]) == sorted([band.id, frame.id])
    assert bspcheck.to_detail(v, [band.id, frame.id]) == 2 and [s.id for s in v.brushes] == [brick.id]


def test_hint_box_for_phantom_pair_matches_validated_fix():
    """Par da entrada da escada do rp_surdonoso: a caixa tem que ser exatamente a validada no vbsp."""
    from srctools import Vec
    from hammertools import bspcheck
    big = {"area": 28820, "normal": Vec(1, 0, 0), "points": [Vec(3257, -11066, -376), Vec(3257, -11066, -256), Vec(3257, -10826, -256), Vec(3257, -10826, -376)]}
    small = {"area": 17280, "normal": Vec(-1, 0, 0), "points": [Vec(3257, -10970, -256), Vec(3257, -10970, -376), Vec(3257, -10826, -376), Vec(3257, -10826, -256)]}
    assert bspcheck.hint_boxes([big, small]) == [(Vec(3249, -10970, -376), Vec(3257, -10826, -256))]
    # sem par: pra trás da face
    assert bspcheck.hint_boxes([big]) == [(Vec(3249, -11066, -376), Vec(3257, -10826, -256))]


def test_hidden_detail_faces_and_nodraw():
    from srctools import VMF, Vec
    from srctools.vmf import Entity
    from hammertools import fix
    v = VMF()
    wall = v.make_prism(Vec(0, 0, 0), Vec(16, 128, 128), "dev/dev_measuregeneric01b").solid
    v.add_brush(wall)
    # tábua de detail entrando 4u na parede: a face de trás fica escondida dentro dela
    board = v.make_prism(Vec(12, 32, 32), Vec(24, 96, 96), "wood/tabua").solid
    v.add_ent(Entity(v, {"classname": "func_detail"}, solids=[board]))
    from hammertools.core import geom
    hid = fix.hidden_detail_faces(v)
    assert len(hid) == 1 and geom.outward(hid[0][1])[0].x < -0.5   # a face de trás, dentro da parede
    assert fix.nodraw_hidden_detail(v) == 1
    assert sum(1 for s in board.sides if s.mat == "tools/toolsnodraw") == 1


def test_wrapper_reduces_verts_before_tjunctions(room, tmp_path, monkeypatch, capsys):
    import json
    from srctools import Vec
    from srctools.vmf import Entity
    src = tmp_path / "mapsrc" / "m.vmf"; src.parent.mkdir()
    board = room.make_prism(Vec(-512, 0, 0), Vec(-500, 64, 64), "wood/tabua").solid   # entra na parede -x da sala
    room.add_ent(Entity(room, {"classname": "func_detail"}, solids=[board]))
    vmfio.save(room, src)
    fake = tmp_path / "vbsp.py"
    fake.write_text("import sys, pathlib\np = pathlib.Path(sys.argv[-1])\n"
                    "if p.with_suffix('.vmf').read_text().lower().count('wood/tabua') >= 6: print('Too many unique verts, max = 65536'); sys.exit(1)\n"
                    "p.with_suffix('.bsp').write_text('ok')\n")
    monkeypatch.setenv("HT_VBSP", sys.executable)
    monkeypatch.setenv("HT_NO_PHANTOM", "1")
    assert vbsp_main([str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))]) == 0
    out = capsys.readouterr().out
    assert "teto de vértices" in out and "escondidas -> nodraw" in out
    verts = json.loads(src.with_suffix(".tjfix.json").read_text())["verts"]
    assert verts["nodraw"] == 1 and verts["ok"]


def _styled_bsp(tmp_path, light_origin):
    """tiny.bsp com a face 0 levando uma página clara do estilo 5 e a luz do mapa com style 5 em `light_origin`."""
    import logging
    import struct
    from srctools.bsp import BSP, BSP_LUMPS as L
    logging.getLogger("srctools").setLevel(logging.ERROR)
    b = BSP(str(Path(__file__).parent / "data" / "tiny.bsp"))
    faces = bytearray(b.lumps[L.FACES].data)
    for i in range(len(faces) // 56):
        struct.pack_into("<4Bi", faces, i * 56 + 16, 0, 255, 255, 255, -1)
        struct.pack_into("<ii", faces, i * 56 + 36, 0, 0)
    struct.pack_into("<4Bi", faces, 16, 0, 5, 255, 255, 0)
    b.lumps[L.FACES].data = bytes(faces)
    b.lumps[L.LIGHTING].data = bytes([200, 200, 200, 0, 190, 190, 190, 0])   # base e página do estilo 5
    light = next(e for e in b.ents.entities if e["classname"] == "light")
    light["style"] = "5"
    light["origin"] = light_origin
    out = tmp_path / "styled.bsp"
    b.save(str(out))
    return out


def test_bad_lightstyle_face_flagged_when_no_styled_light_near(tmp_path):
    from hammertools import bspcheck
    far = bspcheck.bad_lightstyle_faces(_styled_bsp(tmp_path, "9000 9000 9000"))
    assert [(f["face"], f["style"]) for f in far] == [(0, 5)]
    assert bspcheck.bad_lightstyle_faces(_styled_bsp(tmp_path, "0 0 0")) == []


def test_lock_blocks_second_compile_of_same_map(room, tmp_path, monkeypatch, capsys):
    import os
    src = tmp_path / "m.vmf"
    vmfio.save(room, src)
    src.with_suffix(".ht-vbsp.lock").write_text(str(os.getpid()))   # "outra" compilação viva
    assert vbsp_main([sys.executable, "-game", str(tmp_path / "game"), str(src.with_suffix(""))]) == 3
    assert "já há uma compilação" in capsys.readouterr().err
    src.with_suffix(".ht-vbsp.lock").write_text("999999999")       # trava velha (processo morto) não bloqueia
    fake = tmp_path / "vbsp.py"
    fake.write_text("import sys, pathlib; pathlib.Path(sys.argv[-1]).with_suffix('.bsp').write_text('ok')")
    monkeypatch.setenv("HT_VBSP", sys.executable)
    assert vbsp_main([str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))]) == 0
    assert not src.with_suffix(".ht-vbsp.lock").exists()


def test_ht_flags_become_env_and_are_not_passed_to_vbsp(room, tmp_path, monkeypatch):
    import os
    src = tmp_path / "m.vmf"
    vmfio.save(room, src)
    fake = tmp_path / "vbsp.py"
    fake.write_text("import sys, pathlib; p = pathlib.Path(sys.argv[-1]); p.with_suffix('.bsp').write_text(' '.join(sys.argv[1:]))")
    monkeypatch.setenv("HT_VBSP", sys.executable)
    for k in ("HT_NO_SEAL", "HT_AUTOPROP"):
        monkeypatch.delenv(k, raising=False)
    assert vbsp_main([str(fake), "--ht-no-seal", "--ht-no-autoprop", "-game", str(tmp_path / "game"), str(src.with_suffix(""))]) == 0
    assert os.environ["HT_NO_SEAL"] == "1" and os.environ["HT_AUTOPROP"] == "0"
    assert "--ht-" not in src.with_suffix(".bsp").read_text()
    # o vbsp_main pôs direto no os.environ (não foi o monkeypatch): pop simples, senão o teardown do monkeypatch
    # "restauraria" o 0 e vazaría HT_AUTOPROP pros testes seguintes
    os.environ.pop("HT_NO_SEAL", None); os.environ.pop("HT_AUTOPROP", None)


def test_wrapper_isolates_prop_light_for_ht_prop_models(room, tmp_path, monkeypatch):
    """Prop do `ht prop` no fonte: os outros props saem sem luz por vértice no build/ (o -StaticPropLighting é global)."""
    monkeypatch.delenv("HT_ALL_PROP_LIGHT", raising=False)
    room.create_ent("prop_static", model="models/props_c17/oildrum001.mdl", origin="0 0 0", disablevertexlighting="0")
    room.create_ent("prop_static", model="models/ht_prop/m/abc123def456.mdl", origin="64 0 0")
    src = tmp_path / "mapsrc" / "m.vmf"; src.parent.mkdir()
    vmfio.save(room, src)
    fake = tmp_path / "vbsp.py"
    fake.write_text("import sys, pathlib; pathlib.Path(sys.argv[-1]).with_suffix('.bsp').write_text('x')")
    monkeypatch.setenv("HT_VBSP", sys.executable)
    assert vbsp_main([str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))]) == 0
    props = {e["model"]: e for e in vmfio.load(tmp_path / "mapsrc" / "build" / "m.vmf").by_class["prop_static"]}
    assert props["models/props_c17/oildrum001.mdl"]["disablevertexlighting"] == "1"
    assert props["models/ht_prop/m/abc123def456.mdl"]["disablevertexlighting"] != "1"
    # o fonte não muda
    assert {e["disablevertexlighting"] for e in vmfio.load(src).by_class["prop_static"] if "oildrum" in e["model"]} == {"0"}


FAKE_NUNCA_FECHA = (
    "import sys, pathlib\n"
    "p = pathlib.Path(sys.argv[-1]); txt = p.with_suffix('.vmf').read_text()\n"
    "log = p.with_name('calls.txt')\n"
    "ch = 'n' if '-notjunc' in sys.argv else ('c' if 'func_brush' in txt else 'p')\n"
    "log.write_text((log.read_text() if log.exists() else '') + ch)\n"
    "if '-notjunc' in sys.argv:\n"
    "    print('Too many unique verts, max = 65536 (map has too much brush geometry)'); sys.exit(1)\n"
    "print('Too many t-junctions to fix up! (1 prims, max 32768 :: 65583 indices, max 65536)'); sys.exit(1)\n")


def test_tjfix_record_saved_when_compile_fails_and_drives_next(room, tmp_path, monkeypatch, capsys):
    """A compilação que não fecha ainda ensina: o registro é gravado com "falhou" e a próxima já vai de -notjunc
    (sem redescobrir a conversão) e dispara o auto-prop (ele lê este registro). Sem isso o mapa ficava em loop:
    toda compilação refazia as mesmas rodadas e falhava igual, porque o registro nunca nascia."""
    import json
    src = tmp_path / "mapsrc" / "m.vmf"; src.parent.mkdir()
    vmfio.save(_room_with_detail_tjunctions(room), src)
    fake = tmp_path / "vbsp.py"
    fake.write_text(FAKE_NUNCA_FECHA)
    monkeypatch.setenv("HT_VBSP", sys.executable)
    monkeypatch.delenv("HT_TJ_RETRY", raising=False)
    args = [str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))]

    assert vbsp_main(args) != 0                                   # nada fecha: t-junction e depois vértices
    out1 = capsys.readouterr().out
    fix = json.loads(src.with_suffix(".tjfix.json").read_text())  # gravado MESMO na falha
    assert fix["falhou"] and fix["result"] == "notjunc" and fix["est_idx"] > 0
    assert fix["conv_falhou"]["k"] >= 1 and "quando" in fix
    assert "auto-prop" not in out1                                # primeiro: sem registro, sem auto-prop
    calls = tmp_path / "mapsrc" / "build" / "calls.txt"
    antes = calls.read_text()
    assert antes[0] == "p" and "c" in antes and "n" in antes      # descobriu conversão, depois -notjunc

    assert vbsp_main(args) != 0
    out2 = capsys.readouterr().out
    depois = calls.read_text()[len(antes):]
    assert depois and "p" not in depois and "c" not in depois     # já vai direto com -notjunc, sem redescoberta
    fix2 = json.loads(src.with_suffix(".tjfix.json").read_text())
    assert "autoprop" in fix2 and fix2["memoria"] and fix2["falhou"]
    assert fix2["conv_falhou"] == fix["conv_falhou"]              # a tentativa que falhou continua na memória


def test_tjfix_skips_conversion_that_already_failed(room, tmp_path, monkeypatch, capsys):
    """conv_falhou: a conversão que não coube não é refeta enquanto a estimativa não mudar de verdade — uma
    compilação a menos por rodada; a próxima vai direto pro -notjunc."""
    import json
    src = tmp_path / "mapsrc" / "m.vmf"; src.parent.mkdir()
    vmfio.save(_room_with_detail_tjunctions(room), src)
    fake = tmp_path / "vbsp.py"
    fake.write_text(FAKE_NUNCA_FECHA.replace(
        "print('Too many unique verts, max = 65536 (map has too much brush geometry)'); sys.exit(1)",
        "p.with_suffix('.bsp').write_text('ok'); sys.exit(0)"))
    monkeypatch.setenv("HT_VBSP", sys.executable)
    monkeypatch.delenv("HT_TJ_RETRY", raising=False)
    args = [str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))]

    assert vbsp_main(args) == 0                    # conversão tentada, não coube -> -notjunc fecha (sem vértice)
    calls = tmp_path / "mapsrc" / "build" / "calls.txt"
    assert calls.read_text() == "pcn"
    fix = json.loads(src.with_suffix(".tjfix.json").read_text())
    assert fix["result"] == "notjunc" and fix["conv_falhou"]["k"] >= 1 and "falhou" not in fix

    # estimativa cai 5% -> o plano manda recalcular, mas a tentativa continua válida: não refaz a conversão
    fix["est_idx"] = fix["conv_falhou"]["est"] / 0.94
    src.with_suffix(".tjfix.json").write_text(json.dumps(fix))
    assert vbsp_main(args) == 0
    out = capsys.readouterr().out
    assert "recalculando" in out and "não refaço" in out
    assert calls.read_text() == "pcnpn"          # sem nova 'c': pula a conversão e vai direto pro -notjunc
    again = json.loads(src.with_suffix(".tjfix.json").read_text())
    assert again["conv_falhou"] == fix["conv_falhou"]   # e a memória continua lá

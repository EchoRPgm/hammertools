import sys

from srctools import VMF, Vec

from hammertools import lint, seal
from hammertools.cli import vbsp_main
from hammertools.core import vmf as vmfio


def _box(v, lo, hi, mat="dev/dev_measuregeneric01"):
    v.add_brush(v.make_prism(Vec(*lo), Vec(*hi), mat=mat).solid)


def _room(hole: bool, y0: float = 0.0) -> VMF:
    """Sala 1024x1024x512 (paredes de 32u) com a parede +x furada por uma porta de 128x128 se `hole`."""
    v = VMF()
    _box(v, (0, y0, 0), (1024, y0 + 1024, 32))
    _box(v, (0, y0, 480), (1024, y0 + 1024, 512))
    _box(v, (0, y0, 32), (32, y0 + 1024, 480))
    _box(v, (0, y0, 32), (1024, y0 + 32, 480))
    _box(v, (0, y0 + 992, 32), (1024, y0 + 1024, 480))
    if hole:
        _box(v, (992, y0 + 32, 32), (1024, y0 + 448, 480))
        _box(v, (992, y0 + 576, 32), (1024, y0 + 992, 480))
        _box(v, (992, y0 + 448, 160), (1024, y0 + 576, 480))
    else:
        _box(v, (992, y0 + 32, 32), (1024, y0 + 992, 480))
    v.create_ent("light", origin=f"200 {y0 + 500} 200")
    v.create_ent("info_player_start", origin=f"300 {y0 + 300} 40")
    return v


def _leaks(v: VMF, voxel=16.0) -> int:
    rep = lint.run(v, lint.Resources(), {"leak"}, voxel=voxel)
    return len(rep.by_check("leak")) if hasattr(rep, "by_check") else sum(1 for i in rep.issues if i.check == "leak")


def test_seal_plugs_only_the_doorway():
    v = _room(hole=True)
    assert _leaks(v) > 0
    n0 = len(v.brushes)
    r = seal.seal(v, voxel=16.0)
    assert r.sealed and r.leaked_before == 2
    assert _leaks(v) == 0
    # tampas só na porta (x ~992..1024, y 448..576, z 32..160), nada no meio da sala
    for lo, hi in r.boxes:
        assert lo.x >= 960 - 16 and 448 - 32 <= lo.y and hi.y <= 576 + 32 and hi.z <= 160 + 32, (lo, hi)
    assert len(v.brushes) == n0 + len(r.boxes)
    assert all(s.sides[0].mat == "tools/toolsskybox" for s in v.brushes[n0:])


def test_seal_leaves_sealed_map_alone():
    v = _room(hole=False)
    n0 = len(v.brushes)
    r = seal.seal(v, voxel=16.0)
    assert r.sealed and r.boxes == [] and len(v.brushes) == n0


def test_seal_closes_world_limit_with_thin_slab():
    # sala colada no limite do mundo (y = -16384) sem a parede desse lado: o vbsp vaza pelo limite
    v = VMF()
    y0 = -16384
    _box(v, (0, y0, 0), (1024, y0 + 1024, 32))
    _box(v, (0, y0, 480), (1024, y0 + 1024, 512))
    _box(v, (0, y0, 32), (32, y0 + 1024, 480))
    _box(v, (992, y0, 32), (1024, y0 + 1024, 480))
    _box(v, (0, y0 + 992, 32), (1024, y0 + 1024, 480))
    v.create_ent("light", origin=f"500 {y0 + 500} 200")
    r = seal.seal(v, voxel=16.0)
    assert r.sealed and r.boxes
    slabs = [(lo, hi) for lo, hi in r.boxes if lo.y == -16384 and hi.y == -16384 + seal.SLAB]
    assert slabs, r.boxes
    assert all(hi.y <= 16384 and lo.y >= -16384 for lo, hi in r.boxes)


def test_vbsp_wrapper_seals_build_copy_and_recompiles(tmp_path, monkeypatch, capsys):
    src = tmp_path / "mapsrc" / "m.vmf"
    src.parent.mkdir()
    vmfio.save(_room(hole=True), src)
    # vbsp falso: "vaza" enquanto o VMF não tiver toolsskybox
    fake = tmp_path / "vbsp.py"
    fake.write_text(
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[-1])\n"
        "text = p.with_suffix('.vmf').read_text()\n"
        "if 'toolsskybox' not in text.lower():\n"
        "    print('**** leaked ****')\n"
        "p.with_suffix('.bsp').write_text('ok')\n")
    monkeypatch.setenv("HT_VBSP", sys.executable)
    monkeypatch.setenv("HT_NO_PHANTOM", "1")
    monkeypatch.setenv("HT_SEAL_GROSSO", "1")
    monkeypatch.setattr(seal, "seal", lambda v, res=None, voxel=None, material="tools/toolsskybox":
                        _real_seal(v, res, 16.0, material))
    rc = vbsp_main([str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))])
    out = capsys.readouterr().out
    assert rc == 0 and "tampa(s) de toolsskybox" in out and "selado." in out and "setpos" in out
    assert "toolsskybox" in (tmp_path / "mapsrc" / "build" / "m.vmf").read_text().lower()
    assert "toolsskybox" not in src.read_text().lower()          # o fonte não muda


_real_seal = seal.seal


def test_crossing_finds_inside_to_void_segment():
    cls = lambda p: "in" if p.x < 100 else ("solid" if p.x < 120 else "out")
    a, b = seal.crossing([Vec(0, 0, 0), Vec(200, 0, 0)], cls)
    assert 96 <= a.x < 100 and 120 <= b.x <= 124
    a, b = seal.crossing([Vec(200, 0, 0), Vec(0, 0, 0)], cls)       # caminho no sentido contrário
    assert a.x < 100 and b.x >= 120


def test_seal_at_pointfile_closes_gap_smaller_than_voxel():
    # sala fechada exceto uma fresta de 2u na parede +x: invisível na grade grossa (8u), o vbsp vazaria por ela
    v = _room(hole=False)
    for s in list(v.brushes):
        lo, hi = s.get_bbox()
        if lo.x == 992:
            v.remove_brush(s)
    _box(v, (992, 32, 32), (1024, 496, 480))
    _box(v, (992, 498, 32), (1024, 992, 480))
    assert seal.seal(v).boxes == []                                # grossa: "não vaza"
    path = [Vec(200, 497, 200), Vec(500, 497, 200), Vec(1000, 497, 200), Vec(1500, 497, 200)]   # pela fresta
    made = seal.seal_at_pointfile(v, None or lint.Resources(), path)
    assert made, "devia tampar a fresta"
    for lo, hi in made:
        assert 900 <= lo.x and hi.x <= 1200 and 480 <= lo.y and hi.y <= 512, (lo, hi)
    # a fresta (y 496..498, z 32..480, na espessura da parede x 992..1024) fica toda coberta
    zs = sorted((lo.z, hi.z) for lo, hi in made if lo.y <= 496 and hi.y >= 498)
    z = 32.0
    for a, b in zs:
        if a <= z < b:
            z = b
    assert z >= 480, zs


def test_sliver_plug_fills_off_grid_gap():
    # duas paredes: uma termina em y=499.6 (vértice fora do grid), a outra começa em y=500: lasca de 0,4u
    v = VMF()
    _box(v, (0, 0, 0), (32, 499.6, 256))
    _box(v, (0, 500, 0), (32, 1000, 256))
    path = [Vec(-100, 499.8, 128), Vec(100, 499.8, 128)]
    made = seal.sliver_plugs(v, lint.Resources(), path)
    assert len(made) == 1
    lo, hi = made[0]
    assert (lo.x, hi.x) == (0, 32) and (lo.y, hi.y) == (499, 500) and (lo.z, hi.z) == (0, 256)   # arredondada pra fora
    assert v.brushes[-1].sides[0].mat == "tools/toolsnodraw"


def test_close_slivers_fills_all_sub_unit_gaps_at_once():
    v = VMF()
    _box(v, (0, 0, 0), (32, 499.6, 256))
    _box(v, (0, 500, 0), (32, 1000, 256))          # lasca de 0,4u em y
    _box(v, (100, 0, 0), (131.5, 64, 64))
    _box(v, (132, 0, 0), (164, 64, 64))            # lasca de 0,5u em x
    _box(v, (200, 0, 0), (232, 64, 64))
    _box(v, (240, 0, 0), (272, 64, 64))            # 8u: vão de verdade, fica
    made = seal.close_slivers(v, lint.Resources())
    spans = sorted((round(lo.x, 1), round(hi.x, 1), round(lo.y, 1), round(hi.y, 1)) for lo, hi in made)
    assert spans == [(0, 32, 499, 500), (131, 132, 0, 64)]   # arredondadas pra fora


def test_cache_roundtrip_drops_plugs_over_entities(tmp_path):
    v = _room(hole=True)
    r = seal.seal(v, voxel=16.0)
    plugs = seal.plugs_in(v)
    assert len(plugs) == len(r.boxes) > 0
    cache = tmp_path / "m.seal.json"
    seal.save_cache(cache, plugs)
    fresh = _room(hole=True)
    assert seal.apply_cache(fresh, cache) == (len(plugs), 0)
    assert _leaks(fresh) == 0
    # entidade agora dentro da tampa: o mapa mudou ali, a tampa velha não volta
    lo, hi, _m = plugs[0]
    moved = _room(hole=True)
    moved.create_ent("info_target", origin=f"{(lo.x + hi.x) / 2} {(lo.y + hi.y) / 2} {(lo.z + hi.z) / 2}")
    assert seal.apply_cache(moved, cache) == (len(plugs) - 1, 1)


def test_optimize_never_merges_seal_plugs():
    from hammertools import optimize
    v = VMF()
    _box(v, (0, 0, 0), (64, 64, 64), mat="tools/toolsnodraw")
    seal.add_plug(v, Vec(64, 0, 0), Vec(128, 64, 64), "tools/toolsnodraw")
    n = len(v.brushes)
    optimize.optimize(v)
    assert len(v.brushes) == n and len(seal.plugs_in(v)) == 1


def test_fingerprint_ignores_ids_and_plugs_but_not_geometry(tmp_path):
    a, b = tmp_path / "a.vmf", tmp_path / "b.vmf"
    vmfio.save(_room(hole=True), a)
    v = _room(hole=True)
    seal.add_plug(v, Vec(992, 448, 32), Vec(1024, 576, 160), "tools/toolsskybox")
    vmfio.save(v, b)
    fa = seal.fingerprint(a.read_text())
    assert fa and fa == seal.fingerprint(b.read_text())        # tampa e ids novos não contam
    vmfio.save(_room(hole=False), b)
    assert fa != seal.fingerprint(b.read_text())               # vão fechado no Hammer: outra geometria
    cache = tmp_path / "m.seal.json"
    seal.save_cache(cache, [], [], fa)
    assert seal.cache_valid(cache, fa) and not seal.cache_valid(cache, seal.fingerprint(b.read_text()))
    cache.write_text("[]")                                      # formato antigo, sem impressão: velho
    assert not seal.cache_valid(cache, fa)


def test_vbsp_wrapper_drops_cache_of_other_geometry(tmp_path, monkeypatch, capsys):
    """Mapa fechado no Hammer depois de um selo automático: as tampas do cache ficariam no meio do cômodo."""
    src = tmp_path / "mapsrc" / "m.vmf"
    src.parent.mkdir()
    vmfio.save(_room(hole=False), src)
    cache = src.with_suffix(".seal.json")
    seal.save_cache(cache, [(Vec(400, 400, 100), Vec(488, 488, 188), "tools/toolsskybox")], [], "outra")
    fake = tmp_path / "vbsp.py"
    fake.write_text("import sys, pathlib; pathlib.Path(sys.argv[-1]).with_suffix('.bsp').write_text('ok')")
    monkeypatch.setenv("HT_VBSP", sys.executable)
    monkeypatch.setenv("HT_NO_PHANTOM", "1")
    assert vbsp_main([str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))]) == 0
    out = capsys.readouterr().out
    assert "outra geometria" in out and not cache.exists() and cache.with_suffix(".velho.json").exists()
    assert "toolsskybox" not in (tmp_path / "mapsrc" / "build" / "m.vmf").read_text().lower()


def test_vbsp_wrapper_closes_slivers_before_coarse_seal(tmp_path, monkeypatch, capsys):
    """Leak só por lasca fora do grid: fecha com nodraw e nem chega no selo grosso (toolsskybox no voxel)."""
    src = tmp_path / "mapsrc" / "m.vmf"
    src.parent.mkdir()
    v = _room(hole=False)
    _box(v, (2000, 0, 0), (2032, 499.6, 64))
    _box(v, (2000, 500, 0), (2032, 1000, 64))
    vmfio.save(v, src)
    fake = tmp_path / "vbsp.py"
    fake.write_text(
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[-1])\n"
        "if '499 0' not in p.with_suffix('.vmf').read_text():\n"   # tampa da lasca (y 499..500) ainda não existe
        "    print('**** leaked ****')\n"
        "p.with_suffix('.bsp').write_text('ok')\n")
    monkeypatch.setenv("HT_VBSP", sys.executable)
    monkeypatch.setenv("HT_NO_PHANTOM", "1")
    called = []
    monkeypatch.setattr(seal, "seal", lambda *a, **k: called.append(1) or seal.SealResult())
    assert vbsp_main([str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))]) == 0
    out = capsys.readouterr().out
    assert "lasca(s)" in out and "selado." in out and not called


def test_vbsp_wrapper_reports_real_opening_without_plugging(tmp_path, monkeypatch, capsys):
    """Porta de 128u aberta pro vazio: sem --ht-seal-grosso nada é tampado (a tampa ocuparia a passagem); avisa."""
    src = tmp_path / "mapsrc" / "m.vmf"
    src.parent.mkdir()
    vmfio.save(_room(hole=True), src)
    fake = tmp_path / "vbsp.py"
    # vaza sempre, com o caminho da luz (200 500 200) saindo pela porta (x 992..1024, y 448..576, z 32..160)
    fake.write_text(
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[-1])\n"
        "print('**** leaked ****')\n"
        "p.with_suffix('.lin').write_text('200 500 200\\n1008 512 96\\n1400 512 96\\n')\n"
        "p.with_suffix('.bsp').write_text('ok')\n")
    monkeypatch.setenv("HT_VBSP", sys.executable)
    monkeypatch.setenv("HT_NO_PHANTOM", "1")
    vbsp_main([str(fake), "-game", str(tmp_path / "game"), str(src.with_suffix(""))])
    out = capsys.readouterr().out
    assert "vão(s) de verdade" in out and "AINDA VAZA" in out
    assert "ht_seal" not in (tmp_path / "mapsrc" / "build" / "m.vmf").read_text()
    assert not src.with_suffix(".seal.json").exists()


def test_close_slivers_stays_inside_non_rectangular_faces():
    """Rampa (face lateral triangular) a 1u de uma parede: a tampa pela caixa do brush subia acima da rampa, ia para o ar
    e o vbsp apagava a face da parede (cinza do vazio no vão de escada do rp_surdonoso)."""
    v = VMF()
    _box(v, (0, -64, 0), (256, 0, 256))                   # parede, face em y = 0
    ramp = v.make_prism(Vec(0, 1, 0), Vec(256, 128, 128)).solid
    for sd in ramp.sides:                                  # corta a caixa na diagonal: lateral em y = 1 vira triângulo
        pass
    from srctools import Vec as V
    from srctools.vmf import Side
    ramp.sides.append(Side(v, [V(0, 0, 0), V(0, 200, 0), V(256, 200, 128)], mat="dev/dev_measuregeneric01"))
    v.add_brush(ramp)
    made = seal.close_slivers(v, lint.Resources())
    assert made == []                                      # face triangular: não tampa (a caixa passaria da rampa)
    # face retangular continua fechando
    _box(v, (300, 1, 0), (400, 64, 64))
    _box(v, (300, -64, 0), (400, 0, 64))
    assert len(seal.close_slivers(v, lint.Resources())) == 1

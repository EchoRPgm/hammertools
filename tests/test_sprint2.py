from pathlib import Path

from srctools import Vec

from hammertools.cli import build
from hammertools.core import repeat
from hammertools.core import vmf as vmfio


def _rt(v, tmp_path: Path):
    src, out = tmp_path / "m.vmf", tmp_path / "m_built.vmf"
    vmfio.save(v, src)
    n_groups, n_solids, warnings = build(src, out)
    return vmfio.load(out), n_solids, warnings


def _gen_solids(built):
    ids = {vg.id for vg in _walk(built.vis_tree) if vg.name not in ("ht_generated", "ht_markers")}
    return [s for s in built.brushes if s.visgroup_ids & ids]


def _walk(groups):
    for g in groups:
        yield g
        yield from _walk(g.child_groups)


def test_repeat_helpers():
    assert repeat.positions(200, 64) == [0, 64, 128, 192, 200]
    assert repeat.positions(192, 64) == [0, 64, 128, 192]
    assert repeat.positions(200, 64, include_end=False) == [0, 64, 128, 192]
    assert repeat.segments(200, 64) == [(0, 64), (64, 128), (128, 192), (192, 200)]


def test_fence_brush(room, tmp_path):
    room.create_ent("ht_fence", origin="0 0 0", targetname="c", spacing="64")
    room.create_ent("ht_fence_end", origin="200 0 0", targetname="c")
    built, n, warnings = _rt(room, tmp_path)
    assert warnings == []
    assert n == 5 + 3  # 5 postes (0,64,128,192,200) + 3 painéis; o resto de 8u cabe no poste final
    gen = _gen_solids(built)
    lo, hi = Vec.bbox(*[p for s in gen for side in s.sides for p in side.planes])
    assert (lo.x, hi.x) == (-4, 204) and (lo.z, hi.z) == (0, 104)
    for s in gen:
        a, b = s.get_bbox()
        assert b.x - a.x > 0 and b.y - a.y > 0 and b.z - a.z > 0


def test_fence_prop_manual(room, tmp_path):
    room.create_ent("ht_fence", origin="0 0 0", targetname="c", mode="prop", prop_spacing="64", model_yaw="0", model_z="0", model="models/x.mdl")
    room.create_ent("ht_fence_end", origin="0 256 0", targetname="c")  # ao longo de +Y
    built, n, warnings = _rt(room, tmp_path)
    props = [e for e in built.entities if e["classname"] == "prop_static"]
    assert n == 0 and warnings == [] and len(props) == 4
    ys = sorted(round(Vec.from_str(p["origin"]).y) for p in props)
    assert ys == [32, 96, 160, 224]  # centrados em cada módulo
    assert all(abs(Vec.from_str(p["origin"]).x) < 1e-6 for p in props)
    assert props[0]["angles"].split()[1].startswith("90")


def test_fence_prop_auto_from_model_bbox(room, tmp_path, monkeypatch):
    from hammertools.core import models
    # modelo tipo fence01a: longo em Y (134), origem no centro (z de -54 a 54)
    monkeypatch.setattr(models, "model_bbox", lambda gamedir, model: (Vec(-2, -67, -54), Vec(2, 67, 54)))
    monkeypatch.setattr(models, "game_dir", lambda explicit=None: "fake")
    room.create_ent("ht_fence", origin="0 0 0", targetname="c", mode="prop", model="models/x.mdl", prop_at_end="1")
    room.create_ent("ht_fence_end", origin="400 0 0", targetname="c")  # ao longo de +X
    built, n, warnings = _rt(room, tmp_path)
    props = sorted((e for e in built.entities if e["classname"] == "prop_static"), key=lambda e: Vec.from_str(e["origin"]).x)
    assert warnings == []
    xs = [round(Vec.from_str(p["origin"]).x) for p in props]
    assert xs == [67, 201, 333]  # 2 módulos de 134 + 1 extra encostado no fim (400-67)
    assert all(round(Vec.from_str(p["origin"]).z) == 54 for p in props)
    assert all(p["angles"].split()[1].startswith("90") for p in props)  # eixo longo (Y) alinhado com a linha (X)


def test_fence_prop_auto_without_game_warns(room, tmp_path, monkeypatch):
    from hammertools.core import models
    monkeypatch.setattr(models, "game_dir", lambda explicit=None: None)
    room.create_ent("ht_fence", origin="0 0 0", targetname="c", mode="prop", model="models/x.mdl")
    room.create_ent("ht_fence_end", origin="128 0 0", targetname="c")
    _, _, warnings = _rt(room, tmp_path)
    assert any("bbox" in w for w in warnings)


def test_railing_follows_slope(room, tmp_path):
    room.create_ent("ht_railing", origin="0 0 0", targetname="r", post_spacing="64", height="40")
    room.create_ent("ht_railing_end", origin="128 0 64", targetname="r")
    built, n, warnings = _rt(room, tmp_path)
    assert warnings == []
    assert n == 3 + 2  # postes em 0,64,128 + barra de cima + barra do meio
    gen = _gen_solids(built)
    bars = [s for s in gen if s.get_bbox()[1].x - s.get_bbox()[0].x > 100]
    assert len(bars) == 2
    top = max(bars, key=lambda s: s.get_bbox()[1].z)
    # ponto no meio da barra de cima: x=64, z = 32 (piso) + 36..40
    assert top.point_inside(Vec(64, 0, 32 + 38))
    assert not top.point_inside(Vec(64, 0, 32 + 20))
    assert not top.point_inside(Vec(64, 0, 32 + 41)) and not top.point_inside(Vec(64, 5, 32 + 38))
    # pontos de plano no grid (barras inclinadas construídas por pontos explícitos)
    for s in bars:
        for side in s.sides:
            for p in side.planes:
                assert all(abs(c - round(c)) < 1e-6 for c in (p.x, p.y, p.z))


def test_ladder_func_ladder_gmod(room, tmp_path):
    room.create_ent("ht_ladder", origin="100 0 0", targetname="l", angles="0 0 0")  # parede em +X
    room.create_ent("ht_ladder_end", origin="100 0 128", targetname="l")
    built, n, warnings = _rt(room, tmp_path)
    assert warnings == [] and n == 1
    assert not [e for e in built.entities if e["classname"] in ("func_useableladder", "info_ladder_dismount")]
    lad = next(e for e in built.entities if e["classname"] == "func_ladder")
    assert lad.is_brush() and lad["targetname"] == "l"
    lo, hi = lad.solids[0].get_bbox()
    # visual de x=96..100; volume de 16 na frente: x=80..96, largura 32, do chão até 128+24
    assert (lo.x, hi.x, lo.y, hi.y, lo.z, hi.z) == (80, 96, -16, 16, 0, 152)
    assert all(side.mat == "tools/toolsinvisibleladder" for side in lad.solids[0].sides)
    s = _gen_solids(built)[0]
    lo, hi = s.get_bbox()
    assert (lo.x, hi.x, lo.y, hi.y, lo.z, hi.z) == (96, 100, -16, 16, 0, 128)
    assert len(built.brushes) == 6 + 1  # o volume da func_ladder não vai pro mundo


def test_fence_last_panel_cut(room, tmp_path):
    room.create_ent("ht_fence", origin="0 0 0", targetname="c", spacing="64")
    room.create_ent("ht_fence_end", origin="216 0 0", targetname="c")
    built, n, _ = _rt(room, tmp_path)
    assert n == 5 + 4
    last = max(_gen_solids(built), key=lambda s: s.get_bbox()[1].x - 1000 * (s.get_bbox()[1].x - s.get_bbox()[0].x < 9))
    lo, hi = last.get_bbox()
    assert (lo.x, hi.x) == (196, 212)  # 192+4 .. 216-4

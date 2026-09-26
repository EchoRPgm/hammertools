from pathlib import Path

from srctools import Vec

from hammertools.cli import build
from hammertools.core import vmf as vmfio


def _add_stairs(v, a: str, b: str, name="escada1", **kv):
    kv.setdefault("playerclip", "0")  # testes de geometria dos degraus; o clip tem teste próprio
    v.create_ent("ht_stairs", origin=a, targetname=name, **kv)
    v.create_ent("ht_stairs_end", origin=b, targetname=name)


def _roundtrip(v, tmp_path: Path):
    src = tmp_path / "m.vmf"
    out = tmp_path / "m_built.vmf"
    vmfio.save(v, src)
    n_groups, n_solids, warnings = build(src, out)
    return vmfio.load(out), n_groups, n_solids, warnings


def test_straight_x(room, tmp_path):
    _add_stairs(room, "0 0 0", "128 0 64")  # 8 degraus de 16x8
    built, n_groups, n_solids, warnings = _roundtrip(room, tmp_path)
    assert n_groups == 1 and n_solids == 8
    assert warnings == []
    gen = [s for s in built.brushes if any(vg.name == "escada1" for vg in _all_vg(built) if vg.id in s.visgroup_ids)]
    assert len(gen) == 8
    mins = Vec.bbox(*[p for s in gen for side in s.sides for p in side.planes])[0]
    maxs = Vec.bbox(*[p for s in gen for side in s.sides for p in side.planes])[1]
    assert (mins.x, mins.y, mins.z) == (0, -32, 0)
    assert (maxs.x, maxs.y, maxs.z) == (128, 32, 64)
    # último degrau vai do chão ao topo (style solid)
    last = max(gen, key=lambda s: s.get_bbox()[1].x)
    lo, hi = last.get_bbox()
    assert (lo.x, lo.z, hi.x, hi.z) == (112, 0, 128, 64)


def test_markers_parked_not_deleted(room, tmp_path):
    _add_stairs(room, "0 0 0", "128 0 64")
    built, *_ = _roundtrip(room, tmp_path)
    marks = vmfio.markers(built)
    assert len(marks) == 2 and all(m.hidden for m in marks)
    assert any(vg.name == "ht_markers" for vg in built.vis_tree)


def test_rotated_90_stays_on_grid(room, tmp_path):
    _add_stairs(room, "0 0 0", "0 128 64")  # sobe no +Y
    built, _, n_solids, warnings = _roundtrip(room, tmp_path)
    assert n_solids == 8 and warnings == []
    for s in built.brushes:
        for side in s.sides:
            for p in side.planes:
                assert all(abs(c - round(c)) < 1e-6 for c in (p.x, p.y, p.z))


def test_diagonal_warns(room, tmp_path):
    _add_stairs(room, "0 0 0", "128 128 64")
    _, _, _, warnings = _roundtrip(room, tmp_path)
    assert any("fora do grid" in w for w in warnings)


def test_floating_style(room, tmp_path):
    _add_stairs(room, "0 0 0", "128 0 64", style="floating", tread_thickness="4")
    built, _, n_solids, _ = _roundtrip(room, tmp_path)
    assert n_solids == 8
    gen = [s for s in built.brushes if s.get_bbox()[1].z <= 64 and s.get_bbox()[0].z >= 0 and s.get_bbox()[1].x <= 128 and s.get_bbox()[0].x >= 0 and s.get_bbox()[1].y <= 32]
    last = max(gen, key=lambda s: s.get_bbox()[1].x)
    lo, hi = last.get_bbox()
    assert (lo.z, hi.z) == (60, 64)


def test_missing_end_warns(room, tmp_path):
    room.create_ent("ht_stairs", origin="0 0 0", targetname="solo")
    _, _, n_solids, warnings = _roundtrip(room, tmp_path)
    assert n_solids == 0 and any("ht_stairs_end" in w for w in warnings)


def test_refuses_built_input(tmp_path, capsys):
    from hammertools.cli import main
    p = tmp_path / "x_built.vmf"; p.write_text("")
    assert main(["build", str(p)]) == 2


def _all_vg(v):
    out = []
    def walk(groups):
        for g in groups:
            out.append(g); walk(g.child_groups)
    walk(v.vis_tree)
    return out


def test_solid_nodraw_only_hidden_faces(room, tmp_path):
    _add_stairs(room, "0 0 0", "128 0 64")
    built, *_ = _roundtrip(room, tmp_path)
    gen = [s for s in built.brushes if 0 <= s.get_bbox()[0].x and s.get_bbox()[1].x <= 128 and s.get_bbox()[1].y <= 32]
    assert len(gen) == 8
    for s in sorted(gen, key=lambda s: s.get_bbox()[0].x):
        lo, hi = s.get_bbox()
        last = hi.x == 128
        for side in s.sides:
            n = side.normal()   # srctools devolve a normal APONTANDO PRA DENTRO do solid
            if n.z > 0.5:       # base
                assert side.mat == "tools/toolsnodraw"
            elif n.x < -0.5:    # traseira (+X)
                assert (side.mat == "tools/toolsnodraw") != last
            else:               # topo, espelho (-X) e laterais: visíveis
                assert side.mat != "tools/toolsnodraw"


def test_floating_has_no_nodraw(room, tmp_path):
    _add_stairs(room, "0 0 0", "128 0 64", style="floating")
    built, *_ = _roundtrip(room, tmp_path)
    gen = [s for s in built.brushes if 0 <= s.get_bbox()[0].x and s.get_bbox()[1].x <= 128 and s.get_bbox()[1].y <= 32]
    assert all(side.mat != "tools/toolsnodraw" for s in gen for side in s.sides)


def test_legacy_role_keyvalue_still_works(room, tmp_path):
    room.create_ent("ht_stairs", origin="0 0 0", targetname="old", role="start")
    room.create_ent("ht_stairs", origin="128 0 64", targetname="old", role="end")
    _, _, n_solids, warnings = _roundtrip(room, tmp_path)
    assert n_solids == 8 + 1 and warnings == []  # + rampa de playerclip (padrão ligado)


def test_playerclip_ramp_solid(room, tmp_path):
    _add_stairs(room, "0 0 0", "128 0 64", playerclip="1")  # 8 degraus 16x8
    built, _, n_solids, warnings = _roundtrip(room, tmp_path)
    assert n_solids == 9 and warnings == []
    clips = [s for s in built.brushes if all(side.mat == "tools/toolsplayerclip" for side in s.sides)]
    assert len(clips) == 1
    c = clips[0]
    assert len(c.sides) == 6
    # reta dos narizes: z = 0.5*x + 8 ; de (-16, 0) até (112, 64), depois plano até (128, 64)
    assert c.point_inside(Vec(64, 0, 0.5 * 64 + 8 - 1))       # logo abaixo da rampa
    assert not c.point_inside(Vec(64, 0, 0.5 * 64 + 8 + 1))   # logo acima
    assert c.point_inside(Vec(-15, 0, 0.2)) and not c.point_inside(Vec(-17, 0, 0.2))
    assert c.point_inside(Vec(127, 0, 63)) and not c.point_inside(Vec(129, 0, 63))
    assert not c.point_inside(Vec(64, 40, 20)) and c.point_inside(Vec(64, 31, 20))  # largura 64
    for side in c.sides:
        for p in side.planes:
            assert all(abs(v - round(v)) < 1e-6 for v in (p.x, p.y, p.z))


def test_playerclip_ramp_floating_leaves_space_below(room, tmp_path):
    _add_stairs(room, "0 0 0", "128 0 64", playerclip="1", style="floating", tread_thickness="8")
    built, _, n_solids, _ = _roundtrip(room, tmp_path)
    assert n_solids == 9
    c = next(s for s in built.brushes if all(side.mat == "tools/toolsplayerclip" for side in s.sides))
    assert c.point_inside(Vec(64, 0, 0.5 * 64 + 8 - 4))   # dentro da laje (nariz - 4)
    assert not c.point_inside(Vec(64, 0, 10))              # espaço livre embaixo da escada

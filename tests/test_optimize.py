from srctools import VMF, Vec
from srctools.vmf import Entity

from hammertools import lint, optimize
from hammertools.cli import main


def _box(v, lo, hi, mat="dev/dev_measuregeneric01b"):
    return v.make_prism(Vec(*lo), Vec(*hi), mat).solid


def test_merges_chain_of_slices():
    v = VMF()
    for x in range(0, 256, 64):  # piso fatiado em 4
        v.add_brush(_box(v, (x, 0, 0), (x + 64, 128, 16)))
    res = optimize.optimize(v)
    assert sum(res.merged.values()) == 3 and len(v.brushes) == 1
    lo, hi = v.brushes[0].get_bbox()
    assert (lo, hi) == (Vec(0, 0, 0), Vec(256, 128, 16))


def test_keeps_different_texture_and_partial_face():
    v = VMF()
    v.add_brush(_box(v, (0, 0, 0), (64, 64, 64)))
    v.add_brush(_box(v, (64, 0, 0), (128, 64, 64), "concrete/concretefloor001a"))  # outra textura
    v.add_brush(_box(v, (-64, 0, 0), (0, 32, 64)))                                # face só parcial
    assert sum(optimize.optimize(v).merged.values()) == 0 and len(v.brushes) == 3


def test_water_end_never_joins_solid():
    v = VMF()
    a = _box(v, (0, 0, 0), (64, 64, 64))
    b = _box(v, (64, 0, 0), (128, 64, 64))
    b.sides[[s.normal().x for s in b.sides].index(-1)].mat = "nature/water"  # ponta +x (normal pra dentro -x)
    v.add_brush(a); v.add_brush(b)
    assert sum(optimize.optimize(v).merged.values()) == 0


def test_detail_only_within_same_entity():
    v = VMF()
    e1 = Entity(v, {"classname": "func_detail"}, solids=[_box(v, (0, 0, 0), (64, 64, 64)), _box(v, (64, 0, 0), (128, 64, 64))])
    e2 = Entity(v, {"classname": "func_detail"}, solids=[_box(v, (128, 0, 0), (192, 64, 64))])
    v.add_ent(e1); v.add_ent(e2)
    res = optimize.optimize(v)
    assert res.merged["func_detail"] == 1 and len(e1.solids) == 1 and len(e2.solids) == 1


def test_cli_writes_new_file_and_reduces_tjunctions(tmp_path):
    v = VMF()
    for x in range(0, 256, 64):
        v.add_brush(_box(v, (x, 0, 0), (x + 64, 128, 16)))
    v.add_brush(_box(v, (0, 0, 16), (256, 128, 32), "concrete/concretefloor001a"))  # laje por cima: vê as emendas como t-junctions
    src = tmp_path / "m.vmf"
    with open(src, "w") as f:
        v.export(f)
    before = src.read_text()
    assert main(["optimize", str(src), "--game", str(tmp_path)]) == 0
    assert src.read_text() == before
    out = VMF.parse(__import__("srctools").Keyvalues.parse(open(tmp_path / "m_opt.vmf")))
    assert len(out.brushes) == 2
    assert lint.run(out, lint.Resources(), {"tjunctions"}).data["tjunctions_total"] == 0

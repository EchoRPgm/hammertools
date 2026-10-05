from srctools import Vec, VMF
from srctools.vmf import Entity

from hammertools import extents, lint
from hammertools.core import geom


def test_clamp_cuts_removes_and_warns():
    v = VMF()
    wall = v.make_prism(Vec(-100, -16384, 0), Vec(100, -16300, 64), "dev/a").solid
    v.add_brush(wall)
    v.add_brush(v.make_prism(Vec(-100, -16384, 0), Vec(100, -16360, 64), "dev/b").solid)   # todo fora
    v.add_brush(v.make_prism(Vec(0, 0, 0), Vec(64, 64, 64), "dev/c").solid)
    det = v.make_prism(Vec(16300, 0, 0), Vec(16384, 64, 64), "dev/d").solid
    v.add_ent(Entity(v, {"classname": "func_detail"}, solids=[det]))
    v.add_ent(Entity(v, {"classname": "light", "origin": "0 -16370 32"}))
    r = extents.clamp(v)
    assert {(c, i) for c, i, _ in r["cortados"]} == {("mundo", wall.id), ("func_detail", det.id)}
    assert len(r["removidos"]) == 1 and r["entidades"][0][0] == "light"
    pts = [p for _, poly in geom.face_polys(wall) for p in poly]
    assert min(p.y for p in pts) == -extents.LIMIT and max(p.y for p in pts) == -16300
    assert len(v.brushes) == 2
    rep = lint.run(v, lint.Resources(), {"extents"})
    assert any(i.check == "extents" for i in rep.issues)       # a luz fora do limite continua acusada


def test_inside_map_untouched():
    v = VMF()
    v.add_brush(v.make_prism(Vec(-16000, -16000, 0), Vec(16000, 16000, 64), "dev/a").solid)
    assert not any(extents.clamp(v).values())


def test_clamp_is_idempotent():
    v = VMF()
    v.add_brush(v.make_prism(Vec(-100, -16384, 0), Vec(100, -16300, 64), "dev/a").solid)
    extents.clamp(v)
    n = len(v.brushes[0].sides)
    assert not any(extents.clamp(v).values()) and len(v.brushes[0].sides) == n

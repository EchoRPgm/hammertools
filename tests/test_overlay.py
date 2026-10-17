from srctools import VMF, Vec

from hammertools import overlay


def _box(v, lo, hi, mat="dev/dev_measuregeneric01"):
    s = v.make_prism(Vec(*lo), Vec(*hi), mat=mat).solid
    v.add_brush(s)
    return s


def test_anchors_find_the_shift_and_classify_changes(tmp_path):
    a = VMF()
    for i in range(20):
        _box(a, (i * 64, 0, 0), (i * 64 + 32, 32, 32))
    gone = _box(a, (5000, 0, 0), (5032, 32, 32))
    moved = _box(a, (6000, 0, 0), (6032, 32, 32))
    b = VMF()
    d = Vec(-1024, 3462, 0)
    for s in a.brushes:
        if s is gone:
            continue
        lo, hi = s.get_bbox()
        if s is moved:
            lo, hi = lo + d + Vec(8, 0, 0), hi + d + Vec(8, 0, 0)
        else:
            lo, hi = lo + d, hi + d
        nb = b.make_prism(lo, hi, mat="dev/dev_measuregeneric01").solid
        nb.id = s.id
        b.add_brush(nb)
    # peça recriada com id novo no mesmo lugar e uma peça nova
    first = a.brushes[0].get_bbox()
    new = b.make_prism(first[0] + d + Vec(0, 0, 64), first[1] + d + Vec(0, 0, 64)).solid
    new.id = 99999                        # id que A não tem
    b.add_brush(new)
    res = overlay.compare(a, b)
    assert res.shift == d and res.agree >= 19
    # mudou conta o objeto dos dois lados (A e B)
    assert res.count("só A") == 1 and res.count("mudou") == 2 and res.count("só B") == 1
    out = tmp_path / "o.png"
    w, h, _ = overlay.render(res, out)
    assert out.exists() and w > 0 and h > 0
    assert any("x -1024, y +3462" in l for l in overlay.report(res))

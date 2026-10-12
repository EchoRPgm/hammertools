

def test_snap_hint_planes_aligns_near_coplanar_hint():
    from srctools import VMF, Vec
    from hammertools import fix
    v = VMF()
    wall = v.make_prism(Vec(-877, -4842, -600), Vec(-833, -4832, -472), "rainy/concretewall_jail").solid
    v.add_brush(wall)
    hint = v.make_prism(Vec(-1125, -4842.05, -600), Vec(-457, -4832.05, -472), "TOOLS/TOOLSSKIP")
    hint.north.mat = "TOOLS/TOOLSHINT"
    hint.south.mat = "TOOLS/TOOLSHINT"
    v.add_brush(hint.solid)
    far = v.make_prism(Vec(0, 0, 0), Vec(64, 64.3, 64), "TOOLS/TOOLSHINT").solid   # longe de qualquer parede
    v.add_brush(far)
    moved = fix.snap_hint_planes(v)
    assert sorted(d for _, d in moved) == [0.05, 0.05]
    # o plano de cada face de hint encostou no plano da parede (os pontos das faces laterais não mudam o plano delas)
    assert {round(p.y, 3) for p in hint.south.planes} == {-4842}
    assert {round(p.y, 3) for p in hint.north.planes} == {-4832}
    assert far.get_bbox()[1].y == 64.3


def test_open_uncovered_areaportals_only_when_door_leaves_a_gap():
    from srctools import VMF, Vec, Entity
    from hammertools import fix
    v = VMF()

    def door(name, lo, hi):
        e = Entity(v, {"classname": "func_door", "targetname": name})
        e.solids.append(v.make_prism(Vec(*lo), Vec(*hi), "metal/door").solid)
        v.add_ent(e)

    def portal(target, lo, hi):
        e = Entity(v, {"classname": "func_areaportal", "target": target, "StartOpen": "0"})
        e.solids.append(v.make_prism(Vec(*lo), Vec(*hi), "tools/toolsareaportal").solid)
        v.add_ent(e)
        return e
    door("portao", (-562, -4127, -320), (-262, -4125, -176))        # 300×144 num vão 316×160
    gap = portal("portao", (-570, -4127, -328), (-254, -4125, -168))
    door("cheia", (0, 0, 0), (128, 2, 128))
    ok = portal("cheia", (0, 0, 0), (128, 2, 128))
    assert fix.open_uncovered_areaportals(v) == ["portao"]
    assert gap["target"] == "" and gap["StartOpen"] == "1"
    assert ok["target"] == "cheia" and ok["StartOpen"] == "0"

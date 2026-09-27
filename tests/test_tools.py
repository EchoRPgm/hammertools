from srctools import VMF, Vec
from srctools.vmf import Output

from hammertools import diffvmf, lightmap, rename, retexture


def _mapa():
    v = VMF()
    v.add_brush(v.make_prism(Vec(0, 0, 0), Vec(64, 64, 64), "dev/dev_measuregeneric01").solid)
    v.add_brush(v.make_prism(Vec(64, 0, 0), Vec(128, 64, 64), "dev/dev_measurewall01a").solid)
    porta = v.create_ent("func_door", targetname="porta_1")
    botao = v.create_ent("func_button", targetname="botao_1")
    botao.add_out(Output("OnPressed", "porta_1", "Open", "", 0.0))
    botao.add_out(Output("OnPressed", "porta_*", "Close", "", 1.0))
    v.create_ent("point_template", targetname="tpl", Template01="porta_1")
    v.create_ent("prop_dynamic", targetname="p", parentname="porta_1")
    return v


def test_rename_updates_outputs_and_keyvalues():
    v = _mapa()
    r = rename.rename(v, r"porta_(\d+)", r"door_\1")
    assert r.mapping == {"porta_1": "door_1"}
    assert next(iter(v.by_class["func_door"]))["targetname"] == "door_1"
    outs = next(iter(v.by_class["func_button"])).outputs
    assert outs[0].target == "door_1" and outs[1].target == "porta_*"      # curinga fica, vai pra revisão
    assert r.review and "porta_*" in r.review[0]
    assert next(iter(v.by_class["point_template"]))["Template01"] == "door_1"
    assert next(iter(v.by_class["prop_dynamic"]))["parentname"] == "door_1"


def test_retexture_with_wildcards_and_rescale():
    v = _mapa()
    r = retexture.retexture(v, [("dev/dev_measure*", "concrete/final")], size_of=lambda m: (512, 512) if m == "concrete/final" else (256, 256))
    assert r.faces == 12 and all(s.mat == "concrete/final" for b in v.brushes for s in b.sides)
    assert all(abs(s.uaxis.scale - 0.125) < 1e-6 for b in v.brushes for s in b.sides)   # 0.25 * 256/512


def test_lightmap_report_and_uniform():
    v = _mapa()
    faces = [s for b in v.brushes for s in b.sides]
    faces[0].lightmap = 32
    assert "dev/dev_measuregeneric01" in lightmap.report(v)
    assert lightmap.normalize(v, [], uniform=True) == 1 and not lightmap.report(v)
    assert lightmap.normalize(v, [("dev/*", 64)]) == 12


def test_diff_by_id():
    a = _mapa()
    import copy
    b = copy.deepcopy(a)
    next(iter(b.by_class["func_door"]))["speed"] = "200"
    b.brushes[0].sides[0].mat = "concrete/x"
    b.create_ent("light", origin="0 0 0")
    lines = diffvmf.diff(a, b)
    assert any(l.startswith("+ entidade light") for l in lines)
    assert any("speed" in l for l in lines) and any("concrete/x" in l for l in lines)

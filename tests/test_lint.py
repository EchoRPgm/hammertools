from srctools import VMF, Vec

from hammertools import lint
from hammertools.core import geom


def _room(size=512, height=256, hole=False, inner_mat="dev/dev_measuregeneric01b"):
    """Sala fechada de paredes 16; hole=True abre 64x64 na parede +X."""
    v = VMF()
    for s in v.make_hollow(Vec(-size, -size, 0), Vec(size, size, height), thick=16, mat="tools/toolsnodraw", inner_mat=inner_mat):
        v.add_brush(s)
    if hole:
        wall = next(s for s in v.brushes if s.get_bbox()[0].x >= size - 0.5)
        v.remove_brush(wall)
        lo, hi = Vec(size, -size - 16, -16), Vec(size + 16, size + 16, height + 16)
        for a, b in (((lo.x, lo.y, lo.z), (hi.x, -32, hi.z)), ((lo.x, 32, lo.z), (hi.x, hi.y, hi.z)),
                     ((lo.x, -32, lo.z), (hi.x, 32, 32)), ((lo.x, -32, 96), (hi.x, 32, hi.z))):
            v.add_brush(v.make_prism(Vec(*a), Vec(*b), "dev/dev_measuregeneric01b").solid)
    v.create_ent("info_player_start", origin="0 0 8")
    v.create_ent("light", origin="0 0 128")
    return v


def _brush_ent(v, classname, solids):
    from srctools.vmf import Entity
    e = Entity(v, {"classname": classname}, solids=solids)
    v.add_ent(e)
    return e


class FakeRes(lint.Resources):
    def __init__(self, materials=(), models=None, nonseal=()):
        mats = {m.lower() for m in materials}
        super().__init__(lambda m: m.lower() in mats, lambda m: m.lower() not in nonseal,
                         lambda m: (models or {}).get(m.lower()), source="fake")


def _checks(rep, name):
    return [i for i in rep.issues if i.check == name]


# ----------------------------------------------------------------------------- geometria
def test_face_polys_box():
    v = VMF()
    s = v.make_prism(Vec(0, 0, 0), Vec(64, 32, 16)).solid
    polys = geom.face_polys(s)
    assert all(len(p) == 4 for _, p in polys)
    assert len(geom.vertices(s)) == 8
    top = next(p for side, p in polys if geom.outward(side)[0].z > 0.5)
    assert geom.centroid(top) == Vec(32, 16, 16)


# ----------------------------------------------------------------------------- leak
def test_sealed_room_no_leak():
    rep = lint.run(_room(), checks={"leak"})
    assert not _checks(rep, "leak") and rep.stats["entidades no vazio"] == 0


def test_hole_leaks_with_path():
    rep = lint.run(_room(hole=True), checks={"leak"})
    leaks = _checks(rep, "leak")
    assert {i.msg.split()[0] for i in leaks} == {"info_player_start", "light"}
    assert rep.leak_path and rep.leak_path[-1].x > 512  # caminho sai pelo buraco (+X)
    assert any(abs(p.y) < 32 and 32 < p.z < 96 and 500 < p.x < 540 for p in rep.leak_path)


def test_detail_does_not_seal():
    v = _room(hole=True)
    _brush_ent(v, "func_detail", [v.make_prism(Vec(512, -48, 16), Vec(528, 48, 112), "dev/dev_measuregeneric01b").solid])
    rep = lint.run(v, checks={"leak"})
    assert _checks(rep, "leak")  # func_detail tapando o buraco não sela


def test_world_plug_seals_but_clip_does_not():
    v = _room(hole=True)
    plug = v.make_prism(Vec(512, -48, 16), Vec(528, 48, 112), "dev/dev_measuregeneric01b").solid
    v.add_brush(plug)
    assert not _checks(lint.run(v, checks={"leak"}), "leak")
    for side in plug.sides:
        side.mat = "tools/toolsplayerclip"
    assert _checks(lint.run(v, checks={"leak"}), "leak")


def test_translucent_does_not_seal():
    v = _room(hole=True)
    v.add_brush(v.make_prism(Vec(512, -48, 16), Vec(528, 48, 112), "glass/window01").solid)
    assert not _checks(lint.run(v, FakeRes(), {"leak"}), "leak")
    assert _checks(lint.run(v, FakeRes(nonseal={"glass/window01"}), {"leak"}), "leak")


def test_pointfile(tmp_path):
    rep = lint.run(_room(hole=True), checks={"leak"})
    p = tmp_path / "m.lin"
    lint.write_pointfile(p, rep.leak_path)
    lines = p.read_text().splitlines()
    assert len(lines) == len(rep.leak_path) and len(lines[0].split()) == 3


# ----------------------------------------------------------------------------- nodraw
def test_nodraw_inner_face_is_flagged_outer_is_not():
    v = _room()  # faces externas já são nodraw
    assert not _checks(lint.run(v, checks={"nodraw"}), "nodraw")
    floor = min(v.brushes, key=lambda s: s.get_bbox()[1].z)
    top = next(side for side in floor.sides if geom.outward(side)[0].z > 0.5)
    top.mat = "tools/toolsnodraw"
    hits = _checks(lint.run(v, checks={"nodraw"}), "nodraw")
    assert len(hits) == 1 and "topo" in hits[0].msg


def test_nodraw_covered_by_detail_is_ok():
    v = _room()
    floor = min(v.brushes, key=lambda s: s.get_bbox()[1].z)
    next(side for side in floor.sides if geom.outward(side)[0].z > 0.5).mat = "tools/toolsnodraw"
    _brush_ent(v, "func_detail", [v.make_prism(Vec(-512, -512, 0), Vec(512, 512, 8), "dev/dev_measuregeneric01b").solid])
    assert not _checks(lint.run(v, checks={"nodraw"}), "nodraw")


# ----------------------------------------------------------------------------- duplicados / sobreposição
def test_duplicates():
    v = _room()
    v.add_brush(v.make_prism(Vec(0, 0, 0), Vec(64, 64, 64), "dev/dev_measuregeneric01b").solid)
    v.add_brush(v.make_prism(Vec(0, 0, 0), Vec(64, 64, 64), "dev/dev_measuregeneric01").solid)
    assert len(_checks(lint.run(v, checks={"duplicates"}), "duplicates")) == 1


def test_overlaps_only_detail_or_entities():
    v = _room()
    v.add_brush(v.make_prism(Vec(0, 0, 0), Vec(64, 64, 64), "dev/dev_measuregeneric01b").solid)
    v.add_brush(v.make_prism(Vec(32, 0, 0), Vec(96, 64, 64), "dev/dev_measuregeneric01b").solid)
    rep = lint.run(v, checks={"overlaps"})
    assert not _checks(rep, "overlaps") and rep.stats["sobreposições mundo x mundo (inofensivas)"] == 1
    _brush_ent(v, "func_detail", [v.make_prism(Vec(48, 16, 0), Vec(80, 48, 32), "dev/dev_measuregeneric01b").solid])
    hits = _checks(lint.run(v, checks={"overlaps"}), "overlaps")
    assert len(hits) == 2 and all("func_detail" in h.msg for h in hits)
    # encostado (sem interpenetrar) não conta
    v2 = _room()
    v2.add_brush(v2.make_prism(Vec(0, 0, 0), Vec(64, 64, 64), "dev/dev_measuregeneric01b").solid)
    _brush_ent(v2, "func_detail", [v2.make_prism(Vec(64, 0, 0), Vec(128, 64, 64), "dev/dev_measuregeneric01b").solid])
    assert not _checks(lint.run(v2, checks={"overlaps"}), "overlaps")


def test_overlaps_ignore_trigger():
    v = _room()
    v.add_brush(v.make_prism(Vec(0, 0, 0), Vec(64, 64, 64), "dev/dev_measuregeneric01b").solid)
    _brush_ent(v, "trigger_multiple", [v.make_prism(Vec(0, 0, 0), Vec(64, 64, 64), "tools/toolstrigger").solid])
    assert not _checks(lint.run(v, checks={"overlaps"}), "overlaps")


# ----------------------------------------------------------------------------- recursos do jogo
def test_textures_and_models():
    v = _room()
    v.add_brush(v.make_prism(Vec(0, 0, 0), Vec(64, 64, 64), "custom/nao_existe").solid)
    v.create_ent("prop_static", origin="100 0 0", model="models/a/estatico.mdl")
    v.create_ent("prop_static", origin="200 0 0", model="models/a/dinamico.mdl")
    v.create_ent("prop_physics", origin="300 0 0", model="models/sumiu/x.mdl")
    res = FakeRes(materials={"dev/dev_measuregeneric01b", "tools/toolsnodraw"},
                  models={"models/a/estatico.mdl": {"static": True}, "models/a/dinamico.mdl": {"static": False}})
    rep = lint.run(v, res, {"textures", "models"})
    tex = _checks(rep, "textures")
    assert len(tex) == 1 and "custom/nao_existe" in tex[0].msg and tex[0].group == "custom/"
    mdl = _checks(rep, "models")
    assert {(i.level, "dinamico" in i.msg, "sumiu" in i.msg) for i in mdl} == {("aviso", True, False), ("erro", False, True)}


def test_resources_missing_skips():
    rep = lint.run(_room(), lint.Resources(), {"textures", "models"})
    assert set(rep.skipped) == {"textures", "models"}


def test_gma_roundtrip(tmp_path):
    import struct
    from hammertools.core.gma import GMA, AddonIndex
    files = [("materials/pack/a.vmt", b'"LightmappedGeneric" {}'), ("models/pack/b.mdl", b"IDST" + b"\0" * 148 + struct.pack("<I", 0x10))]
    head = b"GMAD" + bytes([3]) + b"\0" * 16 + b"\0" + b"nome\0desc\0autor\0" + struct.pack("<i", 1)
    lst = b"".join(struct.pack("<I", i + 1) + n.encode() + b"\0" + struct.pack("<qI", len(d), 0) for i, (n, d) in enumerate(files)) + struct.pack("<I", 0)
    p = tmp_path / "x.gma"; p.write_bytes(head + lst + b"".join(d for _, d in files) + b"\0\0\0\0")
    g = GMA(p)
    assert g.read("models/pack/b.mdl")[:4] == b"IDST" and g.read("materials/pack/a.vmt").startswith(b'"Lightmapped')
    idx = AddonIndex([p])
    assert "MATERIALS/PACK/A.VMT" in idx and idx.count == 1


def test_folder_grouping():
    assert lint._folder("props/cs_office/chair.mdl", 2) == "props/cs_office/"
    assert lint._folder("props/chair.mdl", 2) == "props/"
    assert lint._folder("chair.mdl", 2) == "(raiz)"


def test_cli_exit_codes(tmp_path):
    from hammertools.cli import main
    from hammertools.core import vmf as vmfio
    ok, bad = tmp_path / "ok.vmf", tmp_path / "bad.vmf"
    vmfio.save(_room(), ok); vmfio.save(_room(hole=True), bad)
    assert main(["lint", str(ok), "--only", "leak,outputs"]) == 0
    assert main(["lint", str(bad), "--only", "leak", "--pointfile"]) == 1
    assert (tmp_path / "bad.lin").exists()
    assert main(["lint", str(ok), "--only", "banana"]) == 2

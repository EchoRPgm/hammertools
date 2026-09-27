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


def test_texture_examples_and_html(tmp_path):
    v = _room()
    for k in range(7):  # 7 brushes com o material faltando -> 5 exemplos
        v.add_brush(v.make_prism(Vec(k * 80, 0, 0), Vec(k * 80 + 64, 64, 64), "custom/sumiu").solid)
    v.create_ent("infodecal", origin="10 20 30", texture="decals/sumiu_decal")
    res = FakeRes(materials={"dev/dev_measuregeneric01b", "tools/toolsnodraw"})
    rep = lint.run(v, res, {"textures"})
    tex = {i.name: i for i in _checks(rep, "textures")}
    assert tex["custom/sumiu"].count == 7 * 6 and len(tex["custom/sumiu"].examples) == 5
    assert tex["decals/sumiu_decal"].count == 1 and tex["decals/sumiu_decal"].examples[0][0] == Vec(10, 20, 30)
    p = lint.write_html(rep, tmp_path / "r.html", "m.vmf")
    html = p.read_text()
    assert "custom/sumiu" in html and "decals/sumiu_decal" in html and "+37 uso(s)" in html
    by_mat = html.split('id="p-tex"')[1].split('id="p-reg"')[0]
    assert by_mat.count('title="copiar setpos') == 6 and "setpos 10 20 94" in html


def test_cli_html(tmp_path):
    from hammertools.cli import main
    from hammertools.core import vmf as vmfio
    p = tmp_path / "m.vmf"; vmfio.save(_room(), p)
    assert main(["lint", str(p), "--only", "textures", "--html", "--no-open"]) in (0, 1)
    assert (tmp_path / "m.lint.html").exists()


def test_cluster_regions_mix_materials():
    from hammertools.lint import cluster_locations
    items = [("a/x", Vec(0, 0, 0), ""), ("b/y", Vec(100, 0, 0), ""), ("a/x", Vec(200, 50, 0), ""),  # cadeia: tudo junto
             ("c/z", Vec(5000, 0, 0), ""), ("c/z", Vec(5010, 0, 0), ""),
             ("d/w", Vec(-9000, 0, 0), "")]
    g = cluster_locations(items, 256)
    assert [x["count"] for x in g] == [3, 2, 1]
    assert dict(g[0]["materials"]) == {"a/x": 2, "b/y": 1}
    assert len(g[0]["examples"]) == 3 and g[0]["lo"] == Vec(0, 0, 0) and g[0]["hi"] == Vec(200, 50, 0)


def test_html_has_region_tab(tmp_path):
    v = _room()
    for k in range(3):
        v.add_brush(v.make_prism(Vec(k * 80, 0, 0), Vec(k * 80 + 64, 64, 64), "custom/a").solid)
    v.add_brush(v.make_prism(Vec(0, 100, 0), Vec(64, 164, 64), "custom/b").solid)
    rep = lint.run(v, FakeRes(materials={"dev/dev_measuregeneric01b", "tools/toolsnodraw"}), {"textures"})
    assert sum(len(i.locations) for i in rep.issues) == 3 * 6 + 6
    html = lint.write_html(rep, tmp_path / "r.html", "m.vmf", 256).read_text()
    assert 'data-tab="reg"' in html and "Texturas por região <b>1</b>" in html  # tudo perto: uma região só, com os 2 materiais


def test_full_report_dashboard(tmp_path):
    v = _room(hole=True)
    v.add_brush(v.make_prism(Vec(0, 0, 0), Vec(64, 64, 64), "custom/sumiu").solid)
    v.add_brush(v.make_prism(Vec(0, 0, 0), Vec(64, 64, 64), "custom/sumiu").solid)  # duplicado
    v.create_ent("prop_static", origin="100 0 0", model="models/sumiu.mdl")
    rep = lint.run(v, FakeRes(materials={"dev/dev_measuregeneric01b", "tools/toolsnodraw"}), lint.ALL_CHECKS)
    html = lint.write_html(rep, tmp_path / "r.html", "m.vmf").read_text()
    for tab in ("dash", "tex", "reg", "mdl", "tj", "leak", "geo", "ent"):
        assert f'id="p-{tab}"' in html
    dash = html.split('id="p-dash"')[1].split('id="p-tex"')[0]
    # ordem de prioridade: leak antes de texturas antes de modelos antes de duplicados
    pos = [dash.find(t) for t in ("Leak: o mapa vaza", "Texturas faltando", "Modelos faltando", "Brushes duplicados")]
    assert all(p > 0 for p in pos) and pos == sorted(pos)
    assert "Onde concentrar esforço" in dash and "Caminho do leak" in html


def test_nodraw_probe_does_not_see_through_other_floor():
    """Regressão (rp_surdonoso 1860 -9685 -532): laje com fundo nodraw, vão fechado de 81u e outro piso
    embaixo; com voxel grosso a sonda atravessava o piso de baixo e achava a sala jogável debaixo dele."""
    v = _room(height=1024)
    a = v.make_prism(Vec(-512, -512, 600), Vec(512, 512, 640), "dev/dev_measuregeneric01b").solid
    next(s for s in a.sides if geom.outward(s)[0].z < -0.5).mat = "tools/toolsnodraw"
    v.add_brush(a)
    v.add_brush(v.make_prism(Vec(-512, -512, 500), Vec(512, 512, 519), "dev/dev_measuregeneric01b").solid)
    assert not _checks(lint.run(v, checks={"nodraw"}, voxel=80), "nodraw")
    # sem o piso de baixo a face dá mesmo pra sala: tem que acusar
    v.remove_brush(v.brushes[-1])
    assert _checks(lint.run(v, checks={"nodraw"}, voxel=80), "nodraw")


def test_nodraw_needs_line_of_sight_from_an_entity():
    """Espaço ligado ao interior mas que nenhuma entidade enxerga (atrás de parede, passagem em L) não acusa."""
    v = _room(height=256)
    # divisória em x=0 com passagem só no canto y>448: as duas metades são o mesmo espaço pro voxel
    v.add_brush(v.make_prism(Vec(-8, -512, 0), Vec(8, 448, 256), "dev/dev_measuregeneric01b").solid)
    pillar = v.make_prism(Vec(200, -32, 0), Vec(264, 32, 128), "dev/dev_measuregeneric01b").solid
    next(s for s in pillar.sides if geom.outward(s)[0].x < -0.5).mat = "tools/toolsnodraw"  # face virada pra divisória
    v.add_brush(pillar)
    for e in list(v.entities):
        if e["classname"] != "worldspawn":
            v.remove_ent(e)
    v.create_ent("info_player_start", origin="-300 0 8")  # do outro lado da divisória
    assert not _checks(lint.run(v, checks={"nodraw"}), "nodraw")
    v.create_ent("light", origin="100 0 64")  # agora alguém do mesmo lado enxerga a face
    hits = _checks(lint.run(v, checks={"nodraw"}), "nodraw")
    assert len(hits) == 1 and "light a" in hits[0].msg


def test_nodraw_hidden_by_prop_bbox():
    """Regressão (rp_surdonoso -3394 -10900 -152): batente nodraw atrás do modelo de janela que preenche o vão."""
    v = _room()
    pillar = v.make_prism(Vec(200, -32, 0), Vec(264, 32, 128), "dev/dev_measuregeneric01b").solid
    next(s for s in pillar.sides if geom.outward(s)[0].x < -0.5).mat = "tools/toolsnodraw"
    v.add_brush(pillar)
    assert _checks(lint.run(v, checks={"nodraw"}), "nodraw")  # sem o prop: à vista (info_player_start enxerga)
    # modelo girado 90°: comprido em Y, encostado na face -X do pilar
    v.create_ent("prop_static", origin="196 0 64", angles="0 90 0", model="models/janela.mdl")
    res = FakeRes()
    res.model_info = lambda m: {"static": True, "mins": Vec(-58, -5, -66), "maxs": Vec(58, 5, 66)}  # cobre a face toda
    assert not _checks(lint.run(v, res, checks={"nodraw"}), "nodraw")
    # modelo cobrindo só 32u de uma face de 128u: o resto do batente fica à vista
    res.model_info = lambda m: {"static": True, "mins": Vec(-58, -5, -16), "maxs": Vec(58, 5, 16)}
    assert _checks(lint.run(v, res, checks={"nodraw"}), "nodraw")


def test_disp_triangles_follow_generator_layout():
    from hammertools.core.disp import terrain_tile
    v = VMF()
    s = terrain_tile(v, Vec(0, 0, 0), Vec(512, 256, 0), 16, 2, "nature/grass", lambda u, w: 100 * u + 10 * w)
    tris = geom.disp_triangles(s)
    assert len(tris) == 2 * 4 * 4
    pts = {tuple(round(c) for c in p) for t in tris for p in t}
    assert (0, 0, 0) in pts and (512, 0, 100) in pts and (512, 256, 110) in pts and (0, 256, 10) in pts
    hit = min(h for t in tris if (h := geom.ray_triangle(Vec(256, 128, 500), Vec(0, 0, -1), t)) is not None)
    assert abs(hit - (500 - 55)) < 0.5  # 100*0.5 + 10*0.5


def test_nodraw_under_displacement_terrain_not_seen():
    """Regressão (rp_surdonoso z -2035): árvore em cima do terreno 'via' a caixa nodraw debaixo do chão
    porque o raio testava o brush-base do displacement, não a superfície elevada."""
    from hammertools.core.disp import terrain_tile
    v = _room(height=1024)
    # terreno cobrindo a sala, brush-base fino em z 300..316 e superfície subindo 200u
    v.add_brush(terrain_tile(v, Vec(-512, -512, 316), Vec(512, 512, 316), 16, 2, "nature/grass", lambda u, w: 200))
    box = v.make_prism(Vec(-64, -64, 380), Vec(64, 64, 400), "dev/dev_measuregeneric01b").solid  # entre base e superfície
    next(x for x in box.sides if geom.outward(x)[0].z > 0.5).mat = "tools/toolsnodraw"  # só o topo, virado pra árvore
    v.add_brush(box)
    for e in list(v.entities):
        if e["classname"] != "worldspawn":
            v.remove_ent(e)
    v.create_ent("info_player_start", origin="0 0 8")
    v.create_ent("prop_static", origin="0 0 700", model="models/arvore.mdl")  # em cima do terreno (516)
    hits = [i for i in _checks(lint.run(v, checks={"nodraw"}, voxel=8), "nodraw") if "solid %d," % box.id in i.msg]
    assert not hits


def test_nodraw_on_translucent_brush_is_ok():
    """Regressão (rp_surdonoso 495 -8295 -535): vidro de janela com o lado de dentro nodraw."""
    v = _room()
    pane = v.make_prism(Vec(-64, 100, 32), Vec(64, 109, 96), "glass/vidro").solid
    next(s for s in pane.sides if geom.outward(s)[0].y < -0.5).mat = "tools/toolsnodraw"  # lado virado pro spawn
    v.add_brush(pane)
    assert _checks(lint.run(v, FakeRes(materials={"glass/vidro"}), checks={"nodraw"}), "nodraw")  # vidro opaco: acusa
    assert not _checks(lint.run(v, FakeRes(materials={"glass/vidro"}, nonseal={"glass/vidro"}), checks={"nodraw"}), "nodraw")


def test_nodraw_under_prop_with_small_gap():
    """Regressão (rp_surdonoso -160 -8811 24): piso nodraw do elevador, modelo com o próprio piso 5,5u acima."""
    v = _room()
    floor = v.make_prism(Vec(-64, -64, 10), Vec(64, 64, 24), "tools/toolsnodraw").solid
    v.add_brush(floor)
    v.create_ent("prop_static", origin="0 0 83", model="models/elevador.mdl")
    res = FakeRes()
    res.model_info = lambda m: {"static": True, "mins": Vec(-60, -62, -53.5), "maxs": Vec(66, 62, 52)}
    hits = [i for i in _checks(lint.run(v, res, checks={"nodraw"}), "nodraw") if "solid %d," % floor.id in i.msg]
    assert not any("(topo)" in i.msg for i in hits)


def test_nodraw_scenery_prop_is_not_a_viewer():
    """Árvore gigante (caixa > 256u) não conta como testemunha: a base do tronco não é onde o jogador fica."""
    v = _room()
    pillar = v.make_prism(Vec(200, -32, 0), Vec(264, 32, 128), "dev/dev_measuregeneric01b").solid
    next(s for s in pillar.sides if geom.outward(s)[0].x < -0.5).mat = "tools/toolsnodraw"
    v.add_brush(pillar)
    for e in list(v.entities):
        if e["classname"] != "worldspawn":
            v.remove_ent(e)
    v.create_ent("prop_static", origin="-100 0 8", model="models/arvore.mdl")
    res = FakeRes()
    res.model_info = lambda m: {"static": True, "mins": Vec(-200, -200, 0), "maxs": Vec(200, 200, 700)}
    assert not _checks(lint.run(v, res, checks={"nodraw"}), "nodraw")
    res.model_info = lambda m: {"static": True, "mins": Vec(-16, -16, 0), "maxs": Vec(16, 16, 40)}
    assert _checks(lint.run(v, res, checks={"nodraw"}), "nodraw")


def test_report_area_filter_and_grouping(tmp_path):
    import json, re
    v = _room()
    v.add_brush(v.make_prism(Vec(0, 0, 0), Vec(64, 64, 64), "custom/sumiu").solid)       # área 0_0_0
    v.add_brush(v.make_prism(Vec(-300, -300, 0), Vec(-236, -236, 64), "custom/sumiu").solid)  # área -1_-1_0
    rep = lint.run(v, FakeRes(materials={"dev/dev_measuregeneric01b", "tools/toolsnodraw"}), lint.ALL_CHECKS)
    html = lint.write_html(rep, tmp_path / "r.html", "m.vmf", area_size=256).read_text()
    assert 'id="area"' in html and 'id="group"' in html
    areas = json.loads(re.search(r'<script type="application/json" id="areas">(.*?)</script>', html, re.S).group(1))
    keys = {a["k"] for a in areas}
    assert {"0_0_0", "-2_-2_0"} <= keys and areas == sorted(areas, key=lambda a: -a["n"])
    assert 'data-area="0_0_0"' in html and 'data-area="-2_-2_0"' in html
    assert "data-area-go=" in html  # painel: botão "filtrar esta área"


def test_nodraw_ramp_under_stair_steps_is_hidden():
    """Regressão (rp_surdonoso 3414 -12011 -360): cunha func_detail com rampa nodraw embaixo dos degraus; a
    rampa só encosta nas quinas dos degraus e o centro dela cai exatamente numa quina."""
    v = _room()
    # cunha: caixa y -24..24, z 0..32 com o topo inclinado em rampa de (y -24, z 0) a (y 24, z 32)
    prism = v.make_prism(Vec(-32, -24, 0), Vec(32, 24, 32), "dev/dev_measuregeneric01b")
    wedge = prism.solid
    ramp = prism.top
    ramp.planes = [Vec(p.x, p.y, (p.y + 24) * 32 / 48) for p in ramp.planes]
    wedge.sides.remove(prism.north if geom.outward(prism.north)[0].y < -0.5 else prism.south)
    ramp.mat = "tools/toolsnodraw"
    steps = [v.make_prism(Vec(-32, y0, 0), Vec(32, y0 + 12, z1), "dev/dev_measuregeneric01b").solid
             for y0, z1 in ((-24, 8), (-12, 16), (0, 24), (12, 32))]
    _brush_ent(v, "func_detail", [wedge])
    _brush_ent(v, "func_detail", steps)
    hits = [i for i in _checks(lint.run(v, checks={"nodraw"}), "nodraw") if "solid %d," % wedge.id in i.msg]
    assert not hits
    # sem os degraus a rampa fica exposta: acusa
    for e in list(v.entities):
        if e.solids and e.solids[0] is steps[0]:
            v.remove_ent(e)
    assert [i for i in _checks(lint.run(v, checks={"nodraw"}), "nodraw") if "solid %d," % wedge.id in i.msg]


def test_tjfix_marks_resolved_faces(tmp_path):
    from srctools.vmf import Entity
    v = VMF()
    slab = v.make_prism(Vec(-256, -64, 0), Vec(256, 64, 16), "dev/dev_measuregeneric01b").solid
    v.add_ent(Entity(v, {"classname": "func_detail"}, solids=[slab]))
    blocks = [v.make_prism(Vec(x, 64, 0), Vec(x + 48, 96, 40), "dev/dev_measuregeneric01b").solid for x in (-160, -32, 96)]
    v.add_ent(Entity(v, {"classname": "func_detail"}, solids=blocks))
    rep = lint.run(v, FakeRes(), {"tjunctions"})
    slab_faces = [f for f in rep.data["tjunctions"] if f["solid"] == slab.id]
    assert slab_faces
    # só os blocos viraram func_brush: a laje fica sem vértices alheios -> resolvida
    lint.apply_tjfix(rep, {"result": "convertido", "func_detail": 1, "func_brush": 1, "solids": [b.id for b in blocks], "indices": 42})
    assert all(f["status"] == "conv" and f["left"] == 0 for f in slab_faces)
    html = lint.write_html(rep, tmp_path / "r.html", "m.vmf").read_text()
    assert "resolvida na compilação" in html and "índices reais no BSP" in html and "consertadas na compilação" in html
    # compilado com -notjunc: tudo pendente
    lint.apply_tjfix(rep, {"result": "notjunc"})
    assert all(f["status"] == "pend" for f in rep.data["tjunctions"])


def test_model_shader_on_brush_is_flagged():
    """Regressão (rp_surdonoso 5337 -9769): faixa de grama com material de modelo (VertexLitGeneric) em brush."""
    v = _room()
    v.add_brush(v.make_prism(Vec(-64, -64, 0), Vec(64, 64, 8), "models/grama").solid)
    vmts = {"materials/models/grama.vmt": b'"VertexLitGeneric"\n{\n"$basetexture" "forest/grass_01"\n}',
            "materials/dev/dev_measuregeneric01b.vmt": b'"LightmappedGeneric" { }',
            "materials/tools/toolsnodraw.vmt": b'"LightmappedGeneric" { }'}
    res = FakeRes(materials={"models/grama", "dev/dev_measuregeneric01b", "tools/toolsnodraw"})
    res.read = lambda p, limit=None: vmts.get(p.lower())
    hits = [i for i in _checks(lint.run(v, res, {"textures"}), "textures") if i.group == "shader de modelo"]
    assert len(hits) == 1 and hits[0].name == "models/grama" and hits[0].count == 6


def test_fix_model_shader_writes_lightmapped_copy(tmp_path):
    from hammertools import fix
    v = _room()
    v.add_brush(v.make_prism(Vec(-64, -64, 0), Vec(64, 64, 8), "materials/models/grama").solid)
    v.create_ent("info_overlay", material="materials/models/grama")  # overlay não muda
    vmts = {"materials/materials/models/grama.vmt": b'"VertexLitGeneric"\n{\n"$basetexture" "forest/grass_01"\n"$surfaceprop" "grass"\n"$phong" "1"\n}'}
    res = FakeRes(materials={"materials/models/grama"})
    res.read = lambda p, limit=None: vmts.get(p.lower())
    r = fix.fix_model_shaders(v, res, "m_fix")
    assert r.faces == 6 and r.replaced == {"materials/models/grama": "m_fix/models/grama"}
    txt = r.materials["m_fix/models/grama"]
    assert txt.startswith('"LightmappedGeneric"') and '"$basetexture" "forest/grass_01"' in txt and "$phong" not in txt
    assert next(iter(v.by_class["info_overlay"]))["material"] == "materials/models/grama"
    assert fix.write_materials(r, tmp_path)[0].read_text() == txt


def _logic_map():
    v = _room()
    v.create_ent("func_breakable_surf", targetname="vidro")
    v.create_ent("point_template", targetname="t_ok", Template01="vidro")
    v.create_ent("point_template", targetname="t_nunca", Template01="vidro")          # nunca acionado + duplicado
    v.create_ent("point_template", targetname="t_vazio", Template01="nao_existe")     # não recria nada
    relay = v.create_ent("logic_relay", targetname="r")
    relay.add_out(__import__("srctools").vmf.Output("OnTrigger", "t_ok", "ForceSpawn", "", 1.0))
    loop = v.create_ent("logic_relay", targetname="loop")
    loop.add_out(__import__("srctools").vmf.Output("OnTrigger", "loop", "Trigger", "", 0.0))   # trava
    timer = v.create_ent("logic_relay", targetname="timer")
    timer.add_out(__import__("srctools").vmf.Output("OnTrigger", "timer", "Trigger", "", 300.0))  # temporizador: ok
    return v


def test_logic_checks():
    msgs = [i.msg for i in _checks(lint.run(_logic_map(), checks={"logic"}), "logic")]
    assert any("t_vazio" in m and "não recria nada" in m for m in msgs)
    assert any("t_nunca" in m and "nunca é acionado" in m for m in msgs)
    assert not any("'t_ok' nunca" in m for m in msgs)
    assert not any("'t_vazio' nunca" in m for m in msgs)  # já é erro por não recriar nada
    assert any("'vidro' está em 2 templates" in m for m in msgs)
    loops = [m for m in msgs if "laço" in m]
    assert len(loops) == 1 and "loop" in loops[0] and "timer" not in loops[0]


def test_perf_prop_fade_and_embedded_window():
    from hammertools import fix
    v = _room()
    v.create_ent("prop_static", origin="0 0 0", model="models/caixa.mdl")                  # solta no chão: ganha fade
    # janela no vão entre duas paredes (batentes) em y=-64..-48 e y=48..64
    v.add_brush(v.make_prism(Vec(200, -64, 0), Vec(216, -48, 128), "dev/dev_measuregeneric01b").solid)
    v.add_brush(v.make_prism(Vec(200, 48, 0), Vec(216, 64, 128), "dev/dev_measuregeneric01b").solid)
    v.create_ent("prop_static", origin="208 0 64", model="models/janela.mdl")               # encaixada: sem fade
    sizes = {"models/caixa.mdl": (Vec(-12, -12, 0), Vec(12, 12, 20)), "models/janela.mdl": (Vec(-4, -48, -48), Vec(4, 48, 48))}
    res = FakeRes()
    res.model_info = lambda m: {"static": True, "mins": sizes[m.lower()][0], "maxs": sizes[m.lower()][1]}
    rep = lint.run(v, res, {"perf"})
    msgs = [i.msg for i in _checks(rep, "perf")]
    assert any("caixa.mdl" in m and "1200/1500" in m for m in msgs) and not any("janela" in m for m in msgs)
    assert fix.fix_fades(v, res) == 1
    caixa = next(e for e in v.entities if e.get("model") == "models/caixa.mdl")
    assert (caixa["fademindist"], caixa["fademaxdist"]) == ("1200", "1500")


def test_lintignore_regions():
    v = _room()
    floor = min(v.brushes, key=lambda s: s.get_bbox()[1].z)
    next(side for side in floor.sides if geom.outward(side)[0].z > 0.5).mat = "tools/toolsnodraw"
    rep = lint.run(v, checks={"nodraw"})
    assert _checks(rep, "nodraw")
    n = lint.apply_ignore(rep, {"regions": [{"box": [[-600, -600, -100], [600, 600, 100]], "checks": ["nodraw"], "motivo": "teste"}]})
    assert n >= 1 and not _checks(rep, "nodraw") and rep.stats["ignorados (lintignore)"] == n


def test_vmt_syntax_error_is_flagged():
    v = _room()
    v.add_brush(v.make_prism(Vec(-64, -64, 0), Vec(64, 64, 8), "vidro/quebrado").solid)
    vmts = {"materials/vidro/quebrado.vmt": b'"UnlitGeneric"\r\n{\r\n\t"$basetexture" "x"\r\n\t"$surfaceprop" "glass\r\n}'}
    res = FakeRes(materials={"vidro/quebrado", "dev/dev_measuregeneric01b", "tools/toolsnodraw"})
    res.read = lambda p, limit=None: vmts.get(p.lower())
    hits = [i for i in _checks(lint.run(v, res, {"textures"}), "textures") if i.group == "vmt quebrado"]
    assert len(hits) == 1 and hits[0].name == "vidro/quebrado" and "line" in hits[0].msg.lower()


def test_active_cordon_is_flagged():
    from srctools.vmf import Cordon
    v = _room()
    assert lint.active_cordon(v) is None
    v.cordon_enabled = True
    v.cordons.append(Cordon(v, Vec(-10, -10, -10), Vec(10, 10, 10), is_active=True))
    assert lint.active_cordon(v) == ((-10, -10, -10), (10, 10, 10))
    assert any("cordon ativo" in i.msg for i in _checks(lint.run(v, checks={"markers"}), "markers"))

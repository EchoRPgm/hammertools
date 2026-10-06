import sys
from pathlib import Path

from srctools import Vec
from srctools.vmf import Entity

from hammertools import autoprop
from hammertools.core import vmf as vmfio


class FakeRes:
    """Materiais do jogo: um lightmapped normal, uma água (fica de fora) e as texturas de 256x128."""
    read = None

    def __init__(self):
        import struct
        self.files = {
            "materials/dev/a.vmt": b'"LightmappedGeneric" { "$basetexture" "dev/a" "$surfaceprop" "metal" }',
            "materials/dev/agua.vmt": b'"Water" { "$basetexture" "dev/a" }',
            "materials/dev/a.vtf": b"VTF\0" + b"\0" * 12 + struct.pack("<HH", 256, 128) + b"\0" * 12,
        }
        self.read = lambda p, limit=None: (self.files.get(p.lower())[:limit] if limit else self.files.get(p.lower())) if p.lower() in self.files else None


def _room_with_details(room, n=4, mat="dev/a"):
    for i in range(n):
        blk = room.make_prism(Vec(i * 64, 0, 0), Vec(i * 64 + 32, 128, 16), mat).solid
        room.add_ent(Entity(room, {"classname": "func_detail"}, solids=[blk]))
    return room


def test_candidates_skip_big_and_water(room):
    _room_with_details(room)
    floor = room.make_prism(Vec(-1024, -1024, -32), Vec(1024, 1024, -16), "dev/a").solid
    room.add_ent(Entity(room, {"classname": "func_detail"}, solids=[floor]))
    agua = room.make_prism(Vec(0, 300, 0), Vec(32, 332, 16), "dev/agua").solid
    room.add_ent(Entity(room, {"classname": "func_detail"}, solids=[agua]))
    c = autoprop.candidates(room, autoprop.Materials(FakeRes()))
    assert len(c) == 4                                   # o piso grande e a água ficam como detail


def test_choose_meets_both_goals(room):
    _room_with_details(room)
    cands = autoprop.candidates(room, autoprop.Materials(FakeRes()))
    est = autoprop.Estimate(idx_total=80000, verts_total=70000,
                            idx_cost={s.id: 8000 for _, s in cands}, vert_cost={s.id: 4000 for _, s in cands})
    chosen, st = autoprop.choose(est, cands, calib=1.0, vcalib=1.0)
    assert st["suficiente"] and st["tira_idx"] >= st["need_idx"] and st["tira_verts"] >= st["need_verts"]
    est_ok = autoprop.Estimate(idx_total=1000, verts_total=1000)
    assert autoprop.choose(est_ok, cands, 1.0, 1.0)[0] == []          # já cabe: nada a converter


def test_smd_rotated_and_origin_inside_detail(room):
    _room_with_details(room, n=1)
    mats = autoprop.Materials(FakeRes())
    (e, s), = autoprop.candidates(room, mats)
    cl = autoprop.Cluster((0, 0, 0), [(e, s)])
    origin, _name, files, vmts = autoprop.build_files(cl, mats, "m")
    lo, hi = s.get_bbox()
    assert lo.x <= origin.x <= hi.x and lo.y <= origin.y <= hi.y and lo.z <= origin.z <= hi.z
    pts = [tuple(map(float, l.split()[1:4])) for l in files["ref.smd"].splitlines() if l.startswith("0 ") and len(l.split()) == 12]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    assert max(ys) - min(ys) == 32 and max(xs) - min(xs) == 128   # bloco 32 x 128 sai girado -90° (o studiomdl gira +90)
    assert "VertexLitGeneric" in vmts["dev_a"] and '"$surfaceprop" "metal"' in vmts["dev_a"]
    assert '$surfaceprop "metal"' in files["model.qc"] and "$staticprop" in files["model.qc"]


def test_apply_swaps_detail_for_props_with_fake_studiomdl(room, tmp_path, monkeypatch):
    _room_with_details(room)
    game = tmp_path / "game"
    (game.parent / "bin").mkdir(parents=True)
    vbsp = game.parent / "bin" / "vbsp"
    vbsp.write_text("")
    (game.parent / "bin" / "studiomdl").write_text("")
    out = tmp_path / "build" / "m.vmf"
    out.parent.mkdir()
    room.create_ent("prop_static", model="models/props_c17/oildrum001.mdl", origin="0 0 0",
                    disablevertexlighting="0")   # prop do próprio mapa, com o "0" que o Hammer++ grava em todo prop
    vmfio.save(room, out)
    from hammertools import lint
    monkeypatch.setattr(lint.Resources, "from_game", classmethod(lambda cls, *a, **k: FakeRes()))
    monkeypatch.setattr(autoprop, "estimate", lambda v: autoprop.Estimate(80000, 70000,
                        {s.id: 9000 for e in v.by_class["func_detail"] for s in e.solids},
                        {s.id: 9000 for e in v.by_class["func_detail"] for s in e.solids}))

    def fake_studiomdl(cmd, cwd):   # "compila": cria o .mdl onde o studiomdl criaria
        qc = Path(cmd[-1]).read_text()
        name = qc.split('"')[1]
        (game / "models" / name).parent.mkdir(parents=True, exist_ok=True)
        (game / "models" / name).write_text("mdl")
        return 0
    info = autoprop.apply(out, game, vbsp, 1.0, 1.0, log=lambda m: None, run=fake_studiomdl)
    v = vmfio.load(out)
    props = [e for e in v.entities if e["classname"] == "prop_static"]
    assert info["models"] == len([p for p in props if p["solid"] == "0" and "ht_prop" in p["model"]]) >= 1 and info["falhas"] == 0
    gen = [p for p in props if "ht_prop" in p["model"]]
    assert all(p["model"].startswith("models/ht_prop/m/") for p in gen)
    assert len(v.by_class["func_detail"]) < 4
    visual = [p for p in gen if p["solid"] == "0"]
    coll = [p for p in gen if p["solid"] == "6"]
    # o visível não tem colisão (o studiomdl fundia peças e tampava portas) nem faz sombra
    assert visual and all(p["disableshadows"] == "1" for p in visual)
    # a colisão vem de modelos à parte, nunca desenhados nem iluminados, e faz a sombra (forma exata dos brushes)
    assert coll and all(p["fademaxdist"] == "1" and p["disableshadows"] == "0" and p["disablevertexlighting"] == "1" for p in coll)
    assert {p["origin"] for p in coll} <= {p["origin"] for p in visual}
    # luz por vértice só nos gerados: o prop do mapa continua iluminado como antes (mapa não escurece)
    own = [p for p in props if "ht_prop" not in p["model"]]
    assert own and all(p["disablevertexlighting"] == "1" for p in own)
    qcs = [q.read_text() for q in (tmp_path / "build").rglob("model.qc")]
    assert any("$collisionmodel" not in q and "ref.smd" in q for q in qcs)
    assert any("$collisionmodel" in q and "$maxconvexpieces" in q for q in qcs)
    assert (game / "materials" / "models" / "ht_prop" / "m" / "dev_a.vmt").exists()
    # de novo com o mesmo conteúdo: tudo do cache, nenhuma chamada ao studiomdl
    vmfio.save(room, out)
    calls = []
    autoprop.apply(out, game, vbsp, 1.0, 1.0, log=lambda m: None, run=lambda c, d: calls.append(c) or 0)
    assert calls == []


def test_model_vmt_keeps_backslash_paths_literal():
    """VMT com barra invertida (custom_textures\\txt_chao): o Source não tem escapes; com escapes o \\t virava TAB e o
    prop gerado aparecia com o xadrez roxo (8 materiais do rp_surdonoso)."""
    res = FakeRes()
    res.files["materials/custom_textures/txt_chao.vmt"] = b'"LightmappedGeneric"\n{\n"$basetexture" "custom_textures\\txt_chao"\n}\n'
    res.files["materials/dunc_temp/vegas/w.vmt"] = b'"LightmappedGeneric" { "$basetexture" "dunc_temp\\vegas\\w" "$bumpmap" "dunc_temp\\vegas\\w_n" }'
    mats = autoprop.Materials(res)
    a = mats.model_vmt("custom_textures/txt_chao")
    b = mats.model_vmt("dunc_temp/vegas/w")
    assert '"$basetexture" "custom_textures/txt_chao"' in a
    assert '"$basetexture" "dunc_temp/vegas/w"' in b and '"$bumpmap" "dunc_temp/vegas/w_n"' in b
    assert "\t" not in a.replace('\t"$', '"$') and "\x0b" not in b


def test_only_nodraw_among_tool_materials_goes_into_props():
    """toolsinvisibleladder virava colisão sólida dentro do prop (escada de mão que não sobe e parede invisível)."""
    res = FakeRes()
    res.files["materials/glass/janela.vmt"] = b'"LightmappedGeneric" { "$basetexture" "dev/a" "%compilenonsolid" "1" }'
    mats = autoprop.Materials(res)
    assert mats.usable("TOOLS/TOOLSNODRAW")
    for m in ("tools/toolsinvisibleladder", "tools/toolsplayerclip", "tools/toolsskip", "tools/toolstrigger", "glass/janela"):
        assert not mats.usable(m), m
    assert mats.usable("dev/a") and mats.surfaceprop("dev/a") == "metal"



def test_contact_colors_never_put_touching_brushes_together():
    """Batente esquerdo, verga e batente direito se tocam: no mesmo modelo de colisão viravam um casco só (porta)."""
    from srctools import VMF
    v = VMF()
    def box(lo, hi):
        return v.make_prism(Vec(*lo), Vec(*hi)).solid
    jamb_l, lintel, jamb_r = box((0, 0, 0), (8, 8, 100)), box((0, 0, 100), (60, 8, 108)), box((52, 0, 0), (60, 8, 100))
    far = box((500, 500, 0), (508, 508, 8))
    colors = autoprop.contact_colors([jamb_l, lintel, jamb_r, far])
    assert colors[0] != colors[1] and colors[2] != colors[1]
    assert len(set(colors)) == 2           # os batentes não se tocam: podem dividir o modelo


def test_same_group_in_any_order_gives_same_origin_and_model(room):
    """A ordem dos solids no grupo mudava entre compilações: com degraus iguais a origem mudava e o cache reaproveitava o
    modelo da outra origem (escada 128u abaixo, dentro da parede, no rp_surdonoso)."""
    _room_with_details(room, n=4)
    mats = autoprop.Materials(FakeRes())
    cands = autoprop.candidates(room, mats)
    a = autoprop.build_files(autoprop.Cluster((0, 0, 0), list(cands)), mats, "m")
    b = autoprop.build_files(autoprop.Cluster((0, 0, 0), list(reversed(cands))), mats, "m")
    assert a[0] == b[0] and a[1] == b[1] and a[2] == b[2]
    ca = autoprop.collision_models(autoprop.Cluster((0, 0, 0), list(cands)), a[0], mats, "m")
    cb = autoprop.collision_models(autoprop.Cluster((0, 0, 0), list(reversed(cands))), b[0], mats, "m")
    assert [n for n, _ in ca] == [n for n, _ in cb]

import struct

from srctools import VMF, Vec

from hammertools import content


def _mdl(textures, cdmats):
    """studiohdr_t mínimo: cabeçalho de 232 bytes + tabela de texturas + cdmaterials + strings."""
    head = bytearray(232)
    head[:4] = b"IDST"
    tex_i = len(head)
    body = bytearray(64 * len(textures))
    cd_i = tex_i + len(body)
    cdtab = bytearray(4 * len(cdmats))
    strings = bytearray()
    base = cd_i + len(cdtab)
    tex_name_off = []
    for t in textures:
        tex_name_off.append(base + len(strings)); strings += t.encode() + b"\0"
    cd_off = []
    for c in cdmats:
        cd_off.append(base + len(strings)); strings += c.encode() + b"\0"
    for k, off in enumerate(tex_name_off):
        struct.pack_into("<i", body, 64 * k, off - (tex_i + 64 * k))
    for k, off in enumerate(cd_off):
        struct.pack_into("<i", cdtab, 4 * k, off)
    struct.pack_into("<iiii", head, 204, len(textures), tex_i, len(cdmats), cd_i)
    return bytes(head + body + cdtab + strings)


def test_mdl_textures():
    data = _mdl(["chair_seat", "chair_legs"], ["models/props/cadeira/", "models/shared"])
    assert content.mdl_textures(data) == ["models/props/cadeira/chair_seat", "models/shared/chair_seat",
                                          "models/props/cadeira/chair_legs", "models/shared/chair_legs"]


def test_vmt_deps():
    vtf, vmt = content.vmt_deps('"LightmappedGeneric" { "$basetexture" "Custom/Wall" "$bumpmap" "custom/wall_n" '
                                '"$envmap" "env_cubemap" "$color" "[1 1 1]" "$surfaceprop" "concrete" }')
    assert vtf == {"custom/wall", "custom/wall_n"} and vmt == set()
    vtf, vmt = content.vmt_deps('"patch" { "include" "materials/custom/base.vmt" "insert" { "$envmaptint" "[.5 .5 .5]" } }')
    assert vmt == {"custom/base"}


def _src(files):
    files = {content.norm(k): v for k, v in files.items()}
    return content.Source("teste", lambda p: content.norm(p) in files, lambda p: files[content.norm(p)])


def test_resolve_copies_only_what_game_lacks():
    v = VMF()
    v.add_brush(v.make_prism(Vec(0, 0, 0), Vec(64, 64, 64), "custom/wall").solid)
    v.add_brush(v.make_prism(Vec(0, 0, 64), Vec(64, 64, 128), "dev/base").solid)
    v.create_ent("prop_static", origin="0 0 0", model="models/custom/chair.mdl")
    v.create_ent("prop_static", origin="0 0 0", model="models/sumiu.mdl")
    v.spawn["skyname"] = "sky_custom"
    game = {"materials/dev/base.vmt": b'"LightmappedGeneric" { "$basetexture" "dev/base" }', "materials/dev/base.vtf": b"x"}
    src = _src({
        "materials/custom/wall.vmt": b'"LightmappedGeneric" { "$basetexture" "custom/wall" "$bumpmap" "custom/wall_n" }',
        "materials/custom/wall.vtf": b"v", "materials/custom/wall_n.vtf": b"n",
        "models/custom/chair.mdl": _mdl(["seat"], ["models/custom/"]), "models/custom/chair.vvd": b"d",
        "models/custom/chair.dx90.vtx": b"t", "models/custom/chair.phy": b"p",
        "materials/models/custom/seat.vmt": b'"VertexLitGeneric" { "$basetexture" "models/custom/seat" }',
        "materials/models/custom/seat.vtf": b"s",
    })
    res = content.resolve(v, lambda p: content.norm(p) in game, lambda p: game.get(content.norm(p)), [src])
    assert set(res.copy) == {
        "materials/custom/wall.vmt", "materials/custom/wall.vtf", "materials/custom/wall_n.vtf",
        "models/custom/chair.mdl", "models/custom/chair.vvd", "models/custom/chair.dx90.vtx", "models/custom/chair.phy",
        "materials/models/custom/seat.vmt", "materials/models/custom/seat.vtf"}
    assert "materials/dev/base.vmt" in res.in_game
    assert "models/sumiu.mdl" in res.missing and any(m.startswith("skybox/sky_custom") for m in res.missing)


def test_write(tmp_path):
    src = _src({"materials/a/b.vmt": b"x"})
    res = content.Result(copy={"materials/a/b.vmt": "teste"})
    assert content.write(res, [src], tmp_path / "out", "m content") == 1
    assert (tmp_path / "out/materials/a/b.vmt").read_bytes() == b"x" and (tmp_path / "out/addon.json").exists()

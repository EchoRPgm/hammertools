"""Cache do vvis/vrad por conteúdo do BSP (hammertools/bspcache.py) e a integração no `ht compile`."""
import io
import stat
import struct
import sys
import zipfile
from pathlib import Path

from srctools.bsp import BSP, BSP_LUMPS

from hammertools import bspcache as bc
from hammertools import compile as htc
from hammertools.core import vmf as vmfio

ENTS = (b'{\n"classname" "worldspawn"\n"skyname" "sky_day01_01"\n}\n'
        b'{\n"classname" "light"\n"origin" "0 0 64"\n"_light" "255 255 255 200"\n}\n'
        b'{\n"classname" "prop_physics"\n"origin" "10 0 0"\n"model" "models/props_c17/oildrum001.mdl"\n}\n')


def make_bsp(path: Path, lumps: dict | None = None, revision: int = 7, game_lumps: dict | None = None) -> Path:
    """BSP v20 mínimo: cabeçalho + lumps crus (o resto vazio)."""
    data = {BSP_LUMPS.ENTITIES.value: ENTS + b"\0", BSP_LUMPS.PLANES.value: b"P" * 20}
    gl = game_lumps or {}
    body = struct.pack("<i", len(gl))
    for gid, (ver, raw) in gl.items():
        body += struct.pack("<4sHHii", gid[::-1], 0, ver, 0, len(raw))
    data[BSP_LUMPS.GAME_LUMP.value] = body
    for k, v in (lumps or {}).items():
        data[k.value if hasattr(k, "value") else k] = v
    header = 8 + 64 * 16 + 4
    out = bytearray(header)
    struct.pack_into("<4si", out, 0, b"VBSP", 20)
    for k in range(64):
        raw = data.get(k, b"")
        ofs = len(out)
        if k == BSP_LUMPS.GAME_LUMP.value and gl:
            # offsets dos game lumps são absolutos no arquivo
            fixed = bytearray(raw)
            pos = ofs + len(raw)
            extra = b""
            for i, (gid, (ver, gdata)) in enumerate(gl.items()):
                struct.pack_into("<i", fixed, 4 + 16 * i + 8, pos)
                pos += len(gdata)
                extra += gdata
            raw = bytes(fixed) + extra
        struct.pack_into("<iii4s", out, 8 + 16 * k, ofs if raw else 0, len(raw), 0, b"\0\0\0\0")
        out += raw
    struct.pack_into("<i", out, 8 + 64 * 16, revision)
    path.write_bytes(bytes(out))
    return path


def keys(bsp, prt=None, vis=(), rad=("-bounce", "2")):
    return bc.compute_keys(bsp, prt, list(vis) if vis is not None else None, None, list(rad) if rad is not None else None, None)


def test_same_geometry_entity_that_neither_reads_keeps_both_keys(tmp_path):
    a = keys(make_bsp(tmp_path / "a.bsp"))
    moved = ENTS.replace(b'"10 0 0"', b'"500 20 0"')
    b = keys(make_bsp(tmp_path / "b.bsp", {BSP_LUMPS.ENTITIES: moved + b"\0"}))
    assert a.vis == b.vis and a.rad == b.rad


def test_light_change_keeps_vis_and_invalidates_rad(tmp_path):
    a = keys(make_bsp(tmp_path / "a.bsp"))
    brighter = ENTS.replace(b"255 255 255 200", b"255 255 255 400")
    b = keys(make_bsp(tmp_path / "b.bsp", {BSP_LUMPS.ENTITIES: brighter + b"\0"}))
    assert a.vis == b.vis and a.rad != b.rad


def test_light_moving_in_entity_list_invalidates_rad(tmp_path):
    """O worldlight guarda o índice da entidade dona: luz em outra posição da lista = vrad de novo."""
    a = keys(make_bsp(tmp_path / "a.bsp"))
    first = ENTS.split(b"}\n")
    reordered = b"}\n".join([first[0], first[2], first[1], b""])
    b = keys(make_bsp(tmp_path / "b.bsp", {BSP_LUMPS.ENTITIES: reordered + b"\0"}))
    assert a.vis == b.vis and a.rad != b.rad


def test_brush_entity_and_compile_keys_count_for_rad(tmp_path):
    a = keys(make_bsp(tmp_path / "a.bsp"))
    brush = ENTS + b'{\n"classname" "func_brush"\n"model" "*1"\n"vrad_brush_cast_shadows" "1"\n}\n'
    b = keys(make_bsp(tmp_path / "b.bsp", {BSP_LUMPS.ENTITIES: brush + b"\0"}))
    assert a.vis == b.vis and a.rad != b.rad
    minlight = ENTS.replace(b'"classname" "prop_physics"', b'"classname" "prop_physics"\n"_minlight" "0.5"')
    c = keys(make_bsp(tmp_path / "c.bsp", {BSP_LUMPS.ENTITIES: minlight + b"\0"}))
    assert c.rad != a.rad


def test_spot_target_position_counts_for_rad(tmp_path):
    base = ENTS.replace(b'"_light"', b'"target" "alvo"\n"_light"') + b'{\n"classname" "info_target"\n"targetname" "alvo"\n"origin" "0 0 0"\n}\n'
    a = keys(make_bsp(tmp_path / "a.bsp", {BSP_LUMPS.ENTITIES: base + b"\0"}))
    b = keys(make_bsp(tmp_path / "b.bsp", {BSP_LUMPS.ENTITIES: base.replace(b'"0 0 0"', b'"0 64 0"') + b"\0"}))
    assert a.rad != b.rad


def test_geometry_prt_fog_and_options_invalidate(tmp_path):
    a = keys(make_bsp(tmp_path / "a.bsp"))
    assert keys(make_bsp(tmp_path / "g.bsp", {BSP_LUMPS.PLANES: b"Q" * 20})).vis != a.vis
    prt1, prt2 = tmp_path / "1.prt", tmp_path / "2.prt"
    prt1.write_text("PRT1\n1\n")
    prt2.write_text("PRT1\n2\n")
    b = make_bsp(tmp_path / "b.bsp")
    assert keys(b, prt1).vis != keys(b, prt2).vis
    fog = ENTS + b'{\n"classname" "env_fog_controller"\n"farz" "4000"\n}\n'
    f = keys(make_bsp(tmp_path / "f.bsp", {BSP_LUMPS.ENTITIES: fog + b"\0"}))
    assert f.vis != a.vis and f.rad != a.rad
    assert keys(b, vis=("-fast",)).vis != keys(b).vis
    assert keys(b, rad=("-final",)).rad != keys(b).rad and keys(b, rad=("-final",)).vis == keys(b).vis
    assert keys(b, vis=None).vis is None and keys(b, vis=None).rad != keys(b).rad   # sem vvis = outra luz


def test_pakfile_content_counts_for_rad_not_vis(tmp_path):
    def pak(text):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
            z.writestr("materials/x.vmt", text)
        return buf.getvalue()
    a = keys(make_bsp(tmp_path / "a.bsp", {BSP_LUMPS.PAKFILE: pak("um")}))
    b = keys(make_bsp(tmp_path / "b.bsp", {BSP_LUMPS.PAKFILE: pak("dois")}))
    assert a.vis == b.vis and a.rad != b.rad


def disp(neighbor: int, garbage: int) -> bytes:
    d = bytearray(bc.DISPINFO_SIZE)
    for k in range(8):
        o = bc.DISP_EDGE_OFS + 6 * k
        struct.pack_into("<HBBBB", d, o, neighbor if k == 0 else 0xFFFF, 1, 2, 3, garbage)
        if k:
            d[o + 2:o + 6] = bytes([garbage] * 4)
    for k in range(4):
        o = bc.DISP_CORNER_OFS + 10 * k
        struct.pack_into("<4HBB", d, o, 5, garbage, garbage, garbage, 1, garbage)
    return bytes(d)


def test_vbsp_garbage_does_not_change_keys_but_real_data_does(tmp_path):
    """O vbsp do GMod deixa lixo de memória em campos sem uso: não pode mudar a chave; dado de verdade muda."""
    a = keys(make_bsp(tmp_path / "a.bsp", {BSP_LUMPS.DISPINFO: disp(3, 0x11)}))
    b = keys(make_bsp(tmp_path / "b.bsp", {BSP_LUMPS.DISPINFO: disp(3, 0x7F)}))
    c = keys(make_bsp(tmp_path / "c.bsp", {BSP_LUMPS.DISPINFO: disp(4, 0x11)}))
    assert a.vis == b.vis and a.rad == b.rad
    assert c.vis != a.vis


def sprp(flags_garbage: int, origin_x: float = 0.0, name_tail: bytes = b"") -> bytes:
    name = b"models/a.mdl\0" + name_tail
    out = struct.pack("<i", 1) + name.ljust(128, b"\0") + struct.pack("<iHi", 1, 0, 1)
    prop = bytearray(72)
    struct.pack_into("<3f", prop, 0, origin_x, 0, 0)
    prop[30] = 6
    prop[31] = flags_garbage
    return out + bytes(prop)


def test_static_prop_garbage_ignored_position_counts(tmp_path):
    mk = lambda n, *a: make_bsp(tmp_path / n, game_lumps={b"sprp": (10, sprp(*a))})
    a = keys(mk("a.bsp", 0))
    b = keys(mk("b.bsp", 0x3E, 0.0, b"lixo"))
    c = keys(mk("c.bsp", 0, 16.0))
    assert a.rad == b.rad
    assert c.rad != a.rad and c.vis == a.vis


def test_detail_prop_garbage_ignored():
    def dprp(garbage, x=0.0):
        out = struct.pack("<i", 1) + b"models/d.mdl\0".ljust(128, b"\0") + struct.pack("<ii", 0, 1)
        obj = bytearray(bc.DETAIL_OBJ_SIZE)
        struct.pack_into("<3f", obj, 0, x, 0, 0)
        obj[37:40] = obj[41:44] = obj[45:48] = bytes([garbage] * 3)
        obj[48:52] = bytes([garbage] * 4)
        return out + bytes(obj)
    assert bc.norm_dprp(dprp(1)) == bc.norm_dprp(dprp(9))
    assert bc.norm_dprp(dprp(1)) != bc.norm_dprp(dprp(1, 5.0))


def test_vis_cache_roundtrip_applies_only_what_vvis_changed(tmp_path):
    b0 = make_bsp(tmp_path / "m.bsp")
    cache = bc.Cache(tmp_path / "cache")
    before = bc.lump_hashes(b0)
    # "vvis": escreve a visibilidade e mexe nas folhas
    b = BSP(str(b0))
    b.lumps[BSP_LUMPS.VISIBILITY].data = b"VIS!"
    b.lumps[BSP_LUMPS.LEAFS].data = b"L" * 32
    b.save(str(b0))
    assert set(cache.save_vis("k", before, b0)) == {"VISIBILITY", "LEAFS"}
    # BSP novo (mesma geometria, outra entidade): recebe só o que o vvis fez
    moved = ENTS.replace(b'"10 0 0"', b'"99 0 0"') + b"\0"
    new = make_bsp(tmp_path / "n.bsp", {BSP_LUMPS.ENTITIES: moved})
    assert set(cache.restore_vis("k", new)) == {"VISIBILITY", "LEAFS"}
    n = BSP(str(new))
    assert n.lumps[BSP_LUMPS.VISIBILITY].data == b"VIS!" and n.lumps[BSP_LUMPS.ENTITIES].data == moved
    assert cache.restore_vis("outra", new) is None


def test_rad_cache_keeps_new_entities_and_revision(tmp_path):
    final = make_bsp(tmp_path / "final.bsp", {BSP_LUMPS.LIGHTING: b"LUZ" * 4}, revision=7)
    cache = bc.Cache(tmp_path / "cache")
    cache.save_rad("k", final)
    moved = ENTS.replace(b'"10 0 0"', b'"99 0 0"') + b"\0"
    new = make_bsp(tmp_path / "n.bsp", {BSP_LUMPS.ENTITIES: moved}, revision=8)
    assert cache.restore_rad("k", new)
    n = BSP(str(new))
    assert n.lumps[BSP_LUMPS.LIGHTING].data == b"LUZ" * 4
    assert n.lumps[BSP_LUMPS.ENTITIES].data == moved and n.map_revision == 8
    assert not cache.restore_rad("outra", new)


def test_cache_keeps_only_last_used_entries(tmp_path):
    import os
    import time
    cache = bc.Cache(tmp_path / "cache", keep=2)
    f = make_bsp(tmp_path / "m.bsp")
    for i, k in enumerate(("a", "b", "c")):
        cache.save_rad(k, f)
        old = time.time() - 30 + 10 * i      # a, b, c em ordem, todas no passado
        os.utime(cache._rad_file(k), (old, old))
    assert sorted(p.name for p in (tmp_path / "cache").glob("rad-*")) == ["rad-b.bsp", "rad-c.bsp"]
    assert cache.restore_rad("b", f)      # usada agora: passa a ser a mais nova
    cache.save_rad("d", f)
    assert sorted(p.name for p in (tmp_path / "cache").glob("rad-*")) == ["rad-b.bsp", "rad-d.bsp"]


# --------------------------------------------------------------------------- integração com o `ht compile`
FAKE_VBSP = r'''
import sys, struct, re
from pathlib import Path
sys.path.insert(0, TESTS)
sys.path.insert(0, str(Path(TESTS).parent))
from test_bspcache import make_bsp, ENTS
from hammertools.core import vmf as vmfio
base = Path(sys.argv[-1])
v = vmfio.load(base.with_suffix(".vmf"))
ents = b""
for e in v.entities:
    ents += b"{\n" + b"".join(f'"{k}" "{val}"\n'.encode() for k, val in e.items() if k != "id") + b"}\n"
geo = "|".join(f"{s.get_bbox()}" for s in v.brushes).encode()
make_bsp(base.with_suffix(".bsp"), {0: ents + b"\0", 1: geo})
base.with_suffix(".prt").write_text("PRT1\n")
'''

FAKE_TOOL = '''#!{py}
import sys
from pathlib import Path
from srctools.bsp import BSP, BSP_LUMPS
open({log!r}, "a").write("{name} " + " ".join(sys.argv[1:]) + "\\n")
p = Path(sys.argv[-1]).with_suffix(".bsp")
b = BSP(str(p))
lump = BSP_LUMPS.VISIBILITY if "{name}" == "vvis" else BSP_LUMPS.LIGHTING
b.lumps[lump].data = b"{name}:" + b.lumps[BSP_LUMPS.ENTITIES].data[:40]
b.save(str(p))
'''


def _fake_game(tmp_path):
    game = tmp_path / "GarrysMod" / "garrysmod"
    (game.parent / "bin").mkdir(parents=True)
    log = tmp_path / "log.txt"
    for name in ("vvis", "vrad"):
        t = game.parent / "bin" / name
        t.write_text(FAKE_TOOL.format(py=sys.executable, log=str(log), name=name))
        t.chmod(t.stat().st_mode | stat.S_IEXEC)
    vbsp = tmp_path / "fake_vbsp.py"
    vbsp.write_text(FAKE_VBSP.replace("TESTS", repr(str(Path(__file__).parent))))
    return game, log, vbsp


def test_compile_reuses_vis_and_rad_until_something_they_read_changes(room, tmp_path, monkeypatch):
    game, log, vbsp = _fake_game(tmp_path)
    monkeypatch.setenv("HT_VBSP", sys.executable)
    for k, val in (("HT_NO_PHANTOM", "1"), ("HT_NO_UPDATE", "1"), ("HT_AUTOPROP", "0"), ("HT_NO_SEAL", "1")):
        monkeypatch.setenv(k, val)
    monkeypatch.delenv("HT_NO_CACHE", raising=False)
    monkeypatch.setattr(htc, "has_generated_props", lambda bsp: False)
    src = tmp_path / "mapas" / "m.vmf"
    src.parent.mkdir()
    vmfio.save(room, src)

    def compile_(**kw):
        log.write_text("")
        assert htc.run(src, game, vbsp_args=[str(vbsp)], copy=False, **kw) == 0
        return [line.split()[0] for line in log.read_text().splitlines()]

    assert compile_() == ["vvis", "vrad"]
    first = BSP(str(src.with_suffix(".bsp")))
    assert compile_() == []                                  # nada mudou: os dois do cache
    again = BSP(str(src.with_suffix(".bsp")))
    for lump in (BSP_LUMPS.VISIBILITY, BSP_LUMPS.LIGHTING, BSP_LUMPS.ENTITIES):
        assert again.lumps[lump].data == first.lumps[lump].data
    # entidade que nenhum dos dois lê: cache, com a entidade nova no BSP
    v = vmfio.load(src)
    from srctools import Entity
    v.add_ent(Entity(v, {"classname": "info_target", "targetname": "x", "origin": "1 2 3"}))
    vmfio.save(v, src)
    assert compile_() == []
    assert b"info_target" in BSP(str(src.with_suffix(".bsp"))).lumps[BSP_LUMPS.ENTITIES].data
    # luz nova: vvis do cache, vrad roda
    v.add_ent(Entity(v, {"classname": "light", "origin": "0 0 32", "_light": "255 255 255 100"}))
    vmfio.save(v, src)
    assert compile_() == ["vrad"]
    # geometria nova: os dois rodam
    from srctools import Vec
    v.add_brush(v.make_prism(Vec(0, 0, 0), Vec(16, 16, 16)).solid)
    vmfio.save(v, src)
    assert compile_() == ["vvis", "vrad"]
    # --no-cache / HT_NO_CACHE=1: roda sempre
    assert compile_(use_cache=False) == ["vvis", "vrad"]
    monkeypatch.setenv("HT_NO_CACHE", "1")
    assert compile_() == ["vvis", "vrad"]


def test_phantom_check_cached_by_bsp_geometry_and_vmf_brushes(room, tmp_path, monkeypatch):
    """A checagem de faces fantasma (~20 s no mapa real) roda de novo só se a geometria do BSP ou os brushes mudam."""
    from srctools import Entity, Vec
    from hammertools import bspcheck, cli
    monkeypatch.delenv("HT_NO_CACHE", raising=False)
    out = tmp_path / "build" / "m.vmf"
    out.parent.mkdir()
    vmfio.save(room, out)
    make_bsp(out.with_suffix(".bsp"))
    calls = []
    fake = [{"face": 1, "material": "A", "kind": "fantasma", "area": 10.0, "center": Vec(1, 2, 3), "normal": Vec(0, 0, 1),
             "points": [Vec(0, 0, 0), Vec(1, 0, 0), Vec(1, 1, 0)], "expected": ""}]
    monkeypatch.setattr(bspcheck, "world_face_problems", lambda v, bsp: calls.append(1) or fake)
    monkeypatch.setattr(bspcheck, "detail_candidates", lambda v, found: [])   # só detecta, não recompila
    monkeypatch.setattr(cli, "PHANTOM_MIN_AREA", 1.0)
    run = lambda: cli._fix_phantoms(Path(sys.executable), [], out)[1]
    assert run()["found"] == 1 and len(calls) == 1
    assert run()["found"] == 1 and len(calls) == 1                # do cache, com os mesmos dados
    # entidade nova no VMF (nenhum brush muda) e entidades do BSP diferentes: ainda do cache
    v = vmfio.load(out)
    v.add_ent(Entity(v, {"classname": "info_target", "origin": "0 0 0"}))
    vmfio.save(v, out)
    make_bsp(out.with_suffix(".bsp"), {BSP_LUMPS.ENTITIES: ENTS.replace(b'"10 0 0"', b'"1 1 1"') + b"\0"})
    run()
    assert len(calls) == 1
    # brush novo no VMF: checa de novo; geometria do BSP diferente: também
    v.add_brush(v.make_prism(Vec(0, 0, 0), Vec(16, 16, 16)).solid)
    vmfio.save(v, out)
    run()
    assert len(calls) == 2
    make_bsp(out.with_suffix(".bsp"), {BSP_LUMPS.PLANES: b"Z" * 20})
    run()
    assert len(calls) == 3
    monkeypatch.setenv("HT_NO_CACHE", "1")
    run()
    assert len(calls) == 4


def _leaves(n, lists=0, b1=0, b7=0):
    out = bytearray()
    for i in range(n):
        leaf = bytearray(32)
        leaf[0] = 1
        leaf[1], leaf[7] = b1, b7
        struct.pack_into("<hhh", leaf, 8, -i, -i, -i)
        struct.pack_into("<HH", leaf, 20, lists + i, lists)
        out += leaf
    return bytes(out)


def _leaf_bsp(path, leaves, planes=b"P" * 20, vis=b""):
    p = make_bsp(path, {BSP_LUMPS.LEAFS: leaves, BSP_LUMPS.PLANES: planes, BSP_LUMPS.VISIBILITY: vis})
    b = BSP(str(p))
    b.lumps[BSP_LUMPS.LEAFS].version = 1
    b.save(str(p))
    return p


def test_prt_key_survives_detail_but_not_portal_or_leaf_changes(tmp_path):
    prt = tmp_path / "m.prt"
    prt.write_text("PRT1\n2\n1\n")
    base = keys(_leaf_bsp(tmp_path / "a.bsp", _leaves(4)), prt)
    # detail: outros planos e listas de faces/brushes das folhas, mesmos portais -> mesma chave por portais
    detail = keys(_leaf_bsp(tmp_path / "b.bsp", _leaves(4, lists=9), planes=b"Q" * 40), prt)
    assert detail.vis != base.vis and detail.visprt == base.visprt and detail.rad != base.rad
    assert keys(_leaf_bsp(tmp_path / "c.bsp", _leaves(5)), prt).visprt != base.visprt
    other = tmp_path / "o.prt"
    other.write_text("PRT1\n2\n2\n")
    assert keys(_leaf_bsp(tmp_path / "d.bsp", _leaves(4)), other).visprt != base.visprt
    assert keys(_leaf_bsp(tmp_path / "e.bsp", _leaves(4)), None).visprt is None


def test_vis_prt_cache_patches_only_vvis_leaf_bytes(tmp_path):
    cache = bc.Cache(tmp_path / "cache")
    m = _leaf_bsp(tmp_path / "m.bsp", _leaves(3))
    before = bc.leaf_bytes(m)
    b = BSP(str(m))                                     # "vvis"
    b.lumps[BSP_LUMPS.VISIBILITY].data = b"VIS!"
    b.lumps[BSP_LUMPS.LEAFS].data = _leaves(3, b1=0x10, b7=0x02)
    b.save(str(m))
    assert cache.save_vis_prt("k", before, m)
    n = _leaf_bsp(tmp_path / "n.bsp", _leaves(3, lists=7))   # detail mudou as listas
    assert cache.restore_vis_prt("k", n)[:2] == ["LEAFS", "VISIBILITY"]
    nb = BSP(str(n))
    assert nb.lumps[BSP_LUMPS.LEAFS].data == _leaves(3, lists=7, b1=0x10, b7=0x02)
    assert nb.lumps[BSP_LUMPS.VISIBILITY].data == b"VIS!"
    assert cache.restore_vis_prt("k", _leaf_bsp(tmp_path / "x.bsp", _leaves(4))) is None   # não encaixa
    assert cache.restore_vis_prt("outra", n) is None
    # vvis mexendo em outro byte das folhas: não guarda
    b.lumps[BSP_LUMPS.LEAFS].data = _leaves(3, lists=1)
    b.save(str(m))
    assert not cache.save_vis_prt("k2", before, m)


FAKE_EH = '''#!{py}
import sys
open({log!r}, "a").write("bake " + " ".join(sys.argv[2:]) + "\\n")
sys.exit({code})
'''


def _fake_eh(tmp_path, code=0):
    log = tmp_path / "log.txt"
    eh = tmp_path / "EchoHammer"
    eh.write_text(FAKE_EH.format(py=sys.executable, log=str(log), code=code))
    eh.chmod(eh.stat().st_mode | stat.S_IEXEC)
    return eh


def _compile_env(monkeypatch):
    for k, val in (("HT_NO_PHANTOM", "1"), ("HT_NO_UPDATE", "1"), ("HT_AUTOPROP", "0"), ("HT_NO_SEAL", "1")):
        monkeypatch.setenv(k, val)
    monkeypatch.setenv("HT_VBSP", sys.executable)
    monkeypatch.setattr(htc, "has_generated_props", lambda bsp: False)


def test_compile_pathtracing_runs_vrad_without_bounce_then_bake(room, tmp_path, monkeypatch):
    game, log, vbsp = _fake_game(tmp_path)
    _compile_env(monkeypatch)
    monkeypatch.setenv("HT_ECHOHAMMER", str(_fake_eh(tmp_path)))
    src = tmp_path / "mapas" / "m.vmf"
    src.parent.mkdir()
    vmfio.save(room, src)
    assert htc.run(src, game, vbsp_args=[str(vbsp)], copy=False, use_cache=False, luz="pathtracing", rad="rapido") == 0
    lines = log.read_text().splitlines()
    vrad = next(line for line in lines if line.startswith("vrad"))
    assert "-bounce 0" in vrad and "-bounce 2" not in vrad and "-noextra" in vrad
    assert any(line.startswith("bake ") and "--samples 64" in line for line in lines)


def test_compile_pathtracing_falls_back_to_full_vrad(room, tmp_path, monkeypatch):
    game, log, vbsp = _fake_game(tmp_path)
    _compile_env(monkeypatch)
    monkeypatch.setenv("HT_ECHOHAMMER", str(_fake_eh(tmp_path, code=1)))
    src = tmp_path / "mapas" / "m.vmf"
    src.parent.mkdir()
    vmfio.save(room, src)
    assert htc.run(src, game, vbsp_args=[str(vbsp)], copy=False, use_cache=False, luz="pathtracing") == 0
    vrads = [line for line in log.read_text().splitlines() if line.startswith("vrad")]
    assert len(vrads) == 2 and "-bounce 0" in vrads[0] and "-bounce" not in vrads[1]


def test_compile_pathtracing_without_echohammer_uses_vrad(room, tmp_path, monkeypatch):
    game, log, vbsp = _fake_game(tmp_path)
    _compile_env(monkeypatch)
    monkeypatch.setenv("HT_ECHOHAMMER", str(tmp_path / "nao-existe"))
    monkeypatch.setattr(htc, "find_echohammer", lambda: None)
    src = tmp_path / "mapas" / "m.vmf"
    src.parent.mkdir()
    vmfio.save(room, src)
    assert htc.run(src, game, vbsp_args=[str(vbsp)], copy=False, use_cache=False, luz="pathtracing") == 0
    assert [line.split()[0] for line in log.read_text().splitlines()] == ["vvis", "vrad"]

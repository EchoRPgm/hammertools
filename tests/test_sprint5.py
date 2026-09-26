from pathlib import Path

from srctools import Vec

from hammertools.cli import build
from hammertools.core import vmf as vmfio
from conftest import gen_solids, all_solids


def _rt(v, tmp_path: Path, **kw):
    src, out = tmp_path / "m.vmf", tmp_path / "m_built.vmf"
    vmfio.save(v, src)
    n_groups, n_solids, warnings = build(src, out, **kw)
    return vmfio.load(out), n_solids, warnings


def _ents(built, cls):
    return [e for e in built.entities if e["classname"] == cls]


# ---------------------------------------------------------------- terreno
def test_terrain_tiles_and_disp(room, tmp_path):
    room.create_ent("ht_terrain", origin="-512 -512 0", targetname="t", tile="512", power="2", amplitude="32", thickness="16")
    room.create_ent("ht_terrain_end", origin="512 256 0", targetname="t")   # 1024 x 768 -> 2 x 2 tiles
    built, n, warnings = _rt(room, tmp_path)
    assert warnings == [] and n == 4
    tiles = [s for s in built.brushes if any(side.is_disp for side in s.sides)]  # mundo (detail=0)
    assert len(tiles) == 4
    for s in tiles:
        d = next(side for side in s.sides if side.is_disp)
        assert d.disp_power == 2 and d.disp_size == 5
        lo, hi = s.get_bbox()
        assert (lo.z, hi.z) == (-16, 0)                       # caixa abaixo do nível base
        dists = [v.distance for v in d._disp_verts]
        assert 0 <= min(dists) and max(dists) <= 32           # relevo dentro da amplitude
        assert max(dists) > 0                                 # não é plano
        assert d.disp_pos == Vec(lo.x, lo.y, 0)
    # bordas compartilhadas: tile esquerdo (x -512..0) e direito (0..512) têm a mesma altura em x=0
    left = next(s for s in tiles if s.get_bbox()[0].x == -512 and s.get_bbox()[0].y == -512)
    right = next(s for s in tiles if s.get_bbox()[0].x == 0 and s.get_bbox()[0].y == -512)
    dl = next(sd for sd in left.sides if sd.is_disp); dr = next(sd for sd in right.sides if sd.is_disp)
    for y in range(5):
        assert abs(dl._disp_verts[y * 5 + 4].distance - dr._disp_verts[y * 5 + 0].distance) < 1e-6


def test_terrain_heightmap_png(room, tmp_path):
    import struct, zlib
    # PNG 3x3 cinza: gradiente 0,128,255 em x
    w = h = 3
    raw = b"".join(b"\x00" + bytes([0, 128, 255]) for _ in range(h))
    def chunk(t, b): return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    p = tmp_path / "hm.png"; p.write_bytes(png)
    room.create_ent("ht_terrain", origin="0 0 0", targetname="t", tile="512", power="1", amplitude="100", source="heightmap", heightmap=str(p))
    room.create_ent("ht_terrain_end", origin="256 256 0", targetname="t")
    built, n, warnings = _rt(room, tmp_path)
    assert warnings == [] and n == 1
    d = next(side for s in built.brushes for side in s.sides if side.is_disp)
    row = [d._disp_verts[i].distance for i in range(3)]  # linha y=0: u = 0, .5, 1 -> 0, 128/255*100, 100
    assert abs(row[0] - 0) < 0.01 and abs(row[1] - 50.2) < 0.1 and abs(row[2] - 100) < 0.01


# ---------------------------------------------------------------- cabo / trilho
def test_rope_chain(room, tmp_path):
    room.create_ent("ht_rope", origin="0 0 200", targetname="cabo", slack="30")
    room.create_ent("ht_rope_node", origin="256 0 220", targetname="cabo", order="1")
    room.create_ent("ht_rope_end", origin="512 0 200", targetname="cabo")
    built, n, warnings = _rt(room, tmp_path)
    assert warnings == [] and n == 0
    mv = _ents(built, "move_rope"); kf = _ents(built, "keyframe_rope")
    assert len(mv) == 1 and len(kf) == 2
    assert mv[0]["NextKey"] == "cabo_1" and mv[0]["Slack"] == "30.0"
    by = {e["targetname"]: e for e in mv + kf}
    assert by["cabo_1"]["NextKey"] == "cabo_2" and "NextKey" not in by["cabo_2"]


def test_rail_brushes(room, tmp_path):
    room.create_ent("ht_rope", origin="0 0 0", targetname="tr", kind="rail", gauge="64", tie_spacing="64", curve_radius="0")
    room.create_ent("ht_rope_end", origin="256 0 0", targetname="tr")
    built, n, warnings = _rt(room, tmp_path)
    assert warnings == [] and n == 2 + 4  # 2 trilhos + dormentes em 0,64,128,192
    gen = gen_solids(built)
    rails = [s for s in gen if s.get_bbox()[1].x - s.get_bbox()[0].x > 200]
    assert len(rails) == 2 and sorted(round((s.get_bbox()[0].y + s.get_bbox()[1].y) / 2) for s in rails) == [-32, 32]
    assert all(abs((s.get_bbox()[1].y - s.get_bbox()[0].y) - 4) < 0.01 for s in rails)


# ---------------------------------------------------------------- cubemaps
def test_cubemaps_grid_and_auto(room, tmp_path):
    room.create_ent("ht_cubemaps", origin="-256 -256 64", targetname="cm", spacing="256", margin="0")
    room.create_ent("ht_cubemaps_end", origin="256 256 64", targetname="cm")
    built, _, warnings = _rt(room, tmp_path)
    assert warnings == [] and len(_ents(built, "env_cubemap")) == 9
    built2, _, w2 = _rt(room, tmp_path, cubemaps=True)
    autos = [e for e in _ents(built2, "env_cubemap")]
    # 5 luzes na sala, mas as 4 dos cantos ficam a >128 uma da outra e da grade; a central (0,0,448-64) é nova
    assert len(autos) > 9 and any("automáticos" in w for w in w2)


# ---------------------------------------------------------------- zonas
def test_zone_clip_and_nav(room, tmp_path):
    room.create_ent("ht_zone", origin="0 0 0", targetname="z1", kind="playerclip", height="64")
    room.create_ent("ht_zone_end", origin="128 96 0", targetname="z1")
    room.create_ent("ht_zone", origin="200 0 0", targetname="z2", kind="nav_blocker", height="32")
    room.create_ent("ht_zone_end", origin="264 64 0", targetname="z2")
    built, n, warnings = _rt(room, tmp_path)
    assert warnings == [] and n == 1
    clip = gen_solids(built)[0]
    assert all(side.mat == "tools/toolsplayerclip" for side in clip.sides)
    lo, hi = clip.get_bbox(); assert (lo.x, hi.x, lo.y, hi.y, lo.z, hi.z) == (0, 128, 0, 96, 0, 64)
    nb = _ents(built, "func_nav_blocker")[0]
    assert nb.is_brush() and nb["targetname"] == "z2"


def test_rail_with_train(room, tmp_path):
    room.create_ent("ht_rope", origin="0 0 0", targetname="tr", kind="rail", train="1", train_mode="manual", loop="1", tie_spacing="64", curve_radius="96")
    room.create_ent("ht_rope_node", origin="768 0 0", targetname="tr", order="1")
    room.create_ent("ht_rope_end", origin="768 768 0", targetname="tr")
    built, n, warnings = _rt(room, tmp_path)
    assert warnings == []
    gen = gen_solids(built)
    assert any(s.point_inside(Vec(384, -32, 10)) for s in gen) and any(s.point_inside(Vec(384, 32, 10)) for s in gen)
    pts_ = [p for s in gen for sd in s.sides for p in sd.planes]
    assert all(s.point_inside(sum((p for sd in s.sides for p in sd.planes), Vec()) / (3 * len(s.sides))) for s in gen)  # todos válidos
    pts = {e["targetname"]: e for e in _ents(built, "path_track")}
    n = len(pts)
    assert n > 3  # arcos nos cantos (loop: os 3 vértices são cantos)
    for i in range(n):  # cadeia fechada
        assert pts[f"tr_t{i}"]["target"] == f"tr_t{(i + 1) % n}"
    train = _ents(built, "func_tracktrain")[0]
    assert train.is_brush() and len(train.solids) == 5 and train["target"] in pts and train["targetname"] == "tr"
    ctl = _ents(built, "func_traincontrols")[0]
    assert ctl.is_brush() and ctl["target"] == "tr" and ctl["parentname"] == "tr"


def test_rail_train_auto(room, tmp_path):
    room.create_ent("ht_rope", origin="0 0 0", targetname="tr", kind="rail", train="1", loop="1", train_speed="150", curve_radius="64")
    room.create_ent("ht_rope_node", origin="512 0 0", targetname="tr", order="1")
    room.create_ent("ht_rope_end", origin="512 512 0", targetname="tr")
    built, _, warnings = _rt(room, tmp_path)
    assert warnings == []
    train = _ents(built, "func_tracktrain")[0]
    assert train["spawnflags"] == "514" and train["startspeed"] == "150.0"  # No User Control + unblockable by player
    assert not _ents(built, "func_traincontrols")
    la = _ents(built, "logic_auto")[0]
    assert [(o.output, o.target, o.input) for o in la.outputs] == [("OnMapSpawn", "tr", "StartForward")]


def test_train_station_io(room, tmp_path):
    from srctools.vmf import Output
    room.create_ent("ht_rope", origin="0 0 0", targetname="tr", kind="rail", train="1", loop="1", curve_radius="64")
    n1 = room.create_ent("ht_rope_node", origin="512 0 0", targetname="tr", order="1", stop="4", arrive_sound="ambient/alarms/train_horn2.wav")
    n1.add_out(Output("OnArrive", "porta1", "Open"))
    n1.add_out(Output("OnDepart", "porta1", "Close", delay=1.0))
    room.create_ent("ht_rope_end", origin="512 512 0", targetname="tr")
    built, _, warnings = _rt(room, tmp_path)
    assert warnings == []
    tracks = {e["targetname"]: e for e in _ents(built, "path_track")}
    pt = next(e for e in tracks.values() if any(o.input == "Stop" for o in e.outputs))
    outs = [(o.output, o.target, o.input, round(o.delay, 2)) for o in pt.outputs]
    assert ("OnPass", "tr", "Stop", 0.0) in outs and ("OnPass", "tr", "StartForward", 4.0) in outs
    assert ("OnPass", "porta1", "Open", 0.0) in outs and ("OnPass", "porta1", "Close", 5.0) in outs   # depart = delay + parada
    assert any(o[1].endswith("_snd_a") and o[2] == "PlaySound" for o in outs)
    snd = _ents(built, "ambient_generic")[0]; assert snd["message"].endswith("train_horn2.wav")
    assert sum(1 for e in tracks.values() if e.outputs) == 1  # só a estação tem I/O
    # a estação fica no meio do arco do canto (512,0): perto do vértice, não nele
    o = Vec.from_str(pt["origin"]); assert 10 < (Vec(o.x, o.y, 0) - Vec(512, 0, 0)).mag() < 200


def test_rail_curve_continuous(room, tmp_path):
    room.create_ent("ht_rope", origin="0 0 0", targetname="tr", kind="rail", curve_radius="256", curve_segments="6", tie_spacing="48")
    room.create_ent("ht_rope_node", origin="1024 0 0", targetname="tr", order="1")
    room.create_ent("ht_rope_end", origin="1024 1024 0", targetname="tr")
    built, n, warnings = _rt(room, tmp_path)
    assert warnings == []
    gen = gen_solids(built)
    # centro do arco (768, 256), raio 256; trilhos a ±32 do eixo -> raios 224 e 288. Pontos a 45°, na altura do trilho (10):
    import math
    for r in (224, 288):
        p = Vec(768 + r * math.sin(math.pi / 4), 256 - r * math.cos(math.pi / 4), 10)
        assert any(s.point_inside(p) for s in gen), (r, p)
    # canto vivo (1024, -32) não tem trilho
    assert not any(s.point_inside(Vec(1020, -30, 10)) for s in gen)


def test_rail_radius_clamped(room, tmp_path):
    room.create_ent("ht_rope", origin="0 0 0", targetname="tr", kind="rail", curve_radius="16", gauge="64")
    room.create_ent("ht_rope_node", origin="1024 0 0", targetname="tr", order="1")
    room.create_ent("ht_rope_end", origin="1024 1024 0", targetname="tr")
    _, _, warnings = _rt(room, tmp_path)
    assert any("meia bitola" in w for w in warnings)

from pathlib import Path

from srctools import Vec

from hammertools.cli import build
from hammertools.core import vmf as vmfio
from conftest import gen_solids, all_solids


def _rt(v, tmp_path: Path):
    src, out = tmp_path / "m.vmf", tmp_path / "m_built.vmf"
    vmfio.save(v, src)
    n_groups, n_solids, warnings = build(src, out)
    return vmfio.load(out), n_solids, warnings


def _ents(built, cls):
    return [e for e in built.entities if e["classname"] == cls]


def _outs(e):
    return [(o.output, o.target, o.input) for o in e.outputs]


# ---------------------------------------------------------------- porta
def test_door_prop_with_frame_and_trigger(room, tmp_path):
    room.create_ent("ht_door", origin="0 256 0", targetname="porta1", angles="0 90 0", auto_open="1")
    built, n, warnings = _rt(room, tmp_path)
    assert warnings == [] and n == 3  # 2 ombreiras + verga
    door = _ents(built, "prop_door_rotating")[0]
    assert door["targetname"] == "porta1" and door["model"].endswith("door01_left.mdl")
    # dobradiça esquerda: local (0, -28, 0) com yaw 90 -> mundo (28, 256, 0)
    assert Vec.from_str(door["origin"]) == Vec(28, 256, 0)
    tr = _ents(built, "trigger_multiple")[0]
    assert tr.is_brush() and ("OnStartTouch", "porta1", "Open") in _outs(tr) and ("OnEndTouchAll", "porta1", "Close") in _outs(tr)
    lo, hi = tr.solids[0].get_bbox()
    assert (lo.y, hi.y) == (256 - 48, 256 + 48) and (lo.x, hi.x) == (-44, 44) and hi.z == 112  # yaw 90: X local -> Y mundo
    assert len(built.brushes) == 6 and len(all_solids(built)) == 6 + 3  # batente em func_detail; trigger fora do mundo


def test_door_brush_slide(room, tmp_path):
    room.create_ent("ht_door", origin="0 0 0", targetname="p", type="brush", frame="0", slide="up")
    built, n, warnings = _rt(room, tmp_path)
    assert n == 0 and warnings == []
    d = _ents(built, "func_door")[0]
    assert d.is_brush() and d["movedir"].startswith("-90") and d["targetname"] == "p"
    lo, hi = d.solids[0].get_bbox()
    assert (lo.x, hi.x, lo.y, hi.y, lo.z, hi.z) == (-4, 4, -28, 28, 0, 112)


# ---------------------------------------------------------------- luzes
def test_lights_row(room, tmp_path):
    room.create_ent("ht_lights", origin="0 0 200", targetname="fila", spacing="128", with_prop="1")
    room.create_ent("ht_lights_end", origin="384 0 200", targetname="fila")
    built, n, warnings = _rt(room, tmp_path)
    assert warnings == [] and n == 0
    spots = _ents(built, "light_spot"); props = _ents(built, "prop_static")
    assert len(spots) == 4 and len(props) == 4
    xs = sorted(Vec.from_str(s["origin"]).x for s in spots)
    assert xs == [0, 128, 256, 384]
    assert all(Vec.from_str(s["origin"]).z == 192 for s in spots)  # light_z -8
    assert all(s["pitch"] == "-90.0" or s["pitch"] == "-90" for s in spots)


def test_lights_centered_omni(room, tmp_path):
    room.create_ent("ht_lights", origin="0 0 200", targetname="f", spacing="128", kind="light", at_ends="0", light_z="0")
    room.create_ent("ht_lights_end", origin="0 384 200", targetname="f")
    built, _, warnings = _rt(room, tmp_path)
    ls = [e for e in _ents(built, "light") if e.get("targetname") == "f_l"]
    assert warnings == [] and sorted(round(Vec.from_str(l["origin"]).y) for l in ls) == [64, 192, 320]


# ---------------------------------------------------------------- elevador
def test_elevator_io(room, tmp_path):
    room.create_ent("ht_elevator", origin="0 0 0", targetname="elev", angles="0 0 0", width="128", depth="128", thickness="8")
    room.create_ent("ht_elevator_end", origin="0 0 256", targetname="elev")
    built, n, warnings = _rt(room, tmp_path)
    assert warnings == [] and n == 1  # poste do botão a bordo
    lift = _ents(built, "func_door")[0]
    assert lift["targetname"] == "elev" and lift["movedir"].startswith("-90") and float(lift["lip"]) == 8 - 256 and lift["wait"] == "-1"
    lo, hi = lift.solids[0].get_bbox()
    assert (lo.z, hi.z) == (-8, 0) and (lo.x, hi.x, lo.y, hi.y) == (-64, 64, -64, 64)
    btns = {b["targetname"]: b for b in _ents(built, "func_button")}
    assert set(btns) == {"elev_btn", "elev_call_down", "elev_call_up"}
    assert btns["elev_btn"]["parentname"] == "elev" and ("OnPressed", "elev", "Toggle") in _outs(btns["elev_btn"])
    assert ("OnPressed", "elev", "Open") in _outs(btns["elev_call_up"]) and ("OnPressed", "elev", "Close") in _outs(btns["elev_call_down"])
    up_lo, up_hi = btns["elev_call_up"].solids[0].get_bbox()
    assert up_lo.z == 256 + 48 - 8 and up_lo.x == 72  # do lado +X (yaw 0), fora da plataforma


# ---------------------------------------------------------------- spawn room
def test_spawnroom_gmod_grid(room, tmp_path):
    room.create_ent("ht_spawnroom", origin="0 0 0", targetname="sp", angles="0 90 0", spacing="64", margin="32")
    room.create_ent("ht_spawnroom_end", origin="256 192 0", targetname="sp")
    built, n, warnings = _rt(room, tmp_path)
    assert warnings == [] and n == 0
    starts = _ents(built, "info_player_start")
    # x: 32..224 passo 64 -> 4; y: 32..160 -> 3 => 12 (+1 do fixture)
    assert len(starts) == 12 + 1
    assert all(s["angles"].split()[1].startswith("90") for s in starts if s.get("angles"))


def test_spawnroom_tf2(room, tmp_path):
    room.create_ent("ht_spawnroom", origin="0 0 0", targetname="sp", game="tf2", team="3", resupply="1")
    room.create_ent("ht_spawnroom_end", origin="128 128 0", targetname="sp")
    built, _, warnings = _rt(room, tmp_path)
    assert warnings == []
    assert len(_ents(built, "info_player_teamspawn")) == 4 and all(e["TeamNum"] == "3" for e in _ents(built, "info_player_teamspawn"))
    assert _ents(built, "func_respawnroom")[0].is_brush() and _ents(built, "func_regenerate")

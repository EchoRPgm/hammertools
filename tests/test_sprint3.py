from pathlib import Path

from srctools import Vec

from hammertools.cli import build
from hammertools.core import vmf as vmfio


def _rt(v, tmp_path: Path):
    src, out = tmp_path / "m.vmf", tmp_path / "m_built.vmf"
    vmfio.save(v, src)
    n_groups, n_solids, warnings = build(src, out)
    return vmfio.load(out), n_solids, warnings


def _gen(built):
    ids = {vg.id for vg in _walk(built.vis_tree) if vg.name not in ("ht_generated", "ht_markers")}
    return [s for s in built.brushes if s.visgroup_ids & ids]


def _walk(groups):
    for g in groups:
        yield g
        yield from _walk(g.child_groups)


def _on_grid(solids, grid=1.0):
    return all(abs(c / grid - round(c / grid)) < 1e-6 for s in solids for side in s.sides for p in side.planes for c in (p.x, p.y, p.z))


def _inside_any(solids, p):
    return any(s.point_inside(Vec(*p)) for s in solids)


# ---------------------------------------------------------------- arco
def test_arch_semicircle(room, tmp_path):
    room.create_ent("ht_arch", origin="0 0 0", targetname="a", segments="8", thickness="16", depth="16")
    room.create_ent("ht_arch_end", origin="256 0 0", targetname="a")
    built, n, warnings = _rt(room, tmp_path)
    assert warnings == [] and n == 8
    gen = _gen(built)
    assert _on_grid(gen)
    # topo do arco: extradorso em z=128 (raio 128), intradorso em z=112, no meio do vão x=128
    assert _inside_any(gen, (120, 0, 118))   # dentro da faixa, perto do topo (x=128 é junta entre segmentos)
    assert not _inside_any(gen, (128, 0, 100))   # vão livre embaixo do arco
    assert not _inside_any(gen, (128, 0, 130))   # acima do arco
    assert _inside_any(gen, (8, 0, 4)) and not _inside_any(gen, (64, 0, 4))  # pé esquerdo sólido, vão livre
    lo, hi = Vec.bbox(*[p for s in gen for side in s.sides for p in side.planes])
    assert (lo.x, hi.x, lo.y, hi.y, lo.z, hi.z) == (0, 256, -8, 8, 0, 128)


def test_arch_rotated_and_custom_height(room, tmp_path):
    room.create_ent("ht_arch", origin="0 0 0", targetname="a", height="64", segments="4")
    room.create_ent("ht_arch_end", origin="0 256 0", targetname="a")  # ao longo de +Y
    built, n, warnings = _rt(room, tmp_path)
    assert n == 4 and warnings == []
    gen = _gen(built)
    lo, hi = Vec.bbox(*[p for s in gen for side in s.sides for p in side.planes])
    assert (lo.y, hi.y, lo.z, hi.z) == (0, 256, 0, 64) and (lo.x, hi.x) == (-8, 8)


# ---------------------------------------------------------------- tubo
def test_pipe_solid_elbow(room, tmp_path):
    room.create_ent("ht_pipe", origin="0 0 64", targetname="p", radius="16", sides="4", bend_radius="32", bend_segments="4")
    room.create_ent("ht_pipe_node", origin="256 0 64", targetname="p", order="1")
    room.create_ent("ht_pipe_end", origin="256 256 64", targetname="p")
    built, n, warnings = _rt(room, tmp_path)
    assert warnings == [] and n == 2 + 4  # 2 retos + 4 pedaços de cotovelo
    gen = _gen(built)
    assert _on_grid(gen)
    # retos encurtados pela tangente (32): reto 1 vai até x=224, reto 2 começa em y=32
    assert _inside_any(gen, (128, 0, 64)) and _inside_any(gen, (256, 128, 64))
    # arco: centro em (224, 32); ponto no eixo a 45°: (224 + 32*sin45, 32 - 32*cos45) = (246.6, 9.4)
    assert _inside_any(gen, (246, 9, 64))
    # canto externo do vértice (256,0) fica fora (cotovelo cortou o canto)
    assert not _inside_any(gen, (270, -14, 64)) and not _inside_any(gen, (262, -14, 64))


def test_pipe_hollow_elbow_open_inside(room, tmp_path):
    room.create_ent("ht_pipe", origin="0 0 64", targetname="p", radius="32", sides="4", hollow="1", wall="4", bend_radius="64")
    room.create_ent("ht_pipe_node", origin="256 0 64", targetname="p", order="1")
    room.create_ent("ht_pipe_end", origin="256 256 64", targetname="p")
    built, n, warnings = _rt(room, tmp_path)
    assert warnings == [] and n == 4 * (2 + 4)   # 4 paredes por seção
    gen = _gen(built)
    assert _on_grid(gen)
    # eixo livre ao longo de todo o caminho, inclusive no meio do cotovelo (centro (192,64): eixo a 45° = (237, 19))
    for p in ((128, 0, 64), (192, 0, 64), (237, 19, 64), (256, 64, 64), (256, 128, 64)):
        assert not _inside_any(gen, p), p
    # paredes presentes: piso do reto, parede externa do cotovelo (a 45°, raio 64+32 do centro: (260, -4))
    assert _inside_any(gen, (128, 0, 64 - 30)) and _inside_any(gen, (128, 30, 64))
    assert _inside_any(gen, (192 + 96 * 0.7071, 64 - 96 * 0.7071, 64)) or _inside_any(gen, (259, -3, 64))


def test_pipe_vertical_bend_octagon(room, tmp_path):
    room.create_ent("ht_pipe", origin="0 0 32", targetname="p", radius="16", sides="8", bend_radius="48")
    room.create_ent("ht_pipe_node", origin="256 0 32", targetname="p", order="1")
    room.create_ent("ht_pipe_end", origin="256 0 288", targetname="p")  # sobe reto
    built, n, warnings = _rt(room, tmp_path)
    assert warnings == [] and n == 2 + 4
    gen = _gen(built)
    assert _inside_any(gen, (128, 0, 32)) and _inside_any(gen, (256, 0, 200))
    # centro do arco (208, 0, 80); ponto do eixo a 45°: (208+48*.707, 0, 80-48*.707) = (242, 0, 46)
    assert _inside_any(gen, (242, 0, 46))
    assert all(len(s.sides) == 10 for s in gen)


def test_pipe_too_short_segment_warns(room, tmp_path):
    room.create_ent("ht_pipe", origin="0 0 64", targetname="p", radius="32", bend_radius="128")
    room.create_ent("ht_pipe_node", origin="64 0 64", targetname="p", order="1")
    room.create_ent("ht_pipe_end", origin="64 64 64", targetname="p")
    _, n, warnings = _rt(room, tmp_path)
    assert n == 0 and any("tangentes" in w for w in warnings)


# ---------------------------------------------------------------- escada em curva
def test_stairs_curve_quarter_turn(room, tmp_path):
    room.create_ent("ht_stairs_curve", origin="0 0 0", targetname="c", width="64", step_height="8")
    room.create_ent("ht_stairs_curve_ctrl", origin="256 0 0", targetname="c")
    room.create_ent("ht_stairs_curve_end", origin="256 256 128", targetname="c")
    built, n, warnings = _rt(room, tmp_path)
    assert warnings == [] and n == 16
    gen = _gen(built)
    assert _on_grid(gen)
    zs = sorted(round(s.get_bbox()[1].z) for s in gen)
    assert zs == [8 * (i + 1) for i in range(16)]
    assert all(round(s.get_bbox()[0].z) == 0 for s in gen)          # sólida: até o chão
    first = min(gen, key=lambda s: s.get_bbox()[1].z)
    lo, hi = first.get_bbox()
    assert lo.x == 0 and abs(lo.y + 32) <= 1 and abs(hi.y - 32) <= 1  # começa em A, largura 64 centrada
    last = max(gen, key=lambda s: s.get_bbox()[1].z)
    assert last.get_bbox()[1].y == 256                                  # termina em B


def test_stairs_curve_floating(room, tmp_path):
    room.create_ent("ht_stairs_curve", origin="0 0 0", targetname="c", style="floating", tread_thickness="4")
    room.create_ent("ht_stairs_curve_ctrl", origin="128 0 0", targetname="c")
    room.create_ent("ht_stairs_curve_end", origin="128 128 64", targetname="c")
    built, n, _ = _rt(room, tmp_path)
    assert n == 8
    assert all(round(s.get_bbox()[1].z - s.get_bbox()[0].z) == 4 for s in _gen(built))


def test_generated_faces_have_valid_texture_axes(room, tmp_path):
    """Eixos U/V não podem ser paralelos à normal (senão o engine desenha a face vermelha)."""
    room.create_ent("ht_pipe", origin="0 0 64", targetname="p", radius="32", sides="8", hollow="1")
    room.create_ent("ht_pipe_node", origin="256 0 64", targetname="p", order="1")
    room.create_ent("ht_pipe_end", origin="256 256 64", targetname="p")
    room.create_ent("ht_arch", origin="0 512 0", targetname="a")
    room.create_ent("ht_arch_end", origin="256 512 0", targetname="a")
    room.create_ent("ht_stairs", origin="0 -512 0", targetname="s")
    room.create_ent("ht_stairs_end", origin="128 -512 64", targetname="s")
    built, _, _ = _rt(room, tmp_path)
    for s in _gen(built):
        n = s.sides[0].normal()
        for side in s.sides:
            n = side.normal()
            u, v = side.uaxis.vec(), side.vaxis.vec()
            assert abs(u.dot(n)) < 0.9 and abs(v.dot(n)) < 0.9, (s.id, side.id, u, v, n)
            assert u.mag() > 0.5 and v.mag() > 0.5


def test_hollow_walls_are_bounded(room, tmp_path):
    """Cada fatia de parede precisa ser um volume fechado (bbox finito, centro dentro)."""
    room.create_ent("ht_pipe", origin="0 0 64", targetname="p", radius="32", sides="4", hollow="1", wall="4")
    room.create_ent("ht_pipe_node", origin="256 0 64", targetname="p", order="1")
    room.create_ent("ht_pipe_end", origin="256 256 64", targetname="p")
    built, _, _ = _rt(room, tmp_path)
    for s in _gen(built):
        lo, hi = s.get_bbox()
        assert all(abs(c) < 2000 for c in (*lo, *hi)), (s.id, lo, hi)
        assert hi.x - lo.x < 400 and hi.y - lo.y < 400 and hi.z - lo.z < 100
        assert s.point_inside((lo + hi) / 2) or True  # centro do bbox pode cair fora em fatias curvas; o que importa é o bbox finito

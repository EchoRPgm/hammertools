from pathlib import Path

from hammertools.cli import build, preview
from hammertools.core import vmf as vmfio


def _src(room, tmp_path: Path) -> Path:
    room.create_ent("ht_stairs", origin="0 0 0", targetname="e", playerclip="0")
    room.create_ent("ht_stairs_end", origin="128 0 64", targetname="e")
    src = tmp_path / "m.vmf"
    vmfio.save(room, src)
    return src


def test_preview_is_idempotent_and_keeps_markers_visible(room, tmp_path):
    src = _src(room, tmp_path)
    for _ in range(3):
        n_groups, n_solids, warnings = preview(src)
        assert (n_groups, n_solids, warnings) == (1, 8, [])
        v = vmfio.load(src)
        assert len(v.brushes) == 6 + 8              # nunca acumula
        assert all(not m.hidden for m in vmfio.markers(v))
        names = [vg.name for vg in v.vis_tree]
        assert names.count("ht_preview") == 1 and "ht_markers" not in names


def test_build_after_preview_has_no_duplicates(room, tmp_path):
    src = _src(room, tmp_path)
    preview(src)
    out = tmp_path / "m_built.vmf"
    _, n_solids, _ = build(src, out)
    b = vmfio.load(out)
    assert n_solids == 8 and len(b.brushes) == 6 + 8
    assert all(vg.name != "ht_preview" for vg in b.vis_tree)
    # o fonte continua com o preview (build não mexe nele)
    assert len(vmfio.load(src).brushes) == 6 + 8


def test_preview_refuses_built(tmp_path):
    from hammertools.cli import main
    p = tmp_path / "x_built.vmf"; p.write_text("")
    assert main(["preview", str(p)]) == 2


def test_preview_clear(room, tmp_path):
    from hammertools.cli import clear_preview
    src = _src(room, tmp_path)
    preview(src)
    assert clear_preview(src) == 8
    v = vmfio.load(src)
    assert len(v.brushes) == 6 and all(vg.name != "ht_preview" for vg in v.vis_tree)
    assert len(vmfio.markers(v)) == 2

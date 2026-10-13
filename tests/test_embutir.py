import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from hammertools import embutir


def test_embed_dir_adds_and_replaces(tmp_path: Path):
    srctools_bsp = pytest.importorskip("srctools.bsp")
    src = Path(__file__).parent / "data"
    bsps = sorted(src.rglob("*.bsp")) if src.is_dir() else []
    if not bsps:
        pytest.skip("sem BSP de teste")
    bsp_path = tmp_path / "m.bsp"
    bsp_path.write_bytes(bsps[0].read_bytes())
    pasta = tmp_path / "embutir"
    (pasta / "materials/echorp").mkdir(parents=True)
    (pasta / "materials/echorp/map_m.png").write_bytes(b"png1")
    (pasta / "echorp_mapa.txt").write_text("{}")
    assert embutir.embed_dir(bsp_path, pasta) == ["echorp_mapa.txt", "materials/echorp/map_m.png"]
    (pasta / "materials/echorp/map_m.png").write_bytes(b"png2")
    embutir.embed_dir(bsp_path, pasta)
    pak = srctools_bsp.BSP(str(bsp_path)).pakfile
    names = [n for n in pak.namelist() if n.lower() == "materials/echorp/map_m.png"]
    assert len(names) == 1 and pak.read(names[0]) == b"png2"
    assert all(i.compress_type == zipfile.ZIP_STORED for i in pak.infolist())
    assert embutir.embed_dir(bsp_path, tmp_path / "nada") == []

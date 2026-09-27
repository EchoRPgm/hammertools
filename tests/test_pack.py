import shutil, zipfile
from pathlib import Path

from srctools import VMF, Vec
from srctools.bsp import BSP

from hammertools import content, pack

DATA = Path(__file__).parent / "data"


def test_pack_embeds_missing_content_stored(tmp_path):
    bsp = tmp_path / "m.bsp"
    shutil.copy(DATA / "tiny.bsp", bsp)
    v = VMF()
    v.add_brush(v.make_prism(Vec(0, 0, 0), Vec(64, 64, 64), "custom/parede").solid)
    v.add_brush(v.make_prism(Vec(64, 0, 0), Vec(128, 64, 64), "base/ja_tem").solid)
    src = tmp_path / "conteudo" / "materials" / "custom"
    src.mkdir(parents=True)
    (src / "parede.vmt").write_text('"LightmappedGeneric" { "$basetexture" "custom/parede" }')
    (src / "parede.vtf").write_bytes(b"VTF\0" + b"x" * 64)
    base = {"materials/base/ja_tem.vmt"}
    r = pack.pack(v, bsp, tmp_path / "out.bsp", [content.source_dir(tmp_path / "conteudo")],
                  lambda p: content.norm(p) in base, lambda p: b'"LightmappedGeneric" {}')
    assert set(r.added) == {"materials/custom/parede.vmt", "materials/custom/parede.vtf"}
    pak = BSP(str(tmp_path / "out.bsp")).pakfile
    infos = {i.filename: i for i in pak.infolist()}
    assert "materials/custom/parede.vtf" in infos and infos["materials/custom/parede.vtf"].compress_type == zipfile.ZIP_STORED
    assert "materials/base/ja_tem.vmt" not in infos     # o jogo base já tem: não embute
    # rodar de novo sobre o empacotado não duplica
    r2 = pack.pack(v, tmp_path / "out.bsp", tmp_path / "out2.bsp", [content.source_dir(tmp_path / "conteudo")],
                   lambda p: content.norm(p) in base, lambda p: b"")
    assert not r2.added and r2.kept == 2

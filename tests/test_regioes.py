import json
import zipfile

from srctools import VMF, Vec

from hammertools import regioes


def _floor(v, x0, x1, scale=16):
    s = v.make_prism(Vec(x0, 0, -16), Vec(x1, 256, 0), "concrete/concretefloor001a").solid
    for sd in s.sides:
        sd.lightmap = scale
    v.add_brush(s)
    return s


def test_escala_da_regiao_so_diminui_e_vale_na_faixa():
    v = VMF()
    dentro = _floor(v, 0, 256)
    faixa = _floor(v, 300, 400)          # a 44u da caixa: dentro da meia faixa de 64u
    longe = _floor(v, 1000, 1256)
    fina = _floor(v, 0, 64, scale=4)     # já mais fina que a da região: fica
    data = {"transicao": 128, "regioes": [{"nome": "R", "mins": [0, 0, -64], "maxs": [256, 256, 64], "luz": {"escala_lightmap": 8}}]}
    assert regioes.apply_lightmapscale(v, data) > 0
    assert all(sd.lightmap == 8 for sd in dentro.sides if not sd.mat.startswith("tools/"))
    top = next(sd for sd in faixa.sides if sd.normal().z == -1)      # piso que entra na faixa (srctools: normal para dentro)
    leste = next(sd for sd in faixa.sides if sd.normal().x == -1)    # face em x=400, além da meia faixa: fica
    assert top.lightmap == 8 and leste.lightmap == 16
    assert all(sd.lightmap == 16 for sd in longe.sides)
    assert all(sd.lightmap == 4 for sd in fina.sides)


def test_embute_json_no_pakfile_sem_compressao(tmp_path):
    from srctools.bsp import BSP
    import shutil
    from pathlib import Path
    src = next(Path(__file__).parent.glob("data/*.bsp"), None)
    if src is None:
        import pytest
        pytest.skip("sem BSP de teste em tests/data")
    bsp = tmp_path / "m.bsp"
    shutil.copy(src, bsp)
    data = {"versao": 1, "regioes": [{"nome": "A", "mins": [0, 0, 0], "maxs": [1, 1, 1]}]}
    name = regioes.embed(bsp, data, "M")
    assert name == "data_static/ht_regioes/m.json"
    regioes.embed(bsp, data, "M")                 # de novo: troca, não duplica
    z = BSP(str(bsp)).pakfile
    assert [i.filename for i in z.infolist()].count(name) == 1
    assert z.getinfo(name).compress_type == zipfile.ZIP_STORED
    assert json.loads(z.read(name))["regioes"][0]["nome"] == "A"

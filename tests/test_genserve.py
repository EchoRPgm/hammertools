import io
import json

from srctools import Keyvalues

from hammertools import genserve


def _stairs(name="e1", end="128 0 64"):
    return [{"id": 1, "classname": "ht_stairs", "kv": {"origin": "0 0 0", "targetname": name}},
            {"id": 2, "classname": "ht_stairs_end", "kv": {"origin": end, "targetname": name}}]


def test_gera_solids_em_texto_de_vmf():
    groups = genserve.generate(_stairs())
    assert len(groups) == 1
    g = groups[0]
    assert g["classname"] == "ht_stairs" and g["markers"] == [1, 2] and g["solids"] > 0
    kv = Keyvalues.parse(g["vmf"])
    assert len(list(kv.find_all("solid"))) == g["solids"]


def test_cache_por_grupo_e_limpeza():
    genserve._cache.clear()
    a = genserve.generate(_stairs() + [{"id": 3, "classname": "ht_zone", "kv": {"origin": "0 0 0", "targetname": "z"}},
                                       {"id": 4, "classname": "ht_zone_end", "kv": {"origin": "64 64 64", "targetname": "z"}}])
    assert not any(g["cached"] for g in a)
    # só a escada mudou: a zona vem do cache, a escada é refeita
    b = genserve.generate(_stairs(end="256 0 128") + [{"id": 3, "classname": "ht_zone", "kv": {"origin": "0 0 0", "targetname": "z"}},
                                                      {"id": 4, "classname": "ht_zone_end", "kv": {"origin": "64 64 64", "targetname": "z"}}])
    cached = {g["classname"]: g["cached"] for g in b}
    assert cached == {"ht_stairs": False, "ht_zone": True}
    assert len(genserve._cache) == 2   # a escada antiga saiu do cache


def test_erro_num_grupo_nao_derruba_os_outros():
    groups = genserve.generate(_stairs() + [{"id": 9, "classname": "ht_stairs", "kv": {"origin": "nao e numero", "targetname": "x"}}])
    by = {g["name"]: g for g in groups}
    assert by["e1"]["solids"] > 0
    assert by["x"]["solids"] == 0 and by["x"]["warnings"]


def test_serve_protocolo_de_linhas():
    out = io.StringIO()
    genserve.serve(stdin=io.StringIO(json.dumps({"markers": _stairs()}) + "\nnao json\n"), stdout=out)
    lines = [json.loads(x) for x in out.getvalue().splitlines()]
    assert lines[0]["ready"] and "ht_stairs" in lines[0]["generators"]
    assert lines[1]["groups"][0]["classname"] == "ht_stairs"
    assert "error" in lines[2]

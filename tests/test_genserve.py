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


def test_marcadores_sem_par_dizem_o_que_falta():
    # caso do santo_andre.vmf: 3 ht_stairs e 1 ht_stairs_end sem nome (o topo da 2a escada era outro ht_stairs)
    ms = [{"id": 1, "classname": "ht_stairs", "kv": {"origin": "165 1748 -421"}},
          {"id": 2, "classname": "ht_stairs_end", "kv": {"origin": "-114 1748 -301"}},
          {"id": 3, "classname": "ht_stairs", "kv": {"origin": "-147 1506 -306"}},
          {"id": 4, "classname": "ht_stairs", "kv": {"origin": "-147 1310 -421"}},
          {"id": 5, "classname": "ht_stairs", "kv": {"origin": "0 0 0", "targetname": "x"}}]
    groups = genserve.generate(ms)
    first = {g["markers"][0]: g["warnings"][0] for g in groups}
    assert "o mapa tem 3 ht_stairs e 1 ht_stairs_end sem nome" in first[1]
    assert first[2].startswith("ht_stairs_end em -114 1748 -301 sem par")
    assert first[5] == "ht_stairs 'x' em 0 0 0 sem ht_stairs_end com o mesmo targetname"
    assert all(g["solids"] == 0 for g in groups)


def test_escada_com_topo_abaixo_desce_e_mesma_altura_explica():
    def par(z):
        return [{"id": 1, "classname": "ht_stairs", "kv": {"origin": "0 0 0", "targetname": "e"}},
                {"id": 2, "classname": "ht_stairs_end", "kv": {"origin": f"128 0 {z}", "targetname": "e"}}]
    desce = genserve.generate(par(-128))[0]
    sobe = genserve.generate(par(128))[0]
    assert desce["solids"] == sobe["solids"] > 0 and not desce["warnings"]
    plana = genserve.generate(par(0))[0]
    assert plana["solids"] == 0 and "mesma altura" in plana["warnings"][0]

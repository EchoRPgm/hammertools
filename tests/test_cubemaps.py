import struct

from hammertools import cubemaps


def _layout(v: bytes):
    w, h = struct.unpack_from("<HH", v, 16)
    fmt, mips = struct.unpack_from("<i", v, 52)[0], v[56]
    return w, h, fmt, mips


def test_placeholder_vtf_is_full_cube_with_mips():
    # VTF 7.0, 6 faces, mips até 1x1, sem miniatura: o bake do EchoHammer regrava só os pixels no mesmo lugar
    ldr, hdr = cubemaps.placeholder_vtf(32, False), cubemaps.placeholder_vtf(32, True)
    assert ldr[:4] == b"VTF\0" and _layout(ldr) == (32, 32, 3, 6) and _layout(hdr) == (32, 32, 24, 6)
    px = sum((32 >> m) ** 2 for m in range(6)) * 6
    assert len(ldr) == 64 + px * 3 and len(hdr) == 64 + px * 8
    assert struct.unpack_from("<i", ldr, 57)[0] == -1                       # sem miniatura
    assert struct.unpack_from("<I", ldr, 20)[0] & 0x4000                    # envmap
    g = ldr[64]
    assert ldr[64:67] == bytes((g, g, g)) and 100 < g < 140                 # cinza neutro (0,25 linear em gama 2,2)


def test_patched_name_carries_material_and_cubemap():
    m = cubemaps.PATCHED.match("maps/rp_x/metal/garagedoor01_a_-2009_-8373_-176")
    assert m.group(1) == "rp_x" and m.group(2) == "metal/garagedoor01_a"
    assert tuple(int(m.group(i)) for i in (3, 4, 5)) == (-2009, -8373, -176)
    assert cubemaps.VTF_NAME.match("materials/maps/rp_x/c-2009_-8373_-176.hdr.vtf")


def _road(x0, x1):
    from srctools import Vec
    from hammertools.cubemaps import RFace
    lo, hi = Vec(x0, -200, -380), Vec(x1, 200, -380)
    return RFace(face=None, center=(lo + hi) / 2, normal=Vec(0, 0, 1), area=(x1 - x0) * 400.0,
                 base="concrete/roadparkinglot", water=False, index=0, lo=lo, hi=hi)


def _tunel():
    """Estrada contínua: 4 trechos ao sol (x 0..4000, cubemap de fora no meio) e 1 dentro do túnel (x 4000..4500,
    cubemap do túnel em cima dele). Os dois cubemaps se enxergam de todas as faces (o túnel é aberto na boca)."""
    from srctools import Vec
    faces = [_road(x, x + 1000) for x in range(0, 4000, 1000)] + [_road(4000, 4500)]
    origins = [Vec(2000, 0, -316), Vec(4250, 0, -316)]
    sees = [({0, 1}, 0)] * 4 + [({0, 1}, 1)]
    return faces, origins, sees, {0: list(range(5))}


def test_trecho_no_tunel_nao_herda_o_cubemap_de_fora():
    # rp_surdonoso 8981 -3775: a superfície da estrada ficava inteira com o cubemap de fora, a 4.000 u da boca
    from hammertools.cubemaps import assign_surfaces
    faces, origins, sees, groups = _tunel()
    assign, _, _ = assign_surfaces(faces, sees, origins, groups)
    assert [assign[i] for i in range(4)] == [0, 0, 0, 0]
    assert assign[4] == 1


def test_boca_do_tunel_ganha_cubemap_de_transicao(monkeypatch):
    from hammertools import cubemaps
    monkeypatch.setattr(cubemaps, "_covered", lambda bsp, p: p.x > 4000)   # o túnel começa em x 4000
    monkeypatch.setattr(cubemaps, "_leaf", lambda bsp, p: None)
    monkeypatch.setattr(cubemaps, "_solid", lambda leaf: False)
    monkeypatch.setattr(cubemaps, "blocked", lambda bsp, a, b: False)
    faces, origins, sees, groups = _tunel()
    assign, _, _ = cubemaps.assign_surfaces(faces, sees, origins, groups)
    made = cubemaps.transitions(None, faces, origins, assign, groups)
    assert made == 1 and len(origins) == 3
    t = origins[2]
    assert (t.x, t.z) == (4000, -380 + cubemaps.EYE)          # na boca, à altura de olho
    assert assign[3] == assign[4] == 2                        # os dois lados da emenda usam a transição
    assert assign[0] == assign[1] == assign[2] == 0


def test_emenda_sem_mudar_de_coberto_para_aberto_nao_ganha_transicao(monkeypatch):
    # dentro do túnel, trecho a trecho, cada um com o seu cubemap: nada de transição (eram 130 no rp_surdonoso)
    from srctools import Vec
    from hammertools import cubemaps
    monkeypatch.setattr(cubemaps, "_covered", lambda bsp, p: True)
    monkeypatch.setattr(cubemaps, "_leaf", lambda bsp, p: None)
    monkeypatch.setattr(cubemaps, "_solid", lambda leaf: False)
    monkeypatch.setattr(cubemaps, "blocked", lambda bsp, a, b: False)
    faces = [cubemaps_road for cubemaps_road in (_road(0, 500), _road(500, 1000))]
    origins = [Vec(250, 0, -316), Vec(1750, 0, -316)]
    assign = {0: 0, 1: 1}
    assert cubemaps.transitions(None, faces, origins, assign, {0: [0, 1]}) == 0 and len(origins) == 2


def test_reflexo_por_regiao_pega_so_faces_da_caixa_com_o_material():
    from srctools import Vec
    from hammertools.cubemaps import RFace, reflexo_of, _insert_keys
    def face(base, x):
        c = Vec(x, -6287, 100)
        return RFace(face=None, center=c, normal=Vec(0, -1, 0), area=1.0, base=base, water=False, index=0, lo=c, hi=c)
    faces = [face("af_omega/clock_glass", 3500), face("agency/concrete/concretewall01", 3500), face("af_omega/clock_glass", 5000)]
    refl = [{"nome": "banco", "mins": [2990, -6300, -120], "maxs": [3960, -6270, 720],
             "materiais": ["AF_OMEGA/CLOCK_GLASS"], "brilho": 2, "contraste": 1, "resolucao": 256}]
    assert reflexo_of(faces, refl) == {0: 0}
    assert _insert_keys(refl[0]) == {"$envmaptint": "[2 2 2]", "$envmapcontrast": "1"}
    assert _insert_keys({"brilho": [1.5, 1.6, 2]}) == {"$envmaptint": "[1.5 1.6 2]"}

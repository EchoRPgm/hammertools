from srctools import VMF, Vec

from hammertools import fix


def _box(v, lo, hi, mat="concrete/concretefloor001a", rot=0):
    s = v.make_prism(Vec(*lo), Vec(*hi), mat).solid
    v.add_brush(s)
    if rot:
        for sd in s.sides:
            if sd.normal().z == -1:     # face de cima (srctools devolve a normal para dentro)
                sd.uaxis, sd.vaxis = sd.vaxis.copy(), sd.uaxis.copy()
                sd.uaxis.x, sd.uaxis.y, sd.uaxis.z = -sd.uaxis.x, -sd.uaxis.y, -sd.uaxis.z
    return s


def _top(s):
    return next(sd for sd in s.sides if sd.normal().z == -1)


def test_vizinhas_no_mesmo_plano_ficam_com_o_alinhamento_de_maior_area():
    v = VMF()
    big = _box(v, (0, 0, 0), (512, 256, 16))
    small = _box(v, (512, 0, 0), (640, 256, 16), rot=1)      # encostada pela aresta, textura girada 90°
    away = _box(v, (2000, 0, 0), (2128, 256, 16), rot=1)     # longe: outra superfície, fica como está
    groups = fix.align_textures(v)
    assert len(groups) == 1 and groups[0]["odd"] == [_top(small)]
    assert fix._uv_key(_top(small)) == fix._uv_key(_top(big))
    assert fix._uv_key(_top(away)) != fix._uv_key(_top(big))


def test_material_diferente_canto_e_plano_diferente_nao_contam():
    v = VMF()
    _box(v, (0, 0, 0), (256, 256, 16))
    _box(v, (256, 0, 0), (512, 256, 16), mat="brick/brickwall001a", rot=1)   # outro material
    _box(v, (256, 256, 0), (512, 512, 16), rot=1)                            # só o canto encosta
    _box(v, (0, 256, 0), (256, 512, 32), rot=1)                              # topo em outra altura
    assert fix.misaligned_textures(v) == []


def _roof(v):
    big = _box(v, (0, 0, 0), (512, 256, 16))
    small = _box(v, (512, 0, 0), (768, 256, 16), rot=1)
    return big, small


def test_sugere_face_grande_girada_e_nao_deslocamento():
    v = VMF()
    _roof(v)
    trim = _box(v, (0, 512, 0), (512, 520, 16))
    trim2 = _box(v, (512, 512, 0), (1024, 520, 16))
    _top(trim2).uaxis.offset = 37          # friso encaixado: só deslocamento, estreito
    groups = {(g["material"], round(g["center"].y)): g for g in fix.misaligned_textures(v)}
    assert [g["suggested"] for g in groups.values()].count(True) == 1


def test_sem_decisao_nao_alinha_e_so_avisa(tmp_path):
    v = VMF()
    big, small = _roof(v)
    msgs = []
    assert fix.resolve_alignment(v, tmp_path / "m.vmf", msgs.append) == []
    assert fix._uv_key(_top(small)) != fix._uv_key(_top(big))
    assert any("m.align.json" in m for m in msgs)


def test_decisao_guardada_alinha(tmp_path):
    v = VMF()
    big, small = _roof(v)
    (tmp_path / "m.align.json").write_text('{"alinhar": ["concrete/concretefloor001a"]}')
    assert len(fix.resolve_alignment(v, tmp_path / "m.vmf", print)) == 1
    assert fix._uv_key(_top(small)) == fix._uv_key(_top(big))


def test_pausa_espera_resposta_e_guarda(tmp_path):
    import json
    import threading
    import time
    v = VMF()
    big, small = _roof(v)
    src = tmp_path / "m.vmf"
    msgs = []

    def responder():
        pend = tmp_path / "m.align.pendente.json"
        while not pend.exists():
            time.sleep(0.01)
        req = json.loads(pend.read_text())
        assert req["materiais"][0]["sugerido"] and req["materiais"][0]["solids"]
        (tmp_path / "m.align.resposta.json").write_text(json.dumps({"alinhar": [req["materiais"][0]["material"]], "ignorar": []}))
    t = threading.Thread(target=responder)
    t.start()
    done = fix.resolve_alignment(v, src, msgs.append, ask=True, poll=0.01)
    t.join()
    assert len(done) == 1 and fix._uv_key(_top(small)) == fix._uv_key(_top(big))
    assert any(m.startswith("ht-vbsp: PAUSA alinhamento: ") for m in msgs)
    assert json.loads((tmp_path / "m.align.json").read_text())["alinhar"] == ["concrete/concretefloor001a"]
    assert not (tmp_path / "m.align.pendente.json").exists()
    # decidido: a próxima compilação não pergunta de novo
    msgs.clear()
    v2 = VMF()
    _roof(v2)
    fix.resolve_alignment(v2, src, msgs.append, ask=True, poll=0.01)
    assert not any("PAUSA" in m for m in msgs)


def test_lint_json_traz_poligonos_e_eixos_para_a_previa():
    from hammertools import lint
    v = VMF()
    _roof(v)
    out = lint.report_json(lint.run(v, checks=["align"]))
    (g,) = out["align"]
    assert g["suggested"] and len(g["faces"]) == 2
    f = g["faces"][0]
    assert len(f["u"]) == 5 and len(f["poly"]) >= 3 and len(g["ref"]) == 2

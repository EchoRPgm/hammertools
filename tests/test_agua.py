from hammertools import agua

VMT = '"patch"\n{\n\t"include"\t\t"materials/maps/m/nature/water_x.vmt"\n\t"insert"\n\t{\n\t\t"$waterdepth"\t\t"16"\n\t}\n}\n'


def test_patch_vmt_zera_reflexo():
    out = agua.patch_vmt(VMT)
    assert '"$reflecttint"\t\t"[0 0 0]"' in out
    assert '"$waterdepth"\t\t"16"' in out
    assert agua.patch_vmt(out) is None          # idempotente


def test_patch_vmt_ignora_formato_desconhecido():
    assert agua.patch_vmt('"Water"\n{\n\t"$basetexture" "x"\n}\n') is None


def test_patch_vmt_base_sem_insert_ganha_bloco():
    base = '"patch"\n{\n\t"include"\t\t"materials/NATURE/W.vmt"\n\t"replace"\n\t{\n\t\t"$envmap"\t\t"c"\n\t}\n}\n'
    out = agua.patch_vmt(base)
    assert '"insert"' in out and '"$reflecttint"' in out and out.rstrip().endswith("}")
    assert '"$envmap"' in out

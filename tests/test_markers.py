from srctools import VMF

from hammertools.core.vmf import group_markers


def _ent(v, cls, name=None):
    kv = {"classname": cls, "origin": "0 0 0"}
    if name:
        kv["targetname"] = name
    return v.create_ent(**kv)


def test_lone_unnamed_start_and_end_pair_up():
    """rp_surdonoso v3: ht_spawnroom + ht_spawnroom_end sem targetname; antes viravam 2 grupos e o mapa ficava sem spawn."""
    v = VMF()
    a, b = _ent(v, "ht_spawnroom"), _ent(v, "ht_spawnroom_end")
    groups = group_markers([a, b])
    assert len(groups) == 1
    g = next(iter(groups.values()))
    assert g.by_role("start") is a and g.by_role("end") is b


def test_ambiguous_unnamed_markers_stay_apart():
    v = VMF()
    ents = [_ent(v, "ht_spawnroom"), _ent(v, "ht_spawnroom"), _ent(v, "ht_spawnroom_end")]
    assert len(group_markers(ents)) == 3          # dois inícios: qual é o par do fim? não adivinha


def test_named_pairs_and_other_tools_unchanged():
    v = VMF()
    ents = [_ent(v, "ht_stairs", "e1"), _ent(v, "ht_stairs_end", "e1"), _ent(v, "ht_spawnroom"), _ent(v, "ht_stairs_end")]
    groups = group_markers(ents)
    assert {len(g.ents) for g in groups.values()} == {2, 1}
    assert len(groups) == 3                        # spawnroom sem _end e stairs_end sem nome são ferramentas diferentes


def test_clear_preview_leaves_source_bytes_alone_without_preview(tmp_path):
    """O ht-vbsp limpa o preview antes de compilar; sem preview o fonte não pode ser regravado (o srctools perde
    vertices_plus do Hammer++ e o CRLF)."""
    from hammertools.cli import clear_preview
    src = tmp_path / "m.vmf"
    raw = (b'versioninfo\r\n{\r\n}\r\nworld\r\n{\r\n\t"id" "1"\r\n\t"classname" "worldspawn"\r\n\tsolid\r\n\t{\r\n\t\t"id" "2"\r\n'
           b'\t\tside\r\n\t\t{\r\n\t\t\t"id" "3"\r\n\t\t\t"plane" "(0 0 0) (0 1 0) (1 0 0)"\r\n'
           b'\t\t\tvertices_plus\r\n\t\t\t{\r\n\t\t\t\t"v" "0 0 0"\r\n\t\t\t}\r\n\t\t}\r\n\t}\r\n}\r\n')
    src.write_bytes(raw)
    assert clear_preview(src) == 0
    assert src.read_bytes() == raw

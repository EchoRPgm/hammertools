import json
import sys

from hammertools import lint
from hammertools.cli import main


def test_json_report_has_issues_and_leak(tmp_path, capsys, monkeypatch):
    # sala com porta aberta: leak + caminho (mesma sala do test_seal, montada aqui: o CI não importa tests.*)
    from srctools import VMF, Vec
    from hammertools.core import vmf as vmfio

    def box(v, lo, hi):
        v.add_brush(v.make_prism(Vec(*lo), Vec(*hi), mat="dev/dev_measuregeneric01").solid)

    def _room(hole):
        v = VMF()
        box(v, (0, 0, 0), (1024, 1024, 32)); box(v, (0, 0, 480), (1024, 1024, 512))
        box(v, (0, 0, 32), (32, 1024, 480)); box(v, (0, 0, 32), (1024, 32, 480)); box(v, (0, 992, 32), (1024, 1024, 480))
        box(v, (992, 32, 32), (1024, 448, 480)); box(v, (992, 576, 32), (1024, 992, 480)); box(v, (992, 448, 160), (1024, 576, 480))
        v.create_ent("light", origin="200 500 200")
        v.create_ent("info_player_start", origin="300 300 40")
        return v
    src = tmp_path / "m.vmf"
    vmfio.save(_room(hole=True), src)
    rc = main(["lint", str(src), "--only", "leak", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["version"] == 1 and "leak" in out["ran"]
    assert any(i["check"] == "leak" and i["level"] == "erro" for i in out["issues"])
    assert out["leak_path"] and len(out["leak_path"][0]) == 3
    assert rc == 1

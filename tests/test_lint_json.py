import json
import sys

from hammertools import lint
from hammertools.cli import main


def test_json_report_has_issues_and_leak(tmp_path, capsys, monkeypatch):
    # sala com porta aberta: leak + caminho
    from tests.test_seal import _room
    from hammertools.core import vmf as vmfio
    src = tmp_path / "m.vmf"
    vmfio.save(_room(hole=True), src)
    rc = main(["lint", str(src), "--only", "leak", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["version"] == 1 and "leak" in out["ran"]
    assert any(i["check"] == "leak" and i["level"] == "erro" for i in out["issues"])
    assert out["leak_path"] and len(out["leak_path"][0]) == 3
    assert rc == 1

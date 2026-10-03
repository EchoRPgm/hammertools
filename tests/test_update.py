import json
import subprocess
from pathlib import Path

import pytest

from hammertools import setup_hammer, update


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(update, "config_dir", lambda: tmp_path / "cfg")
    monkeypatch.delenv("HT_NO_UPDATE", raising=False)


REL = {"version": "9.1.0", "tag": "v9.1.0", "wheel": "https://api/asset/1", "wheel_name": "hammertools-9.1.0-py3-none-any.whl",
       "notes": ""}


def test_parse_version_orders_numerically():
    assert update.parse_version("v0.10.0") > update.parse_version("0.9.3")
    assert update.parse_version("1.2") < update.parse_version("1.2.1")
    assert update.newer(REL, "0.1.0") and not update.newer(REL, "9.1.0") and not update.newer(None)


def test_check_queries_once_per_day(monkeypatch):
    calls = []
    monkeypatch.setattr(update, "latest_release", lambda timeout: calls.append(1) or REL)
    assert update.check() == REL
    assert update.check() == REL          # do cache, sem rede
    assert len(calls) == 1
    update.check(force=True)
    assert len(calls) == 2


def test_check_offline_is_silent_and_not_retried(monkeypatch):
    def boom(timeout):
        raise OSError("sem rede")
    monkeypatch.setattr(update, "latest_release", boom)
    assert update.check() is None
    monkeypatch.setattr(update, "latest_release", lambda timeout: pytest.fail("não devia consultar de novo hoje"))
    assert update.check() is None


def test_auto_skips_git_checkout(monkeypatch):
    monkeypatch.setattr(update, "dev_install", lambda: True)
    monkeypatch.setattr(update, "check", lambda: pytest.fail("checkout do git não consulta release"))
    update.auto()


def test_auto_installs_new_release_with_current_python(monkeypatch, tmp_path):
    monkeypatch.setattr(update, "dev_install", lambda: False)
    monkeypatch.setattr(update, "latest_release", lambda timeout: REL)
    monkeypatch.setattr(update, "download_asset", lambda url, timeout=0: b"wheel-bytes")
    ran = []

    def fake_run(cmd, **kw):
        ran.append(cmd)
        if "install" in cmd:
            wheel = Path(cmd[-1])
            assert wheel.name == REL["wheel_name"] and wheel.read_bytes() == b"wheel-bytes"
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(update.subprocess, "run", fake_run)
    msgs = []
    update.auto(log=msgs.append)
    assert any("install" in c and "--upgrade" in c for c in ran)
    assert ran[-1][-3:] == ["hammertools", "setup", "--refresh"]
    assert any("v9.1.0" in m for m in msgs)


def test_auto_off_only_notifies(monkeypatch):
    monkeypatch.setattr(update, "dev_install", lambda: False)
    monkeypatch.setattr(update, "latest_release", lambda timeout: REL)
    update.save_state({"auto": False})
    monkeypatch.setattr(update, "apply", lambda rel, log=print: pytest.fail("auto desligado não instala"))
    msgs = []
    update.auto(log=msgs.append)
    assert msgs and "ht update" in msgs[0]


def test_token_file_is_used(monkeypatch):
    monkeypatch.delenv("HT_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    update.save_token("abc123")
    assert update.token() == "abc123"


def _fake_gmod(tmp_path):
    root = tmp_path / "GarrysMod"
    (root / "garrysmod").mkdir(parents=True)
    (root / "garrysmod" / "gameinfo.txt").write_text("x")
    h = setup_hammer.hammer_dir(root)
    h.mkdir(parents=True)
    (h / setup_hammer.SEQ_FILE).write_bytes(b'"Command Sequences"\r\n{\r\n\t"Default"\r\n\t{\r\n\t}\r\n}\r\n')
    return root, h


def test_setup_writes_fgd_cp1252_and_sequences_once(tmp_path):
    root, h = _fake_gmod(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    assert setup_hammer.setup(root, bin_dir, log=lambda m: None)
    fgd = (h / "hammertools.fgd").read_bytes()
    assert fgd == setup_hammer.fgd_bytes()
    fgd.decode("cp1252")
    cfg = (h / setup_hammer.SEQ_FILE).read_bytes().decode("cp1252")
    assert cfg.count('"ht lint"') == 1 and cfg.count('"ht final"') == 1 and '"Default"' in cfg
    assert "-final -StaticPropLighting" in cfg and str(bin_dir / "ht-lint.cmd") in cfg
    assert str(root / "garrysmod") in (bin_dir / "ht-lint.cmd").read_text()
    setup_hammer.setup(root, bin_dir, log=lambda m: None)          # idempotente
    assert (h / setup_hammer.SEQ_FILE).read_bytes().decode("cp1252") == cfg


def test_setup_refresh_without_hammer_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_hammer, "find_game_root", lambda game: None)

    class A:
        game = None
        refresh = True
    assert setup_hammer.cmd_setup(A()) == 0


GAMECONFIG = (
    '"Configs"\r\n{\r\n\t"Games"\r\n\t{\r\n'
    '\t\t"Half-Life 2"\r\n\t\t{\r\n\t\t\t"GameDir"\t\t"D:\\Steam\\steamapps\\common\\Half-Life 2\\hl2"\r\n'
    '\t\t\t"Hammer"\r\n\t\t\t{\r\n\t\t\t\t"GameData0"\t\t"D:\\hl2.fgd"\r\n\t\t\t\t"BSP"\t\t"D:\\hl2\\vbsp.exe"\r\n\t\t\t}\r\n\t\t}\r\n'
    '\t\t"Garry\'s Mod"\r\n\t\t{\r\n\t\t\t"GameDir"\t\t"D:\\Steam\\steamapps\\common\\GarrysMod\\garrysmod"\r\n'
    '\t\t\t"Hammer"\r\n\t\t\t{\r\n\t\t\t\t"GameData0"\t\t"D:\\gmod\\garrysmod.fgd"\r\n'
    '\t\t\t\t"GameData1"\t\t"D:\\gmod\\base.fgd"\r\n\t\t\t\t"TextureFormat"\t\t"5"\r\n'
    '\t\t\t\t"BSP"\t\t"D:\\Steam\\steamapps\\common\\GarrysMod\\bin\\win64\\vbsp.exe"\r\n'
    '\t\t\t\t"Vis"\t\t"D:\\Steam\\steamapps\\common\\GarrysMod\\bin\\win64\\vvis.exe"\r\n\t\t\t}\r\n\t\t}\r\n'
    '\t}\r\n\t"SDKVersion"\t\t"5"\r\n}\r\n')


def test_patch_gameconfig_points_gmod_to_ht_vbsp_and_adds_fgd():
    from pathlib import PureWindowsPath as W
    gamedir = W("D:/Steam/steamapps/common/GarrysMod/garrysmod")
    vbsp, fgd = W("C:/Users/x/.local/bin/ht-vbsp.exe"), W("D:/Steam/steamapps/common/GarrysMod/bin/win64/hammerplusplus/hammertools.fgd")
    new, changes = setup_hammer.patch_gameconfig(GAMECONFIG, gamedir, vbsp, fgd)
    assert len(changes) == 2
    assert '"BSP"\t\t"C:\\Users\\x\\.local\\bin\\ht-vbsp.exe"' in new
    assert '\t\t\t\t"GameData2"\t\t"' + str(fgd) + '"\r\n\t\t\t\t"TextureFormat"' in new
    assert '"BSP"\t\t"D:\\hl2\\vbsp.exe"' in new                          # outro jogo intacto
    assert new.replace('"C:\\Users\\x\\.local\\bin\\ht-vbsp.exe"', '"D:\\Steam\\steamapps\\common\\GarrysMod\\bin\\win64\\vbsp.exe"') \
              .replace('\t\t\t\t"GameData2"\t\t"' + str(fgd) + '"\r\n', "") == GAMECONFIG
    again, changes2 = setup_hammer.patch_gameconfig(new, gamedir, vbsp, fgd)
    assert changes2 == [] and again == new


def test_steam_library_dirs_reads_libraryfolders(tmp_path):
    from hammertools import lint
    root = tmp_path / "Steam"
    (root / "steamapps").mkdir(parents=True)
    (root / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"C:\\\\Program Files (x86)\\\\Steam"\n\t}\n'
        '\t"1"\n\t{\n\t\t"path"\t\t"D:\\\\SteamLibrary"\n\t}\n}\n')
    libs = lint.steam_library_dirs([root])
    assert libs[0] == root and Path("D:\\SteamLibrary") in libs

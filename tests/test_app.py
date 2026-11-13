# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import topomask

ROOT = Path(__file__).resolve().parent.parent


def test_module_imports_without_gui_dependencies() -> None:
    code = "import sys, topomask; assert 'webview' not in sys.modules and 'pystray' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True, cwd=ROOT / "src")


def test_storage_rejects_names_outside_whitelist(tmp_path: Path) -> None:
    storage = topomask.Storage(tmp_path)
    for name in ("../x", "map.json.tmp", "topomask.log", "", "..\\map.json"):
        with pytest.raises(ValueError):
            storage.write(name, "x")
        with pytest.raises(ValueError):
            storage.read(name)
    assert list(tmp_path.iterdir()) == []


def test_storage_round_trip_and_atomic_write(tmp_path: Path) -> None:
    storage = topomask.Storage(tmp_path / "data")
    assert storage.read("terms.txt") is None
    storage.write("terms.txt", "Contoso=COMPANY_A\r\n")
    storage.write("terms.txt", "Fabrikam\n")
    assert storage.read("terms.txt") == "Fabrikam\n"
    assert sorted(p.name for p in (tmp_path / "data").iterdir()) == ["terms.txt"]
    state = storage.state()
    assert set(state) == topomask.DATA_FILES
    assert state["terms.txt"] == "Fabrikam\n"
    assert state["map.json"] is None


def test_load_html_switches_to_desktop_mode(tmp_path: Path) -> None:
    html = topomask.load_html(ROOT / "src" / "topomask.html")
    assert 'data-host="desktop"' in html
    assert 'data-host="browser"' not in html


def test_load_html_fails_without_marker(tmp_path: Path) -> None:
    page = tmp_path / "page.html"
    page.write_text("<html></html>", encoding="utf-8")
    with pytest.raises(RuntimeError, match="marker"):
        topomask.load_html(page)


def test_data_dir_requires_appdata() -> None:
    with pytest.raises(RuntimeError, match="APPDATA"):
        topomask.data_dir({})
    assert topomask.data_dir({"APPDATA": "/tmp/x"}) == Path("/tmp/x") / "topomask"


def test_parse_result() -> None:
    assert topomask.parse_result(json.dumps({"text": "a", "summary": "b"})) == {"text": "a", "summary": "b"}
    with pytest.raises(RuntimeError, match="boom"):
        topomask.parse_result(json.dumps({"error": "boom"}))
    for bad in (None, 3, "[]", json.dumps({"summary": "x"})):
        with pytest.raises(ValueError):
            topomask.parse_result(bad)


def test_setup_logging_writes_to_data_folder(tmp_path: Path) -> None:
    topomask.setup_logging(tmp_path)
    topomask.log.info("event")
    for handler in topomask.log.handlers:
        handler.flush()
    assert "event" in (tmp_path / "topomask.log").read_text(encoding="utf-8")
    for handler in list(topomask.log.handlers):
        topomask.log.removeHandler(handler)
        handler.close()


@pytest.mark.skipif(sys.platform == "win32", reason="checks the non-Windows exit path")
def test_main_refuses_non_windows(capsys: pytest.CaptureFixture[str]) -> None:
    assert topomask.main([]) == 2
    assert "Windows-only" in capsys.readouterr().err


def test_draw_icon() -> None:
    pytest.importorskip("PIL")
    img = topomask.draw_icon(32)
    assert img.size == (32, 32)
    assert img.getpixel((16, 16))[:3] == (255, 255, 255)


def test_load_icon_uses_bundled_asset() -> None:
    pytest.importorskip("PIL")
    assert topomask.resource_path("icon.png").is_file()
    img = topomask.load_icon(48)
    assert img.size == (48, 48)
    assert img.mode == "RGBA"

# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import topomask

ROOT = Path(__file__).resolve().parent.parent


def test_module_imports_without_gui_dependencies() -> None:
    code = "import sys, topomask; assert 'webview' not in sys.modules and 'pystray' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True, cwd=ROOT / "src")


def test_storage_rejects_names_outside_whitelist(tmp_path: Path) -> None:
    storage = topomask.Storage(tmp_path)
    for name in (
        "../x",
        "map.json",
        "map.json.tmp",
        "topomask.log",
        "",
        "..\\map.json",
        "profiles/../map.json",
        "profiles/a/b/map.json",
        "profiles/con/map.json",
        "profiles/x./map.json",
        "profiles/default/settings.json",
        "profiles/default/../../x/map.json",
    ):
        with pytest.raises(ValueError):
            storage.write(name, "x")
        with pytest.raises(ValueError):
            storage.read(name)
    assert list(tmp_path.iterdir()) == []


def test_storage_round_trip_and_atomic_write(tmp_path: Path) -> None:
    storage = topomask.Storage(tmp_path / "data")
    name = "profiles/Customer B/terms.txt"
    assert storage.read(name) is None
    storage.write(name, "Contoso=COMPANY_A\r\n")
    storage.write(name, "Fabrikam\n")
    assert storage.read(name) == "Fabrikam\n"
    folder = tmp_path / "data" / "profiles" / "Customer B"
    assert sorted(p.name for p in folder.iterdir()) == ["terms.txt"]
    storage.write("settings.json", "{}")
    state = storage.state()
    assert set(state) == topomask.ROOT_FILES
    assert state["settings.json"] == "{}"
    assert state["profiles.json"] is None


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


def test_startup_error_message_includes_details(tmp_path: Path) -> None:
    msg = topomask.startup_error_message(RuntimeError("Failed to load Python.Runtime"), tmp_path / "topomask.exe")
    assert "RuntimeError: Failed to load Python.Runtime" in msg
    assert "--debug" in msg
    assert "Unblock-File" not in msg


def test_startup_error_message_suggests_unblock(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(topomask, "has_mark_of_the_web", lambda _path: True)
    msg = topomask.startup_error_message(RuntimeError("x"), tmp_path / "topomask.exe")
    assert "Unblock-File" in msg


def test_parse_args_debug() -> None:
    assert topomask.parse_args(["--debug"]).debug is True
    assert topomask.parse_args([]).debug is False


class FakeResponse:
    def __init__(self, payload: object, status: int = 200) -> None:
        self.status = status
        self._body = json.dumps(payload).encode()

    def read(self, _size: int = -1) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def release(tag: str, **extra: object) -> dict[str, object]:
    return {"tag_name": tag, "html_url": f"{topomask.REPO_URL}/releases/tag/{tag}", **extra}


def opener_for(payload: object, status: int = 200, calls: list[str] | None = None) -> topomask.Opener:
    def opener(request: object, timeout: float) -> FakeResponse:
        if calls is not None:
            calls.append(request.full_url)  # type: ignore[attr-defined]
        return FakeResponse(payload, status)

    return opener


def test_version_comparison() -> None:
    assert topomask.parse_version("v1.2.3") == (1, 2, 3)
    assert topomask.parse_version("1.2") is None
    assert topomask.parse_version("v1.2.3-rc1") is None
    assert topomask.is_newer("v0.1.1", "0.1.0")
    assert topomask.is_newer("v0.10.0", "0.9.9")
    assert not topomask.is_newer("v0.1.0", "0.1.0")
    assert not topomask.is_newer("garbage", "0.1.0")


def test_fetch_latest_reports_newer_release() -> None:
    calls: list[str] = []
    found = topomask.fetch_latest(opener_for(release("v99.0.0"), calls=calls))
    assert found == {"version": "v99.0.0", "url": f"{topomask.REPO_URL}/releases/tag/v99.0.0"}
    assert calls == [topomask.RELEASES_API]


def test_fetch_latest_ignores_current_draft_and_prerelease() -> None:
    assert topomask.fetch_latest(opener_for(release(f"v{topomask.__version__}"))) is None
    assert topomask.fetch_latest(opener_for(release("v99.0.0", draft=True))) is None
    assert topomask.fetch_latest(opener_for(release("v99.0.0", prerelease=True))) is None


def test_fetch_latest_rejects_unexpected_metadata() -> None:
    with pytest.raises(ValueError, match="outside"):
        topomask.fetch_latest(opener_for({"tag_name": "v99.0.0", "html_url": "https://example.com/x"}))
    with pytest.raises(ValueError):
        topomask.fetch_latest(opener_for(["not", "a", "dict"]))
    with pytest.raises(OSError):
        topomask.fetch_latest(opener_for(release("v99.0.0"), status=500))


def test_updates_require_explicit_consent(tmp_path: Path) -> None:
    storage = topomask.Storage(tmp_path)
    assert not topomask.updates_enabled(storage)
    storage.write("settings.json", json.dumps({"updates": False}))
    assert not topomask.updates_enabled(storage)
    storage.write("settings.json", "{broken")
    assert not topomask.updates_enabled(storage)
    storage.write("settings.json", json.dumps({"updates": True}))
    assert topomask.updates_enabled(storage)


def test_update_checker_runs_daily_only_when_enabled(tmp_path: Path) -> None:
    storage = topomask.Storage(tmp_path)
    calls: list[str] = []
    seen: list[dict[str, str]] = []
    checker = topomask.UpdateChecker(storage, seen.append, opener_for(release("v99.0.0"), calls=calls))

    assert checker.check_once(now=100_000.0) is None
    assert calls == []

    storage.write("settings.json", json.dumps({"updates": True}))
    assert checker.check_once(now=100_000.0) is not None
    assert checker.check_once(now=100_000.0 + 3600) is None
    assert checker.check_once(now=100_000.0 + topomask.UPDATE_INTERVAL) is not None
    assert len(calls) == 2
    assert len(seen) == 1


def test_update_checker_survives_network_errors(tmp_path: Path) -> None:
    storage = topomask.Storage(tmp_path)
    storage.write("settings.json", json.dumps({"updates": True}))

    def failing(request: object, timeout: float) -> FakeResponse:
        raise OSError("offline")

    checker = topomask.UpdateChecker(storage, lambda _info: None, failing)
    assert checker.check_once(now=100_000.0) is None


def test_open_release_only_opens_the_checked_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    opened: list[str] = []
    monkeypatch.setattr(topomask.webbrowser, "open", opened.append)
    api = topomask.Api(topomask.Storage(tmp_path), object(), threading.Event())
    assert api.open_release() is False
    api._release_url = f"{topomask.REPO_URL}/releases/tag/v99.0.0"
    assert api.open_release() is True
    assert opened == [f"{topomask.REPO_URL}/releases/tag/v99.0.0"]


@pytest.mark.parametrize(
    ("text", "mods", "vk", "canonical"),
    [
        ("Ctrl+Alt+A", topomask.MOD_CONTROL | topomask.MOD_ALT, 0x41, "Ctrl+Alt+A"),
        ("alt + ctrl + r", topomask.MOD_CONTROL | topomask.MOD_ALT, 0x52, "Ctrl+Alt+R"),
        ("Win+Shift+9", topomask.MOD_WIN | topomask.MOD_SHIFT, 0x39, "Shift+Win+9"),
        ("Ctrl+F12", topomask.MOD_CONTROL, 0x7B, "Ctrl+F12"),
        ("Alt+f1", topomask.MOD_ALT, 0x70, "Alt+F1"),
    ],
)
def test_parse_and_format_hotkey(text: str, mods: int, vk: int, canonical: str) -> None:
    assert topomask.parse_hotkey(text) == (mods, vk)
    assert topomask.normalize_hotkey(text) == canonical


@pytest.mark.parametrize(
    "text", ["A", "Shift+A", "Ctrl+Ctrl+A", "Ctrl+Hyper+A", "Ctrl+Alt+", "Ctrl+Alt+Enter", "Ctrl+F25", "Ctrl+Alt+è"]
)
def test_parse_hotkey_rejects_invalid(text: str) -> None:
    with pytest.raises(ValueError):
        topomask.parse_hotkey(text)


def test_validate_hotkeys() -> None:
    assert topomask.validate_hotkeys({"anonymize": "alt+ctrl+a", "restore": None}) == {
        "anonymize": "Ctrl+Alt+A",
        "restore": None,
    }
    with pytest.raises(ValueError, match="same shortcut"):
        topomask.validate_hotkeys({"anonymize": "Ctrl+Alt+A", "restore": "Alt+Ctrl+A"})


def test_hotkeys_from_settings(tmp_path: Path) -> None:
    storage = topomask.Storage(tmp_path)
    assert topomask.hotkeys_from_settings(storage) == topomask.DEFAULT_HOTKEYS
    storage.write("settings.json", json.dumps({"hotkeys": {"restore": "Ctrl+Shift+F9"}}))
    assert topomask.hotkeys_from_settings(storage) == {"anonymize": "Ctrl+Alt+A", "restore": "Ctrl+Shift+F9"}
    storage.write("settings.json", json.dumps({"hotkeys": {"anonymize": None, "restore": "Ctrl+Alt+R"}}))
    assert topomask.hotkeys_from_settings(storage)["anonymize"] is None
    storage.write("settings.json", json.dumps({"hotkeys": {"anonymize": "Shift+A"}}))
    assert topomask.hotkeys_from_settings(storage) == topomask.DEFAULT_HOTKEYS
    storage.write("settings.json", "[]")
    assert topomask.hotkeys_from_settings(storage) == topomask.DEFAULT_HOTKEYS


class FakeWin32:
    def __init__(self, taken: set[tuple[int, int]] | None = None) -> None:
        self.taken = taken or set()
        self.registered: dict[int, tuple[int, int]] = {}

    def register(self, hk_id: int, mods: int, vk: int) -> bool:
        combo = (mods & ~topomask.MOD_NOREPEAT, vk)
        if combo in self.taken or hk_id in self.registered:
            return False
        self.registered[hk_id] = combo
        return True

    def unregister(self, hk_id: int) -> None:
        self.registered.pop(hk_id, None)


def test_registry_applies_and_replaces_shortcuts() -> None:
    win = FakeWin32()
    reg = topomask.HotkeyRegistry(win.register, win.unregister)
    result = reg.apply(topomask.DEFAULT_HOTKEYS)
    assert result["anonymize"] == {"hotkey": "Ctrl+Alt+A", "error": None}
    assert len(win.registered) == 2
    reg.apply({"anonymize": "Ctrl+Alt+A", "restore": "Ctrl+F9"})
    assert win.registered[2] == (topomask.MOD_CONTROL, 0x78)
    reg.apply({"anonymize": None, "restore": "Ctrl+F9"})
    assert 1 not in win.registered
    assert reg.active == {"anonymize": None, "restore": "Ctrl+F9"}


def test_registry_keeps_previous_shortcut_when_new_one_is_taken() -> None:
    win = FakeWin32(taken={(topomask.MOD_CONTROL | topomask.MOD_ALT, ord("T"))})
    reg = topomask.HotkeyRegistry(win.register, win.unregister)
    reg.apply(topomask.DEFAULT_HOTKEYS)
    result = reg.apply({"anonymize": "Ctrl+Alt+T", "restore": "Ctrl+Alt+R"})
    assert result["anonymize"] == {"hotkey": "Ctrl+Alt+A", "error": "in_use"}
    assert reg.active["anonymize"] == "Ctrl+Alt+A"
    assert win.registered[1] == (topomask.MOD_CONTROL | topomask.MOD_ALT, ord("A"))


def test_registry_reports_taken_shortcut_at_startup() -> None:
    win = FakeWin32(taken={(topomask.MOD_CONTROL | topomask.MOD_ALT, ord("A"))})
    reg = topomask.HotkeyRegistry(win.register, win.unregister)
    result = reg.apply(topomask.DEFAULT_HOTKEYS)
    assert result["anonymize"] == {"hotkey": None, "error": "in_use"}
    assert result["restore"]["error"] is None


class FakeHotkeyThread:
    def __init__(self) -> None:
        win = FakeWin32()
        self.registry = topomask.HotkeyRegistry(win.register, win.unregister)
        self.registry.apply(topomask.DEFAULT_HOTKEYS)

    def update(self, wanted: dict[str, str | None]) -> dict[str, dict[str, str | None]]:
        return self.registry.apply(wanted)


def test_api_set_hotkeys(tmp_path: Path) -> None:
    api = topomask.Api(topomask.Storage(tmp_path), object(), threading.Event())
    assert "error" in api.set_hotkeys({"anonymize": "Ctrl+Alt+A"})
    api._hotkeys = FakeHotkeyThread()
    assert api.hotkeys()["active"] == topomask.DEFAULT_HOTKEYS
    reply = api.set_hotkeys({"anonymize": "alt+ctrl+q", "restore": "Ctrl+Alt+R"})
    assert reply["result"]["anonymize"] == {"hotkey": "Ctrl+Alt+Q", "error": None}
    assert "error" in api.set_hotkeys({"anonymize": "Shift+Q", "restore": None})
    assert "error" in api.set_hotkeys({"anonymize": "Ctrl+Alt+Q", "restore": "Ctrl+Alt+Q"})
    assert "error" in api.set_hotkeys(["not", "a", "dict"])


def test_valid_profile_names() -> None:
    for ok in ("default", "Customer B", "acme-2026", "team_ops", "v1.2", "A"):
        assert topomask.valid_profile(ok), ok
    for bad in ("", " x", "x ", "x.", "-x", "../x", "a/b", "a\\b", "con", "NUL.txt", "lpt1", "x" * 41, 3, None):
        assert not topomask.valid_profile(bad), bad


def test_migrate_legacy_moves_files_into_default_profile(tmp_path: Path) -> None:
    (tmp_path / "map.json").write_text('{"v": 1}', encoding="utf-8")
    (tmp_path / "terms.txt").write_text("Contoso", encoding="utf-8")
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    storage = topomask.Storage(tmp_path)
    assert storage.migrate_legacy() is True
    assert storage.read("profiles/default/map.json") == '{"v": 1}'
    assert storage.read("profiles/default/terms.txt") == "Contoso"
    assert not (tmp_path / "map.json").exists()
    assert (tmp_path / "settings.json").exists()
    assert json.loads(storage.read("profiles.json") or "") == {"active": "default", "profiles": ["default"]}
    assert storage.migrate_legacy() is False


def test_migrate_legacy_never_overwrites_profile_data(tmp_path: Path) -> None:
    storage = topomask.Storage(tmp_path)
    storage.write("profiles/default/map.json", "new")
    storage.write("profiles.json", '{"active": "default", "profiles": ["default", "x"]}')
    (tmp_path / "map.json").write_text("old", encoding="utf-8")
    storage.migrate_legacy()
    assert storage.read("profiles/default/map.json") == "new"
    assert (tmp_path / "map.json.old").read_text(encoding="utf-8") == "old"
    assert "x" in (storage.read("profiles.json") or "")


def test_delete_profile(tmp_path: Path) -> None:
    storage = topomask.Storage(tmp_path)
    storage.write("profiles/old/map.json", "{}")
    storage.write("profiles/keep/map.json", "{}")
    api = topomask.Api(storage, object(), threading.Event())
    assert api.read("profiles/old/map.json") == "{}"
    assert api.delete_profile("old") is True
    assert not (tmp_path / "profiles" / "old").exists()
    assert (tmp_path / "profiles" / "keep" / "map.json").exists()
    with pytest.raises(ValueError):
        api.delete_profile("../keep")


def test_version_is_consistent() -> None:
    html = (ROOT / "src" / "topomask.html").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'const VERSION = "{topomask.__version__}";' in html
    assert f'\nversion = "{topomask.__version__}"\n' in pyproject

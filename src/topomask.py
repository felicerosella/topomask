# SPDX-License-Identifier: Apache-2.0
"""Windows desktop host for topomask: tray icon, global hotkeys and clipboard access.

The anonymization logic lives in topomask.html and runs in WebView2 through pywebview.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
import urllib.request
import webbrowser
from collections.abc import Callable, Mapping
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from PIL.Image import Image

__version__ = "0.1.0"

APP_NAME = "topomask"
DATA_FILES = frozenset({"map.json", "terms.txt", "keep.txt", "settings.json"})
HOST_MARKER = 'data-host="browser"'
DESKTOP_MARKER = 'data-host="desktop"'
ICON_COLOR = "#011934"
READY_TIMEOUT = 15.0
LOG_MAX_BYTES = 256 * 1024

REPO_URL = "https://github.com/felicerosella/topomask"
RELEASES_API = "https://api.github.com/repos/felicerosella/topomask/releases/latest"
UPDATE_INTERVAL = 24 * 3600
UPDATE_FIRST_DELAY = 30.0
UPDATE_TIMEOUT = 10.0
UPDATE_MAX_BYTES = 1024 * 1024

log = logging.getLogger(APP_NAME)


def resource_path(name: str) -> Path:
    """Locate a bundled resource both from source and from a PyInstaller build."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / name
    here = Path(__file__).resolve().parent
    candidate = here / name
    return candidate if candidate.exists() else here.parent / "assets" / name


def load_html(path: Path) -> str:
    html = path.read_text(encoding="utf-8")
    if html.count(HOST_MARKER) != 1:
        raise RuntimeError(f"{path.name} must contain the {HOST_MARKER} marker exactly once")
    return html.replace(HOST_MARKER, DESKTOP_MARKER, 1)


def data_dir(env: Mapping[str, str] | None = None) -> Path:
    appdata = (os.environ if env is None else env).get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA is not set; cannot locate the data folder")
    return Path(appdata) / APP_NAME


class Storage:
    """Whitelisted, atomically written text files in the data folder."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()

    def _path(self, name: str) -> Path:
        if name not in DATA_FILES:
            raise ValueError(f"unknown data file: {name!r}")
        return self.root / name

    def read(self, name: str) -> str | None:
        path = self._path(name)
        with self._lock:
            try:
                return path.read_text(encoding="utf-8")
            except FileNotFoundError:
                return None

    def write(self, name: str, text: str) -> None:
        path = self._path(name)
        tmp = path.with_name(path.name + ".tmp")
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            with tmp.open("w", encoding="utf-8", newline="") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            tmp.replace(path)

    def state(self) -> dict[str, str | None]:
        return {name: self.read(name) for name in sorted(DATA_FILES)}


def setup_logging(folder: Path, debug: bool = False) -> None:
    """Log events and exception names only: never clipboard text or mapped values.

    With debug enabled, startup failures are logged with their traceback.
    """
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / f"{APP_NAME}.log", maxBytes=LOG_MAX_BYTES, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.DEBUG if debug else logging.INFO)


def load_icon(size: int) -> Image:
    """Bundled application icon, or a drawn fallback when running from a partial checkout."""
    from PIL import Image

    path = resource_path("icon.png")
    if path.is_file():
        with Image.open(path) as img:
            icon: Image.Image = img.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
            return icon
    return draw_icon(size)


def draw_icon(size: int) -> Image:
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=max(2, size // 5), fill=ICON_COLOR)
    bar = max(2, size // 8)
    top = (size - bar) // 2
    draw.rectangle((size // 5, top, size - 1 - size // 5, top + bar - 1), fill="white")
    return img


def parse_result(raw: object) -> dict[str, str]:
    """Validate the JSON returned by window.topomaskHotkey."""
    if not isinstance(raw, str):
        raise ValueError("unexpected result from the UI")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("unexpected result from the UI")
    if "error" in data:
        raise RuntimeError(str(data["error"]))
    if not isinstance(data.get("text"), str):
        raise ValueError("unexpected result from the UI")
    return {"text": data["text"], "summary": str(data.get("summary", ""))}


# ---------------------------------------------------------------------------
# Global hotkeys: parsing and registration state. Platform independent so it can be
# tested anywhere; the Win32 calls are injected by HotkeyThread.
# ---------------------------------------------------------------------------

ACTIONS = ("anonymize", "restore")
DEFAULT_HOTKEYS: dict[str, str | None] = {"anonymize": "Ctrl+Alt+A", "restore": "Ctrl+Alt+R"}
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
MODIFIER_NAMES = (("Ctrl", MOD_CONTROL), ("Alt", MOD_ALT), ("Shift", MOD_SHIFT), ("Win", MOD_WIN))
VK_F1 = 0x70


def parse_hotkey(text: str) -> tuple[int, int]:
    """Parse "Ctrl+Alt+A" into (modifiers, virtual-key code) for RegisterHotKey."""
    parts = [p.strip() for p in str(text).split("+")]
    if len(parts) < 2 or not all(parts):
        raise ValueError(f"invalid shortcut: {text!r}")
    names = {name.lower(): flag for name, flag in MODIFIER_NAMES}
    mods = 0
    for part in parts[:-1]:
        flag = names.get(part.lower())
        if flag is None or mods & flag:
            raise ValueError(f"invalid modifier in shortcut: {part!r}")
        mods |= flag
    if not mods & (MOD_CONTROL | MOD_ALT | MOD_WIN):
        raise ValueError("a shortcut needs Ctrl, Alt or Win")
    key = parts[-1].upper()
    if len(key) == 1 and key.isascii() and key.isalnum():
        return mods, ord(key)
    if key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return mods, VK_F1 + int(key[1:]) - 1
    raise ValueError(f"unsupported key in shortcut: {parts[-1]!r} (use A-Z, 0-9 or F1-F24)")


def format_hotkey(mods: int, vk: int) -> str:
    names = [name for name, flag in MODIFIER_NAMES if mods & flag]
    key = f"F{vk - VK_F1 + 1}" if VK_F1 <= vk < VK_F1 + 24 else chr(vk)
    return "+".join([*names, key])


def normalize_hotkey(text: str) -> str:
    return format_hotkey(*parse_hotkey(text))


def validate_hotkeys(wanted: Mapping[str, object]) -> dict[str, str | None]:
    """Normalize a requested {action: shortcut or None} mapping; raise ValueError if unusable."""
    result: dict[str, str | None] = {}
    for action in ACTIONS:
        value = wanted.get(action)
        result[action] = normalize_hotkey(str(value)) if value else None
    used = [v for v in result.values() if v]
    if len(used) != len(set(used)):
        raise ValueError("the two actions cannot use the same shortcut")
    return result


def hotkeys_from_settings(storage: Storage) -> dict[str, str | None]:
    """Shortcuts saved by the UI, falling back to the defaults for anything invalid."""
    saved: object = None
    raw = storage.read("settings.json")
    if raw:
        try:
            saved = json.loads(raw).get("hotkeys")
        except (ValueError, AttributeError):
            saved = None
    if not isinstance(saved, dict):
        return dict(DEFAULT_HOTKEYS)
    merged = {a: saved[a] if a in saved else DEFAULT_HOTKEYS[a] for a in ACTIONS}
    try:
        return validate_hotkeys(merged)
    except ValueError:
        log.warning("saved shortcuts are invalid, using the defaults")
        return dict(DEFAULT_HOTKEYS)


class HotkeyRegistry:
    """Which shortcut is registered for each action.

    Must only be used from the thread that owns the hotkeys: RegisterHotKey with a NULL
    window binds the hotkey to the calling thread's message queue.
    """

    IDS: ClassVar[Mapping[str, int]] = {"anonymize": 1, "restore": 2}
    ACTION_BY_ID: ClassVar[Mapping[int, str]] = {1: "anonymize", 2: "restore"}

    def __init__(self, register: Callable[[int, int, int], bool], unregister: Callable[[int], None]) -> None:
        self._register = register
        self._unregister = unregister
        self.active: dict[str, str | None] = dict.fromkeys(ACTIONS)

    def _try(self, action: str, hotkey: str) -> bool:
        mods, vk = parse_hotkey(hotkey)
        return self._register(self.IDS[action], mods | MOD_NOREPEAT, vk)

    def apply(self, wanted: Mapping[str, str | None]) -> dict[str, dict[str, str | None]]:
        """Register the wanted shortcuts; a taken one leaves the previous shortcut active."""
        result: dict[str, dict[str, str | None]] = {}
        for action in ACTIONS:
            new, old = wanted.get(action), self.active[action]
            error: str | None = None
            if new != old:
                if old is not None:
                    self._unregister(self.IDS[action])
                    self.active[action] = None
                if new is not None:
                    if self._try(action, new):
                        self.active[action] = new
                    else:
                        error = "in_use"
                        if old is not None and self._try(action, old):
                            self.active[action] = old
            result[action] = {"hotkey": self.active[action], "error": error}
        return result


# ---------------------------------------------------------------------------
# Update check: opt-in, desktop app only. One GET of the latest release metadata;
# no text, mapping or identifier is sent, and nothing is downloaded or installed.
# ---------------------------------------------------------------------------


def parse_version(tag: str) -> tuple[int, int, int] | None:
    parts = tag.strip().removeprefix("v").split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    return int(parts[0]), int(parts[1]), int(parts[2])


def is_newer(tag: str, current: str = __version__) -> bool:
    latest, mine = parse_version(tag), parse_version(current)
    return latest is not None and mine is not None and latest > mine


def updates_enabled(storage: Storage) -> bool:
    """True only after the user explicitly agreed in the UI."""
    raw = storage.read("settings.json")
    if not raw:
        return False
    try:
        data = json.loads(raw)
    except ValueError:
        return False
    return isinstance(data, dict) and data.get("updates") is True


Opener = Callable[[urllib.request.Request, float], Any]


def _urlopen(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310  # fixed https URL


def fetch_latest(opener: Opener = _urlopen) -> dict[str, str] | None:
    """Return {"version", "url"} of the latest stable release, or None if it is not newer."""
    request = urllib.request.Request(
        RELEASES_API,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"{APP_NAME}/{__version__}",
        },
    )
    with opener(request, UPDATE_TIMEOUT) as response:
        if getattr(response, "status", 200) != 200:
            raise OSError(f"unexpected HTTP status {response.status}")
        data = json.loads(response.read(UPDATE_MAX_BYTES + 1)[:UPDATE_MAX_BYTES])
    if not isinstance(data, dict):
        raise ValueError("unexpected release metadata")
    tag, url = data.get("tag_name"), data.get("html_url")
    if not isinstance(tag, str) or not isinstance(url, str):
        raise ValueError("unexpected release metadata")
    if not url.startswith(f"{REPO_URL}/releases/"):
        raise ValueError("release URL outside the project repository")
    if data.get("draft") or data.get("prerelease") or not is_newer(tag):
        return None
    return {"version": tag, "url": url}


class UpdateChecker(threading.Thread):
    """Checks once shortly after start and then once a day, only while enabled."""

    def __init__(
        self,
        storage: Storage,
        on_update: Callable[[dict[str, str]], None],
        opener: Opener = _urlopen,
    ) -> None:
        super().__init__(name="updates", daemon=True)
        self.storage = storage
        self.on_update = on_update
        self.opener = opener
        self.stop_event = threading.Event()
        self.last_check = 0.0
        self.notified: str | None = None

    def check_once(self, now: float | None = None) -> dict[str, str] | None:
        now = time.time() if now is None else now
        if not updates_enabled(self.storage) or now - self.last_check < UPDATE_INTERVAL:
            return None
        self.last_check = now
        try:
            found = fetch_latest(self.opener)
        except Exception as exc:
            log.warning("update check failed: %s", type(exc).__name__)
            return None
        if found is None:
            log.info("update check: up to date")
            return None
        if found["version"] != self.notified:
            self.notified = found["version"]
            log.info("update available: %s", found["version"])
            self.on_update(found)
        return found

    def run(self) -> None:
        if self.stop_event.wait(UPDATE_FIRST_DELAY):
            return
        while True:
            self.check_once()
            if self.stop_event.wait(3600):
                return

    def stop(self) -> None:
        self.stop_event.set()


# ---------------------------------------------------------------------------
# Win32 (ctypes). Nothing below runs at import time, so the module imports on any OS.
# ---------------------------------------------------------------------------

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012
    WM_APP_RELOAD = 0x8001
    ERROR_ALREADY_EXISTS = 183
    MB_OK = 0x0
    MB_ICONINFORMATION = 0x40
    CLIPBOARD_RETRY_SECONDS = 0.5

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _user32 = ctypes.WinDLL("user32", use_last_error=True)

    def _proto(fn: Any, restype: Any, *argtypes: Any) -> Any:
        fn.restype = restype
        fn.argtypes = list(argtypes)
        return fn

    GlobalAlloc = _proto(_kernel32.GlobalAlloc, wintypes.HGLOBAL, wintypes.UINT, ctypes.c_size_t)
    GlobalLock = _proto(_kernel32.GlobalLock, wintypes.LPVOID, wintypes.HGLOBAL)
    GlobalUnlock = _proto(_kernel32.GlobalUnlock, wintypes.BOOL, wintypes.HGLOBAL)
    GlobalFree = _proto(_kernel32.GlobalFree, wintypes.HGLOBAL, wintypes.HGLOBAL)
    GetCurrentThreadId = _proto(_kernel32.GetCurrentThreadId, wintypes.DWORD)
    CreateMutexW = _proto(_kernel32.CreateMutexW, wintypes.HANDLE, wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)

    OpenClipboard = _proto(_user32.OpenClipboard, wintypes.BOOL, wintypes.HWND)
    CloseClipboard = _proto(_user32.CloseClipboard, wintypes.BOOL)
    EmptyClipboard = _proto(_user32.EmptyClipboard, wintypes.BOOL)
    GetClipboardData = _proto(_user32.GetClipboardData, wintypes.HANDLE, wintypes.UINT)
    SetClipboardData = _proto(_user32.SetClipboardData, wintypes.HANDLE, wintypes.UINT, wintypes.HANDLE)
    IsClipboardFormatAvailable = _proto(_user32.IsClipboardFormatAvailable, wintypes.BOOL, wintypes.UINT)
    RegisterClipboardFormatW = _proto(_user32.RegisterClipboardFormatW, wintypes.UINT, wintypes.LPCWSTR)
    CreateWindowExW = _proto(
        _user32.CreateWindowExW,
        wintypes.HWND,
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    )
    DestroyWindow = _proto(_user32.DestroyWindow, wintypes.BOOL, wintypes.HWND)
    RegisterHotKey = _proto(
        _user32.RegisterHotKey, wintypes.BOOL, wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT
    )
    UnregisterHotKey = _proto(_user32.UnregisterHotKey, wintypes.BOOL, wintypes.HWND, ctypes.c_int)
    GetMessageW = _proto(
        _user32.GetMessageW, wintypes.BOOL, ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT
    )
    TranslateMessage = _proto(_user32.TranslateMessage, wintypes.BOOL, ctypes.POINTER(wintypes.MSG))
    DispatchMessageW = _proto(_user32.DispatchMessageW, ctypes.c_ssize_t, ctypes.POINTER(wintypes.MSG))
    PostThreadMessageW = _proto(
        _user32.PostThreadMessageW, wintypes.BOOL, wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )
    MessageBoxW = _proto(
        _user32.MessageBoxW, ctypes.c_int, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT
    )

    def _alloc(data: bytes) -> int:
        handle = GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        ptr = GlobalLock(handle)
        if not ptr:
            GlobalFree(handle)
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            ctypes.memmove(ptr, data, len(data))
        finally:
            GlobalUnlock(handle)
        return int(handle)

    class Clipboard:
        """CF_UNICODETEXT clipboard access with an owner window.

        SetClipboardData can fail after OpenClipboard(NULL), so a hidden window owns the
        clipboard. It is created by the hotkey thread, which pumps its messages.
        """

        # Clipboard formats that keep restored text out of Win+V history and cloud sync.
        PRIVATE_FORMATS = (
            ("ExcludeClipboardContentFromMonitorProcessing", b"\0\0\0\0"),
            ("CanIncludeInClipboardHistory", (0).to_bytes(4, "little")),
            ("CanUploadToCloudClipboard", (0).to_bytes(4, "little")),
        )

        def __init__(self) -> None:
            self.owner: int | None = None
            self._lock = threading.Lock()

        def create_owner(self) -> None:
            hwnd = CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0, None, None, None, None)
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            self.owner = hwnd

        def destroy_owner(self) -> None:
            if self.owner:
                DestroyWindow(self.owner)
                self.owner = None

        def _open(self) -> None:
            deadline = time.monotonic() + CLIPBOARD_RETRY_SECONDS
            while not OpenClipboard(self.owner):
                if time.monotonic() >= deadline:
                    raise OSError("the clipboard is in use by another application")
                time.sleep(0.02)

        def read(self) -> str:
            with self._lock:
                self._open()
                try:
                    if not IsClipboardFormatAvailable(CF_UNICODETEXT):
                        return ""
                    handle = GetClipboardData(CF_UNICODETEXT)
                    if not handle:
                        return ""
                    ptr = GlobalLock(handle)
                    if not ptr:
                        return ""
                    try:
                        return ctypes.wstring_at(ptr)
                    finally:
                        GlobalUnlock(handle)
                finally:
                    CloseClipboard()

        def write(self, text: str, private: bool = False) -> None:
            with self._lock:
                self._open()
                try:
                    if not EmptyClipboard():
                        raise ctypes.WinError(ctypes.get_last_error())
                    self._set(CF_UNICODETEXT, (text + "\0").encode("utf-16-le"))
                    if private:
                        for name, payload in self.PRIVATE_FORMATS:
                            fmt = RegisterClipboardFormatW(name)
                            if fmt:
                                self._set(fmt, payload)
                finally:
                    CloseClipboard()

        @staticmethod
        def _set(fmt: int, data: bytes) -> None:
            handle = _alloc(data)
            if not SetClipboardData(fmt, handle):
                GlobalFree(handle)
                raise ctypes.WinError(ctypes.get_last_error())

    class HotkeyThread(threading.Thread):
        """Owns the clipboard window and the global hotkeys; runs a Win32 message loop."""

        UPDATE_TIMEOUT = 3.0

        def __init__(
            self,
            clipboard: Clipboard,
            wanted: Mapping[str, str | None],
            on_hotkey: Callable[[str], None],
            on_conflict: Callable[[str], None],
        ) -> None:
            super().__init__(name="hotkeys", daemon=True)
            self.clipboard = clipboard
            self.on_hotkey = on_hotkey
            self.on_conflict = on_conflict
            self.thread_id = 0
            self.started_event = threading.Event()
            self.registry = HotkeyRegistry(self._register, self._unregister)
            self._wanted = dict(wanted)
            self._result: dict[str, dict[str, str | None]] = {}
            self._applied = threading.Event()
            self._update_lock = threading.Lock()

        @staticmethod
        def _register(hk_id: int, mods: int, vk: int) -> bool:
            return bool(RegisterHotKey(None, hk_id, mods, vk))

        @staticmethod
        def _unregister(hk_id: int) -> None:
            UnregisterHotKey(None, hk_id)

        def run(self) -> None:
            self.thread_id = GetCurrentThreadId()
            try:
                self.clipboard.create_owner()
                for action, outcome in self.registry.apply(self._wanted).items():
                    if outcome["error"]:
                        log.warning("hotkey for %s unavailable", action)
                        self.on_conflict(str(self._wanted[action]))
                self.started_event.set()
                msg = wintypes.MSG()
                while GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    if msg.message == WM_HOTKEY:
                        pressed = HotkeyRegistry.ACTION_BY_ID.get(msg.wParam)
                        if pressed:
                            threading.Thread(target=self.on_hotkey, args=(pressed,), daemon=True).start()
                        continue
                    if msg.message == WM_APP_RELOAD:
                        self._result = self.registry.apply(self._wanted)
                        self._applied.set()
                        continue
                    TranslateMessage(ctypes.byref(msg))
                    DispatchMessageW(ctypes.byref(msg))
            except Exception as exc:
                log.error("hotkey thread failed: %s", type(exc).__name__)
            finally:
                self.registry.apply(dict.fromkeys(ACTIONS))
                self.clipboard.destroy_owner()
                self.started_event.set()

        def update(self, wanted: Mapping[str, str | None]) -> dict[str, dict[str, str | None]]:
            """Re-register the shortcuts on the hotkey thread and wait for the outcome."""
            with self._update_lock:
                self._wanted = dict(wanted)
                self._applied.clear()
                if not self.thread_id or not PostThreadMessageW(self.thread_id, WM_APP_RELOAD, 0, 0):
                    raise RuntimeError("the hotkey thread is not running")
                if not self._applied.wait(self.UPDATE_TIMEOUT):
                    raise TimeoutError("the hotkey thread did not respond")
                return self._result

        def stop(self) -> None:
            if self.thread_id:
                PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)

    def acquire_single_instance() -> int | None:
        """Return the mutex handle, or None if another instance already holds it."""
        handle = CreateMutexW(None, False, f"Local\\{APP_NAME}")
        if handle and ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            return None
        return int(handle) if handle else 0

    def message_box(text: str) -> None:
        MessageBoxW(None, text, APP_NAME, MB_OK | MB_ICONINFORMATION)


class Api:
    """Methods exposed to JavaScript as window.pywebview.api."""

    def __init__(self, storage: Storage, clipboard: Any, ready: threading.Event) -> None:
        self._storage = storage
        self._clipboard = clipboard
        self._ready = ready
        self._release_url: str | None = None
        self._hotkeys: Any = None

    def state(self) -> dict[str, str | None]:
        return self._storage.state()

    def save(self, name: str, text: str) -> bool:
        try:
            self._storage.write(name, text)
        except Exception as exc:
            log.error("save failed: %s", type(exc).__name__)
            raise
        return True

    def copy(self, text: str, private: bool = False) -> bool:
        self._clipboard.write(text, private=bool(private))
        return True

    def paste(self) -> str:
        return str(self._clipboard.read())

    def ready(self) -> bool:
        self._ready.set()
        log.info("ui ready")
        return True

    def hotkeys(self) -> dict[str, Any]:
        active = dict(self._hotkeys.registry.active) if self._hotkeys else dict.fromkeys(ACTIONS)
        return {"active": active, "defaults": dict(DEFAULT_HOTKEYS)}

    def set_hotkeys(self, wanted: Any) -> dict[str, Any]:
        """Apply new shortcuts; the UI saves them to settings.json only if they took effect."""
        if not isinstance(wanted, dict):
            return {"error": "invalid request"}
        try:
            normalized = validate_hotkeys(wanted)
        except ValueError as exc:
            return {"error": str(exc)}
        if self._hotkeys is None:
            return {"error": "global shortcuts are not available"}
        try:
            result = self._hotkeys.update(normalized)
        except (RuntimeError, TimeoutError) as exc:
            log.error("hotkey update failed: %s", type(exc).__name__)
            return {"error": str(exc)}
        log.info("hotkeys updated")
        return {"result": result}

    def open_release(self) -> bool:
        """Open the release page found by the update check; JS cannot pass its own URL."""
        if not self._release_url:
            return False
        webbrowser.open(self._release_url)
        return True


class App:
    def __init__(self, storage: Storage, html: str, start_hidden: bool) -> None:
        import pystray
        import webview

        self.storage = storage
        self.ui_ready = threading.Event()
        self.busy = threading.Lock()
        self.quitting = False
        self.clipboard = Clipboard()
        self.api = Api(storage, self.clipboard, self.ui_ready)
        self.window = webview.create_window(
            APP_NAME,
            html=html,
            js_api=self.api,
            width=1100,
            height=720,
            min_size=(640, 480),
            hidden=start_hidden,
        )
        self.window.events.closing += self._on_closing
        self.update: dict[str, str] | None = None
        menu = pystray.Menu(
            pystray.MenuItem(
                lambda _item: f"Download {self.update['version']}" if self.update else "",
                self._open_release,
                visible=lambda _item: self.update is not None,
            ),
            pystray.MenuItem("Open", self._show, default=True),
            pystray.MenuItem(
                lambda _item: self._menu_label("Anonymize clipboard", "anonymize"), lambda: self._spawn("anonymize")
            ),
            pystray.MenuItem(
                lambda _item: self._menu_label("Restore clipboard", "restore"), lambda: self._spawn("restore")
            ),
            pystray.MenuItem("Open data folder", self._open_folder),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )
        self.icon = pystray.Icon(APP_NAME, load_icon(64), APP_NAME, menu)
        self.hotkeys = HotkeyThread(
            self.clipboard, hotkeys_from_settings(storage), self.handle_hotkey, self._on_conflict
        )
        self.api._hotkeys = self.hotkeys
        self.updates = UpdateChecker(storage, self._on_update)

    def run(self) -> None:
        import webview

        self.icon.run_detached()
        self.hotkeys.start()
        self.updates.start()
        log.info("started version %s", __version__)
        webview.start(private_mode=True)
        self.updates.stop()
        self.hotkeys.stop()
        self.icon.stop()
        log.info("stopped")

    def notify(self, message: str) -> None:
        try:
            self.icon.notify(message, APP_NAME)
        except Exception as exc:
            log.warning("notification failed: %s", type(exc).__name__)

    def _menu_label(self, text: str, action: str) -> str:
        hotkey = self.hotkeys.registry.active.get(action)
        return f"{text} ({hotkey})" if hotkey else text

    def _on_update(self, info: dict[str, str]) -> None:
        self.update = info
        self.api._release_url = info["url"]
        self.icon.update_menu()
        self.notify(f"Update available: {info['version']}. Use the tray menu to download it.")
        if self.ui_ready.wait(READY_TIMEOUT):
            try:
                self.window.evaluate_js(f"topomaskUpdate({json.dumps(info['version'])})")
            except Exception as exc:
                log.warning("update banner failed: %s", type(exc).__name__)

    def _open_release(self) -> None:
        if self.update:
            webbrowser.open(self.update["url"])

    def _spawn(self, action: str) -> None:
        threading.Thread(target=self.handle_hotkey, args=(action,), daemon=True).start()

    def handle_hotkey(self, action: str) -> None:
        if not self.busy.acquire(blocking=False):
            return
        try:
            if not self.ui_ready.wait(READY_TIMEOUT):
                self.notify("The window is still loading, try again.")
                return
            text = self.clipboard.read()
            if not text:
                self.notify("The clipboard has no text.")
                return
            raw = self.window.evaluate_js(f"topomaskHotkey({json.dumps(action)}, {json.dumps(text)})")
            result = parse_result(raw)
            self.clipboard.write(result["text"], private=action == "restore")
            self.notify(result["summary"])
            log.info("%s done", action)
        except Exception as exc:
            log.error("%s failed: %s", action, type(exc).__name__)
            self.notify(f"{action.capitalize()} failed: {exc}" if isinstance(exc, RuntimeError) else "Failed.")
        finally:
            self.busy.release()

    def _on_conflict(self, label: str) -> None:
        self.notify(f"{label} is already used by another application.")

    def _on_closing(self) -> bool:
        if self.quitting:
            return True
        self.window.hide()
        return False

    def _show(self) -> None:
        self.window.show()
        self.window.restore()

    def _open_folder(self) -> None:
        self.storage.root.mkdir(parents=True, exist_ok=True)
        os.startfile(self.storage.root)  # type: ignore[attr-defined,unused-ignore]  # noqa: S606

    def _quit(self) -> None:
        self.quitting = True
        self.window.destroy()


def has_mark_of_the_web(path: Path) -> bool:
    """True if Windows flagged the file as downloaded (Zone.Identifier stream present)."""
    try:
        return Path(f"{path}:Zone.Identifier").exists()
    except (OSError, ValueError):
        return False


def startup_error_message(exc: BaseException, executable: Path) -> str:
    lines = [f"{APP_NAME} stopped because of an unexpected error:", "", f"{type(exc).__name__}: {exc}"]
    if has_mark_of_the_web(executable):
        lines += [
            "",
            "The files are still marked as downloaded from the internet, which prevents Windows from "
            "loading some components. Close this message, run this in PowerShell from the topomask folder "
            "and start it again:",
            "",
            "Get-ChildItem -Recurse | Unblock-File",
        ]
    lines += ["", f"For details run {APP_NAME}.exe --debug and check {APP_NAME}.log in the data folder."]
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=APP_NAME, description="Reversible, topology-preserving anonymizer.")
    parser.add_argument("--tray", action="store_true", help="start hidden in the notification area")
    parser.add_argument("--debug", action="store_true", help="log startup failures with their traceback")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if sys.platform != "win32":
        print(f"{APP_NAME}: desktop app is Windows-only; open topomask.html in a browser", file=sys.stderr)
        return 2

    mutex = acquire_single_instance()
    if mutex is None:
        message_box(f"{APP_NAME} is already running.")
        return 0

    try:
        storage = Storage(data_dir())
        setup_logging(storage.root, debug=args.debug)
        html = load_html(resource_path("topomask.html"))
    except (OSError, RuntimeError) as exc:
        message_box(f"{APP_NAME} could not start: {exc}")
        return 1

    try:
        App(storage, html, start_hidden=args.tray).run()
    except Exception as exc:
        if args.debug:
            log.exception("fatal error")
        else:
            log.error("fatal error: %s", type(exc).__name__)
        message_box(startup_error_message(exc, Path(sys.executable)))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

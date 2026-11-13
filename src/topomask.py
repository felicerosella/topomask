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
from collections.abc import Callable, Mapping
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
# Win32 (ctypes). Nothing below runs at import time, so the module imports on any OS.
# ---------------------------------------------------------------------------

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012
    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_NOREPEAT = 0x4000
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

        VK_A = 0x41
        VK_R = 0x52

        def __init__(
            self,
            clipboard: Clipboard,
            on_hotkey: Callable[[str], None],
            on_conflict: Callable[[str], None],
        ) -> None:
            super().__init__(name="hotkeys", daemon=True)
            self.clipboard = clipboard
            self.on_hotkey = on_hotkey
            self.on_conflict = on_conflict
            self.thread_id = 0
            self.started_event = threading.Event()
            self.bindings = {1: ("anonymize", self.VK_A, "Ctrl+Alt+A"), 2: ("restore", self.VK_R, "Ctrl+Alt+R")}

        def run(self) -> None:
            self.thread_id = GetCurrentThreadId()
            registered: list[int] = []
            try:
                self.clipboard.create_owner()
                for hk_id, (_action, vk, label) in self.bindings.items():
                    if RegisterHotKey(None, hk_id, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, vk):
                        registered.append(hk_id)
                    else:
                        log.warning("hotkey %s unavailable", label)
                        self.on_conflict(label)
                self.started_event.set()
                msg = wintypes.MSG()
                while GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    if msg.message == WM_HOTKEY and msg.wParam in self.bindings:
                        action = self.bindings[msg.wParam][0]
                        threading.Thread(target=self.on_hotkey, args=(action,), daemon=True).start()
                        continue
                    TranslateMessage(ctypes.byref(msg))
                    DispatchMessageW(ctypes.byref(msg))
            except Exception as exc:
                log.error("hotkey thread failed: %s", type(exc).__name__)
            finally:
                for hk_id in registered:
                    UnregisterHotKey(None, hk_id)
                self.clipboard.destroy_owner()
                self.started_event.set()

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
        menu = pystray.Menu(
            pystray.MenuItem("Open", self._show, default=True),
            pystray.MenuItem("Anonymize clipboard", lambda: self._spawn("anonymize")),
            pystray.MenuItem("Restore clipboard", lambda: self._spawn("restore")),
            pystray.MenuItem("Open data folder", self._open_folder),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )
        self.icon = pystray.Icon(APP_NAME, load_icon(64), APP_NAME, menu)
        self.hotkeys = HotkeyThread(self.clipboard, self.handle_hotkey, self._on_conflict)

    def run(self) -> None:
        import webview

        self.icon.run_detached()
        self.hotkeys.start()
        log.info("started version %s", __version__)
        webview.start(private_mode=True)
        self.hotkeys.stop()
        self.icon.stop()
        log.info("stopped")

    def notify(self, message: str) -> None:
        try:
            self.icon.notify(message, APP_NAME)
        except Exception as exc:
            log.warning("notification failed: %s", type(exc).__name__)

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

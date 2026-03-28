from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

def _prepare_runtime_root() -> Path:
    runtime_root = Path(tempfile.mkdtemp(prefix="framelab-trace-"))
    config_dir = runtime_root / "config"
    cache_dir = runtime_root / "cache"
    config_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["FRAMELAB_CONFIG_DIR"] = str(config_dir)
    os.environ["FRAMELAB_METRICS_CACHE_PATH"] = str(cache_dir / "metrics.sqlite")
    os.environ["XDG_CACHE_HOME"] = str(cache_dir)
    os.environ["MPLCONFIGDIR"] = str(cache_dir / "mpl")
    os.environ.pop("QT_QPA_PLATFORM", None)
    return runtime_root


RUNTIME_ROOT = _prepare_runtime_root()
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6 import QtCore, QtGui, QtWidgets as qtw  # noqa: E402

from framelab.app import _close_selector_splash, _create_selector_splash  # noqa: E402
from framelab.icons import apply_app_identity, prepare_process_identity  # noqa: E402
from framelab.mpl_config import ensure_matplotlib_config_dir  # noqa: E402
from framelab.plugins import discover_plugin_manifests  # noqa: E402
from framelab.plugins.selection import (  # noqa: E402
    PluginStartupDialog,
    load_selected_plugin_ids,
    save_selected_plugin_ids,
)
from framelab.stylesheets import DARK_THEME  # noqa: E402
from framelab.window import FrameLabWindow  # noqa: E402
from tifffile import imwrite  # noqa: E402

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes


class _TopLevelTrace(QtCore.QObject):
    def __init__(self) -> None:
        super().__init__()
        self._start = time.monotonic()
        self.events: list[dict[str, object]] = []

    def _elapsed_ms(self) -> int:
        return int(round((time.monotonic() - self._start) * 1000.0))

    def _widget_payload(
        self,
        widget: qtw.QWidget,
        *,
        event_name: str,
    ) -> dict[str, object]:
        geometry = widget.frameGeometry()
        return {
            "t_ms": self._elapsed_ms(),
            "event": event_name,
            "class": type(widget).__name__,
            "object_name": widget.objectName(),
            "title": widget.windowTitle(),
            "visible": bool(widget.isVisible()),
            "modal": bool(widget.windowModality() != QtCore.Qt.NonModal),
            "window_flags": int(widget.windowFlags()),
            "geometry": (
                geometry.x(),
                geometry.y(),
                geometry.width(),
                geometry.height(),
            ),
        }

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if isinstance(watched, qtw.QWidget) and watched.isWindow():
            event_type = event.type()
            if event_type == QtCore.QEvent.Show:
                self.events.append(
                    self._widget_payload(watched, event_name="show"),
                )
            elif event_type == QtCore.QEvent.Hide:
                self.events.append(
                    self._widget_payload(watched, event_name="hide"),
                )
        return False

    def snapshot(self, app: qtw.QApplication) -> list[dict[str, object]]:
        payloads: list[dict[str, object]] = []
        for widget in app.topLevelWidgets():
            if not widget.isVisible():
                continue
            payloads.append(self._widget_payload(widget, event_name="snapshot"))
        return payloads


class _NativeWindowTrace:
    def __init__(self) -> None:
        self._start = time.monotonic()
        self._visible_windows: dict[int, dict[str, object]] = {}
        self.events: list[dict[str, object]] = []

    def _elapsed_ms(self) -> int:
        return int(round((time.monotonic() - self._start) * 1000.0))

    def _enumerate_visible_windows(self) -> dict[int, dict[str, object]]:
        if sys.platform != "win32":
            return {}

        user32 = ctypes.windll.user32
        windows: dict[int, dict[str, object]] = {}
        enum_proc_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HWND,
            wintypes.LPARAM,
        )

        def _callback(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True

            title_length = user32.GetWindowTextLengthW(hwnd)
            title_buffer = ctypes.create_unicode_buffer(title_length + 1)
            user32.GetWindowTextW(hwnd, title_buffer, title_length + 1)

            class_buffer = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buffer, 256)

            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))

            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            windows[int(hwnd)] = {
                "hwnd": int(hwnd),
                "pid": int(pid.value),
                "class_name": class_buffer.value,
                "title": title_buffer.value,
                "geometry": (
                    int(rect.left),
                    int(rect.top),
                    int(rect.right - rect.left),
                    int(rect.bottom - rect.top),
                ),
            }
            return True

        user32.EnumWindows(enum_proc_type(_callback), 0)
        return windows

    def prime(self) -> None:
        self._visible_windows = self._enumerate_visible_windows()

    def poll(self) -> None:
        current = self._enumerate_visible_windows()
        for hwnd, payload in current.items():
            if hwnd in self._visible_windows:
                continue
            self.events.append(
                {
                    "t_ms": self._elapsed_ms(),
                    "event": "native-show",
                    **payload,
                },
            )
        for hwnd, payload in self._visible_windows.items():
            if hwnd in current:
                continue
            self.events.append(
                {
                    "t_ms": self._elapsed_ms(),
                    "event": "native-hide",
                    **payload,
                },
            )
        self._visible_windows = current


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _write_session_datacard(session_root: Path) -> None:
    _write_json(
        session_root / "session_datacard.json",
        {
            "schema_version": "1.0",
            "entity": "session",
            "identity": {"label": session_root.name},
            "paths": {
                "session_root_rel": None,
                "acquisitions_root_rel": "acquisitions",
                "notes_rel": None,
            },
            "session_defaults": {},
            "notes": "",
        },
    )


def _write_acquisition_datacard(acquisition_root: Path) -> None:
    _write_json(
        acquisition_root / "acquisition_datacard.json",
        {
            "schema_version": "1.0",
            "entity": "acquisition",
            "identity": {"acquisition_id": acquisition_root.name},
            "paths": {"frames_dir": "frames"},
            "defaults": {},
            "overrides": [],
            "quality": {},
            "external_sources": {},
        },
    )


def _write_frame(path: Path, value: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    imwrite(path, np.full((4, 4), value, dtype=np.uint16))


def _build_trace_workspace(runtime_root: Path) -> tuple[Path, Path, str]:
    workspace_root = runtime_root / "calibration"
    session_root = (
        workspace_root
        / "camera-a"
        / "campaign-2026"
        / "2026-03-05__sess01"
    )
    acquisitions_root = session_root / "acquisitions"
    acquisitions_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)

    acquisition_root = acquisitions_root / "acq-0011__trace"
    acquisition_root.mkdir(parents=True, exist_ok=True)
    _write_acquisition_datacard(acquisition_root)
    _write_frame(acquisition_root / "frames" / "f0.tiff", 10)
    _write_frame(acquisition_root / "frames" / "f1.tiff", 20)

    acquisition_node_id = (
        "calibration:acquisition:"
        "camera-a/campaign-2026/2026-03-05__sess01/acquisitions/acq-0011__trace"
    )
    return workspace_root, acquisition_root, acquisition_node_id


def _print_events(events: list[dict[str, object]], *, header: str) -> None:
    print(header, flush=True)
    for event in events:
        if "class" in event:
            print(
                (
                    f"{event['t_ms']:>5}ms | {event['event']:<8} | "
                    f"{event['class']} | object={event['object_name']!r} | "
                    f"title={event['title']!r} | visible={event['visible']} | "
                    f"modal={event['modal']} | geom={event['geometry']}"
                ),
                flush=True,
            )
            continue
        print(
            (
                f"{event['t_ms']:>5}ms | {event['event']:<11} | "
                f"pid={event['pid']:<6} | hwnd={event['hwnd']:<10} | "
                f"class={event['class_name']!r} | title={event['title']!r} | "
                f"geom={event['geometry']}"
            ),
            flush=True,
        )


def _run_full_launch_trace(
    app: qtw.QApplication,
    trace: _TopLevelTrace,
) -> int:
    workspace_root, acquisition_root, acquisition_node_id = _build_trace_workspace(
        RUNTIME_ROOT,
    )
    snapshot_events: list[dict[str, object]] = []
    state: dict[str, object] = {
        "selector": None,
        "window": None,
    }
    native_trace = _NativeWindowTrace()

    def _capture_snapshot() -> None:
        snapshot_events.extend(trace.snapshot(app))
        native_trace.poll()

    def _close_secondary_windows() -> None:
        print("[trace] closing secondary windows", flush=True)
        for widget in list(app.topLevelWidgets()):
            if widget is state["window"]:
                continue
            if isinstance(widget, qtw.QWidget):
                try:
                    if isinstance(widget, qtw.QMessageBox):
                        widget.accept()
                        continue
                    widget.close()
                except Exception:
                    pass

    def _trigger_shortcut() -> None:
        window = state["window"]
        if not isinstance(window, FrameLabWindow):
            return
        action = getattr(window, "_acquisition_datacard_wizard_shortcut_action", None)
        if not isinstance(action, QtGui.QAction):
            print("Datacard wizard shortcut action was not registered.", flush=True)
            return
        print("[trace] triggering Ctrl+Shift+D", flush=True)
        action.trigger()

    def _trigger_scan_scope() -> None:
        window = state["window"]
        if not isinstance(window, FrameLabWindow):
            return
        action = getattr(window, "file_scan_scope_action", None)
        if not isinstance(action, QtGui.QAction):
            print("Scan scope action was not registered.", flush=True)
            return
        print("[trace] triggering Scan Selected Scope", flush=True)
        action.trigger()

    def _launch_main_window() -> None:
        selector = state["selector"]
        if not isinstance(selector, PluginStartupDialog):
            return
        print("[trace] launching main window", flush=True)
        enabled_plugin_ids = selector.enabled_plugin_ids()
        save_selected_plugin_ids(enabled_plugin_ids)
        window = FrameLabWindow(enabled_plugin_ids=enabled_plugin_ids)
        window.resize(1280, 860)
        window.set_workflow_context(
            str(workspace_root),
            "calibration",
            active_node_id=acquisition_node_id,
        )
        state["window"] = window
        window.showMaximized()
        app.processEvents()
        folder_edit = getattr(window, "folder_edit", None)
        if isinstance(folder_edit, qtw.QLineEdit):
            folder_edit.setText(str(acquisition_root))
        QtCore.QTimer.singleShot(700, _trigger_scan_scope)
        QtCore.QTimer.singleShot(2400, _trigger_shortcut)
        QtCore.QTimer.singleShot(4200, _close_secondary_windows)
        QtCore.QTimer.singleShot(5100, window.close)
        QtCore.QTimer.singleShot(6200, app.quit)

    splash = _create_selector_splash(app)
    manifests = discover_plugin_manifests()
    selected_ids = load_selected_plugin_ids(manifests)
    selector = PluginStartupDialog(
        manifests,
        selected_plugin_ids=selected_ids,
    )
    state["selector"] = selector
    selector.accepted.connect(_launch_main_window)
    _close_selector_splash(splash, target=selector)
    selector.show()
    app.processEvents()
    native_trace.prime()

    timer = QtCore.QTimer()
    timer.setInterval(80)
    timer.timeout.connect(_capture_snapshot)
    timer.start()

    QtCore.QTimer.singleShot(550, selector.accept)
    QtCore.QTimer.singleShot(15000, app.quit)
    app.exec()
    timer.stop()

    _print_events(trace.events, header="=== Show/Hide Events ===")
    _print_events(snapshot_events, header="=== Top-Level Snapshots ===")
    _print_events(native_trace.events, header="=== Native Window Events ===")
    return 0


def main() -> int:
    prepare_process_identity()
    ensure_matplotlib_config_dir()
    app = qtw.QApplication.instance()
    if app is None:
        app = qtw.QApplication(sys.argv)
    apply_app_identity(app)
    app.setStyleSheet(DARK_THEME)
    app.setQuitOnLastWindowClosed(False)

    trace = _TopLevelTrace()
    app.installEventFilter(trace)
    try:
        return _run_full_launch_trace(app, trace)
    finally:
        app.removeEventFilter(trace)


if __name__ == "__main__":
    raise SystemExit(main())

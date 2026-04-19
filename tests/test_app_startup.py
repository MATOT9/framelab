from __future__ import annotations

from pathlib import Path

import pytest

import framelab.app as app_module


pytestmark = [pytest.mark.fast, pytest.mark.core]


class _FakeApp:
    def __init__(self) -> None:
        self.stylesheet = ""

    def setStyleSheet(self, stylesheet: str) -> None:
        self.stylesheet = stylesheet

    def processEvents(self) -> None:
        return None

    def exec(self) -> int:
        return 99


def _fake_qapplication_class(app: _FakeApp):
    class _FakeQApplication:
        def __new__(cls, argv):
            return app

        @staticmethod
        def instance():
            return app

    return _FakeQApplication


def test_main_closes_selector_splash_before_selector_exec(monkeypatch) -> None:
    app = _FakeApp()
    events: list[str] = []

    class _FakeSelector:
        def __init__(self, *args, **kwargs) -> None:
            events.append("selector-init")

        def exec(self) -> int:
            events.append("selector-exec")
            return app_module.qtw.QDialog.Rejected

    monkeypatch.setattr(app_module, "prepare_process_identity", lambda: None)
    monkeypatch.setattr(app_module, "ensure_matplotlib_config_dir", lambda: None)
    monkeypatch.setattr(
        app_module.qtw,
        "QApplication",
        _fake_qapplication_class(app),
    )
    monkeypatch.setattr(app_module, "apply_app_identity", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module, "discover_plugin_manifests", lambda: [])
    monkeypatch.setattr(app_module, "load_selected_plugin_ids", lambda manifests: frozenset())
    monkeypatch.setattr(app_module, "save_selected_plugin_ids", lambda plugin_ids: None)
    monkeypatch.setattr(app_module, "PluginStartupDialog", _FakeSelector)
    monkeypatch.setattr(
        app_module,
        "_create_selector_splash",
        lambda app: events.append("splash-open") or object(),
    )
    monkeypatch.setattr(
        app_module,
        "_close_selector_splash",
        lambda splash, *, target=None: events.append("splash-close"),
    )
    monkeypatch.setattr(app_module.QTimer, "singleShot", lambda _ms, fn: fn())

    result = app_module.main()

    assert result == 0
    assert events == [
        "splash-open",
        "selector-init",
        "splash-close",
        "selector-exec",
    ]


def test_main_closes_selector_splash_on_plugin_startup_error(monkeypatch) -> None:
    app = _FakeApp()
    events: list[str] = []

    monkeypatch.setattr(app_module, "prepare_process_identity", lambda: None)
    monkeypatch.setattr(app_module, "ensure_matplotlib_config_dir", lambda: None)
    monkeypatch.setattr(
        app_module.qtw,
        "QApplication",
        _fake_qapplication_class(app),
    )
    monkeypatch.setattr(app_module, "apply_app_identity", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        app_module,
        "_create_selector_splash",
        lambda app: events.append("splash-open") or object(),
    )
    monkeypatch.setattr(
        app_module,
        "_close_selector_splash",
        lambda splash, *, target=None: events.append("splash-close"),
    )
    monkeypatch.setattr(
        app_module,
        "discover_plugin_manifests",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        app_module,
        "_record_startup_exception",
        lambda title: Path("/tmp/framelab-startup-error.log"),
    )
    monkeypatch.setattr(
        app_module.qtw.QMessageBox,
        "critical",
        lambda parent, title, message: events.append(f"critical:{title}:{message}"),
    )

    result = app_module.main()

    assert result == 1
    assert events == [
        "splash-open",
        "splash-close",
        (
            "critical:Plugin Startup Error:boom\n\n"
            "Full traceback saved to:\n"
            "/tmp/framelab-startup-error.log"
        ),
    ]


def test_main_reports_plugin_load_error_with_traceback_path(monkeypatch) -> None:
    app = _FakeApp()
    events: list[str] = []

    class _FakeSelector:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def exec(self) -> int:
            return app_module.qtw.QDialog.Accepted

        def enabled_plugin_ids(self):
            return frozenset({"session_manager"})

    monkeypatch.setattr(app_module, "prepare_process_identity", lambda: None)
    monkeypatch.setattr(app_module, "ensure_matplotlib_config_dir", lambda: None)
    monkeypatch.setattr(
        app_module.qtw,
        "QApplication",
        _fake_qapplication_class(app),
    )
    monkeypatch.setattr(app_module, "apply_app_identity", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module, "discover_plugin_manifests", lambda: [])
    monkeypatch.setattr(app_module, "load_selected_plugin_ids", lambda manifests: frozenset())
    monkeypatch.setattr(app_module, "save_selected_plugin_ids", lambda plugin_ids: None)
    monkeypatch.setattr(app_module, "PluginStartupDialog", _FakeSelector)
    monkeypatch.setattr(app_module, "_create_selector_splash", lambda app: None)
    monkeypatch.setattr(app_module, "_close_selector_splash", lambda splash, *, target=None: None)
    monkeypatch.setattr(
        app_module,
        "FrameLabWindow",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("plugin load boom")),
    )
    monkeypatch.setattr(
        app_module,
        "_record_startup_exception",
        lambda title: Path("/tmp/framelab-plugin-load.log"),
    )
    monkeypatch.setattr(
        app_module.qtw.QMessageBox,
        "critical",
        lambda parent, title, message: events.append(f"critical:{title}:{message}"),
    )

    result = app_module.main()

    assert result == 1
    assert events == [
        (
            "critical:Plugin Load Error:plugin load boom\n\n"
            "Full traceback saved to:\n"
            "/tmp/framelab-plugin-load.log"
        ),
    ]


def test_install_nuitka_pyside6_signal_workaround_wraps_bound_methods(monkeypatch) -> None:
    events: list[tuple[str, object, object | None]] = []

    class _FakeSignalInstance:
        pass

    def _raw_connect(self, slot, type=None):
        events.append(("connect", slot, type))
        return slot

    def _raw_disconnect(self, slot=None):
        events.append(("disconnect", slot, None))
        return slot

    class _FakeQTimer:
        pass

    def _raw_single_shot(self, *args, **kwargs):
        slot = None
        for candidate in reversed(args):
            if callable(candidate):
                slot = candidate
                break
        if slot is None:
            slot = kwargs.get("slot")
        events.append(("singleShot", slot, None))
        return slot

    connect_namespace = {
        "events": events,
        "orig_connect": _raw_connect,
        "protect": lambda slot: slot,
    }
    exec(
        """
def _fake_connect(self, slot, type=None):
    events.append(("wrapped-connect", slot, type))
    return orig_connect(self, protect(slot), type)
""",
        connect_namespace,
    )
    disconnect_namespace = {
        "events": events,
        "orig_disconnect": _raw_disconnect,
        "protect": lambda slot: slot,
    }
    exec(
        """
def _fake_disconnect(self, slot=None):
    events.append(("wrapped-disconnect", slot, None))
    return orig_disconnect(self, protect(slot))
""",
        disconnect_namespace,
    )
    single_shot_namespace = {
        "events": events,
        "orig_singleShot": _raw_single_shot,
        "protect": lambda slot: slot,
    }
    exec(
        """
def _fake_single_shot(self, *args, **kwargs):
    events.append(("wrapped-singleShot", args[-1] if args else kwargs.get("slot"), None))
    if args:
        args = list(args)
        args[0] = protect(args[0])
    return orig_singleShot(self, *args, **kwargs)
""",
        single_shot_namespace,
    )

    _fake_connect = connect_namespace["_fake_connect"]
    _fake_disconnect = disconnect_namespace["_fake_disconnect"]
    _fake_single_shot = single_shot_namespace["_fake_single_shot"]
    _fake_connect.__module__ = "PySide6-postLoad"
    _fake_disconnect.__module__ = "PySide6-postLoad"
    _fake_single_shot.__module__ = "PySide6-postLoad"
    _FakeSignalInstance.connect = _fake_connect
    _FakeSignalInstance.disconnect = _fake_disconnect
    _FakeQTimer.singleShot = _fake_single_shot

    fake_qtcore = type(
        "FakeQtCore",
        (),
        {
            "SignalInstance": _FakeSignalInstance,
            "QTimer": _FakeQTimer,
            "Qt": type(
                "FakeQt",
                (),
                {
                    "ConnectionType": type(
                        "FakeConnectionType",
                        (),
                        {"AutoConnection": object()},
                    ),
                },
            ),
        },
    )
    monkeypatch.setattr(app_module, "QtCore", fake_qtcore)
    app_module._NUITKA_QT_SLOT_WRAPPERS.clear()
    app_module._NUITKA_QT_SLOT_WRAPPERS_FALLBACK.clear()
    app_module._NUITKA_QT_CALLABLE_WRAPPERS.clear()
    app_module._NUITKA_QT_CALLABLE_WRAPPERS_FALLBACK.clear()

    class _Receiver:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def slot(self, *args: str) -> None:
            self.calls.append(args)

    receiver = _Receiver()

    app_module._install_nuitka_pyside6_signal_workaround()

    fake_qtcore.SignalInstance.connect(object(), receiver.slot)
    fake_qtcore.SignalInstance.disconnect(object(), receiver.slot)
    fake_qtcore.QTimer.singleShot(0, receiver.slot)
    inline_lambda = lambda *args: receiver.calls.append(("lambda", *args))
    fake_qtcore.SignalInstance.connect(object(), inline_lambda)
    fake_qtcore.QTimer.singleShot(0, inline_lambda)

    connect_slot = events[0][1]
    disconnect_slot = events[1][1]
    timer_slot = events[2][1]
    lambda_connect_slot = events[3][1]
    lambda_timer_slot = events[4][1]

    assert callable(connect_slot)
    assert connect_slot is disconnect_slot
    assert connect_slot is timer_slot
    assert callable(lambda_connect_slot)
    assert lambda_connect_slot is lambda_timer_slot

    def _replacement(*args: str) -> None:
        receiver.calls.append(("replacement", *args))

    receiver.slot = _replacement  # type: ignore[method-assign]

    connect_slot("connect")
    timer_slot("timer")
    lambda_connect_slot("scan")

    assert receiver.calls == [
        ("replacement", "connect"),
        ("replacement", "timer"),
        ("lambda", "scan"),
    ]
    wrapped_events = [entry[0] for entry in events if entry[0].startswith("wrapped-")]
    assert wrapped_events == []


def test_create_selector_splash_still_allows_windows(monkeypatch) -> None:
    class _FakeSplashApp:
        def platformName(self) -> str:
            return "windows"

        def processEvents(self) -> None:
            return None

    class _FakePixmap:
        def isNull(self) -> bool:
            return False

    events: list[str] = []

    class _FakeSplash:
        def __init__(self, pixmap) -> None:
            events.append(f"pixmap:{type(pixmap).__name__}")

        def setObjectName(self, name: str) -> None:
            events.append(f"name:{name}")

        def show(self) -> None:
            events.append("show")

    class _FakePath:
        def exists(self) -> bool:
            return True

        def __str__(self) -> str:
            return "fake-splash.png"

    monkeypatch.setattr(app_module.sys, "platform", "win32")
    monkeypatch.setattr(app_module, "_selector_splash_path", lambda: _FakePath())
    monkeypatch.setattr(app_module.QtGui, "QPixmap", lambda path: _FakePixmap())
    monkeypatch.setattr(app_module.qtw, "QSplashScreen", _FakeSplash)

    splash = app_module._create_selector_splash(_FakeSplashApp())

    assert splash is not None
    assert events == [
        "pixmap:_FakePixmap",
        "name:FrameLabSplash",
        "show",
    ]

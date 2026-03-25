from __future__ import annotations

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
        app_module.qtw.QMessageBox,
        "critical",
        lambda parent, title, message: events.append(f"critical:{title}:{message}"),
    )

    result = app_module.main()

    assert result == 1
    assert events == [
        "splash-open",
        "splash-close",
        "critical:Plugin Startup Error:boom",
    ]

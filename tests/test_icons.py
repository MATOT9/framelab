from __future__ import annotations

import pytest
from PySide6 import QtWidgets as qtw
from PySide6.QtCore import Qt

import framelab.window as window_module
from framelab.icons import _apply_icon_to_widget, apply_app_identity, load_app_icon


pytestmark = [pytest.mark.fast, pytest.mark.core]


def test_load_app_icon_returns_non_null_icon(qapp) -> None:
    assert not load_app_icon().isNull()


def test_apply_app_identity_updates_widget_and_native_handle(qapp) -> None:
    class _FakeHandle:
        def __init__(self) -> None:
            self.icon = None

        def setIcon(self, icon) -> None:
            self.icon = icon

    class _FakeWindow:
        def __init__(self) -> None:
            self.icon = None
            self.handle = _FakeHandle()

        def setWindowIcon(self, icon) -> None:
            self.icon = icon

        def windowHandle(self):
            return self.handle

    fake_window = _FakeWindow()

    apply_app_identity(qapp, fake_window)

    assert fake_window.icon is not None
    assert fake_window.handle.icon is not None
    assert fake_window.handle.icon.cacheKey() == fake_window.icon.cacheKey()


def test_apply_icon_to_widget_skips_native_handle_for_non_top_level_qwidgets(qapp) -> None:
    class _ProbeDock(qtw.QDockWidget):
        def __init__(self) -> None:
            super().__init__("Workflow Explorer")
            self.window_icon_calls = 0
            self.window_handle_calls = 0

        def setWindowIcon(self, icon) -> None:
            self.window_icon_calls += 1
            super().setWindowIcon(icon)

        def windowHandle(self):
            self.window_handle_calls += 1
            return super().windowHandle()

    main_window = qtw.QMainWindow()
    dock = _ProbeDock()
    main_window.addDockWidget(Qt.LeftDockWidgetArea, dock)

    try:
        _apply_icon_to_widget(dock, load_app_icon())
        assert dock.window_icon_calls == 0
        assert dock.window_handle_calls == 0
    finally:
        dock.close()
        dock.deleteLater()
        main_window.close()
        main_window.deleteLater()
        qapp.processEvents()


def test_apply_app_identity_with_explicit_window_skips_other_top_levels(qapp) -> None:
    class _ProbeDock(qtw.QDockWidget):
        def __init__(self) -> None:
            super().__init__("Workflow Explorer")
            self.window_handle_calls = 0

        def windowHandle(self):
            self.window_handle_calls += 1
            return super().windowHandle()

    main_window = qtw.QMainWindow()
    dock = _ProbeDock()
    main_window.addDockWidget(Qt.LeftDockWidgetArea, dock)
    dock.setFloating(True)

    try:
        apply_app_identity(qapp, main_window)
        assert dock.window_handle_calls == 0
    finally:
        dock.close()
        dock.deleteLater()
        main_window.close()
        main_window.deleteLater()
        qapp.processEvents()


def test_apply_icon_to_widget_skips_native_handle_for_hidden_top_level_widgets(
    qapp,
) -> None:
    class _ProbeDialog(qtw.QDialog):
        def __init__(self) -> None:
            super().__init__()
            self.window_handle_calls = 0

        def windowHandle(self):
            self.window_handle_calls += 1
            return super().windowHandle()

    dialog = _ProbeDialog()

    try:
        _apply_icon_to_widget(dialog, load_app_icon())
        assert dialog.window_handle_calls == 0
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_main_window_reapplies_app_identity_after_show(
    framelab_window_factory,
    monkeypatch,
    qapp,
) -> None:
    calls: list[object] = []

    def _record(app, window=None) -> None:
        calls.append(window)

    monkeypatch.setattr(window_module, "apply_app_identity", _record)

    window = framelab_window_factory(enabled_plugin_ids=())
    try:
        window.show()
        qapp.processEvents()
        qapp.processEvents()
        if window_module.sys.platform == "win32":
            assert window not in calls
        else:
            assert window in calls
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()

from __future__ import annotations

import pytest

import framelab.window as window_module
from framelab.icons import apply_app_identity, load_app_icon


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
        assert window in calls
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()

from __future__ import annotations

import pytest

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

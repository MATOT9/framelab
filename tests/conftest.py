"""Shared pytest configuration and fixtures for the FrameLab test suite."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator

import pytest


# Keep shell and CI test runs headless by default. Developers can still
# override this explicitly when they want to exercise a visible Qt backend.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    """Return one shared QApplication instance for pytest-managed tests."""

    from PySide6 import QtWidgets as qtw

    app = qtw.QApplication.instance()
    if app is None:
        app = qtw.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture
def process_events(qapp) -> Callable[[], None]:
    """Return a small helper that flushes the Qt event loop."""

    def _process_events() -> None:
        qapp.processEvents()

    return _process_events


@pytest.fixture
def framelab_window_factory(
    qapp,
) -> Iterator[Callable[..., object]]:
    """Create windows with predictable cleanup for future pytest-style tests."""

    from framelab.window import FrameLabWindow

    windows: list[FrameLabWindow] = []

    def _factory(
        *,
        enabled_plugin_ids: tuple[str, ...] = (),
        show: bool = False,
        width: int | None = None,
        height: int | None = None,
    ) -> FrameLabWindow:
        window = FrameLabWindow(enabled_plugin_ids=enabled_plugin_ids)
        windows.append(window)
        if width is not None and height is not None:
            window.resize(width, height)
        if show:
            window.show()
            qapp.processEvents()
        return window

    yield _factory

    for window in reversed(windows):
        try:
            window.close()
        except Exception:
            pass
        try:
            window.deleteLater()
        except Exception:
            pass
    qapp.processEvents()

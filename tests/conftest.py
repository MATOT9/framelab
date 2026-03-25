"""Shared pytest configuration and fixtures for the FrameLab test suite."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator

import pytest


# Keep shell and CI test runs headless by default. Developers can still
# override this explicitly when they want to exercise a visible Qt backend.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session", autouse=True)
def isolated_runtime_paths(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    """Route persisted config and cache paths to one worker-local temp root."""

    runtime_root = tmp_path_factory.mktemp("framelab-runtime")
    config_dir = runtime_root / "config"
    cache_root = runtime_root / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_root / "metrics.sqlite"

    previous_config = os.environ.get("FRAMELAB_CONFIG_DIR")
    previous_cache = os.environ.get("FRAMELAB_METRICS_CACHE_PATH")
    previous_xdg_cache = os.environ.get("XDG_CACHE_HOME")
    previous_mpl = os.environ.get("MPLCONFIGDIR")

    os.environ["FRAMELAB_CONFIG_DIR"] = str(config_dir)
    os.environ["FRAMELAB_METRICS_CACHE_PATH"] = str(cache_path)
    os.environ["XDG_CACHE_HOME"] = str(cache_root)
    os.environ["MPLCONFIGDIR"] = str(cache_root / "mpl")
    try:
        yield
    finally:
        if previous_config is None:
            os.environ.pop("FRAMELAB_CONFIG_DIR", None)
        else:
            os.environ["FRAMELAB_CONFIG_DIR"] = previous_config
        if previous_cache is None:
            os.environ.pop("FRAMELAB_METRICS_CACHE_PATH", None)
        else:
            os.environ["FRAMELAB_METRICS_CACHE_PATH"] = previous_cache
        if previous_xdg_cache is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = previous_xdg_cache
        if previous_mpl is None:
            os.environ.pop("MPLCONFIGDIR", None)
        else:
            os.environ["MPLCONFIGDIR"] = previous_mpl


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
def widget_factory(
    qapp,
) -> Iterator[Callable[[type[object]], object]]:
    """Create lightweight Qt widgets with predictable cleanup."""

    widgets: list[object] = []

    def _factory(widget_type, *args, **kwargs):
        widget = widget_type(*args, **kwargs)
        widgets.append(widget)
        return widget

    yield _factory

    for widget in reversed(widgets):
        try:
            widget.close()
        except Exception:
            pass
        try:
            widget.deleteLater()
        except Exception:
            pass
    qapp.processEvents()


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

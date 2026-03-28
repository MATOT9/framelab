"""Shared matplotlib canvas helpers for Qt embedding."""

from __future__ import annotations

from typing import Callable

from .mpl_config import ensure_matplotlib_config_dir

ensure_matplotlib_config_dir()

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as _FigureCanvasQTAgg
except Exception:
    FigureCanvasQTAgg = None  # type: ignore[assignment]
else:
    class FigureCanvasQTAgg(_FigureCanvasQTAgg):
        """Figure canvas that can rerun layout logic after Qt resizes."""

        def __init__(self, figure, *, resize_callback: Callable[[], None] | None = None):
            super().__init__(figure)
            self._resize_callback = resize_callback

        def set_resize_callback(
            self,
            callback: Callable[[], None] | None,
        ) -> None:
            """Update the resize callback used after Qt resize events."""

            self._resize_callback = callback

        def resizeEvent(self, event) -> None:  # type: ignore[override]
            super().resizeEvent(event)
            callback = self._resize_callback
            if not callable(callback):
                return
            try:
                callback()
            except Exception:
                return

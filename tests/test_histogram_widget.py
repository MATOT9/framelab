from __future__ import annotations

import time

import numpy as np
import pytest

from framelab.widgets import HistogramWidget, MATPLOTLIB_AVAILABLE


pytestmark = [
    pytest.mark.ui,
    pytest.mark.core,
    pytest.mark.skipif(not MATPLOTLIB_AVAILABLE, reason="matplotlib unavailable"),
]


def _spin_until(qapp, predicate, *, timeout_ms: int = 1000) -> None:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    qapp.processEvents()
    assert predicate()


def test_histogram_widget_uses_approximate_counts_before_exact_refresh(qapp) -> None:
    widget = HistogramWidget()
    image = np.arange(500_000, dtype=np.float32).reshape(1000, 500)

    widget.set_image(image, exact=False)
    qapp.processEvents()

    assert widget._pending_image is not None
    initial_counts = np.asarray(widget._counts)
    assert int(initial_counts.sum()) < image.size

    _spin_until(qapp, lambda: widget._pending_image is None)

    exact_counts = np.asarray(widget._counts)
    assert int(exact_counts.sum()) == image.size
    assert int(exact_counts.sum()) > int(initial_counts.sum())
    widget.deleteLater()


def test_histogram_widget_clear_cancels_pending_exact_refresh(qapp) -> None:
    widget = HistogramWidget()
    image = np.arange(500_000, dtype=np.float32).reshape(1000, 500)

    widget.set_image(image, exact=False)
    qapp.processEvents()
    assert widget._pending_image is not None

    widget.clear_histogram()
    _spin_until(qapp, lambda: not widget._exact_timer.isActive(), timeout_ms=400)

    assert widget._pending_image is None
    assert widget._counts is None
    assert widget._edges is None
    widget.deleteLater()


def test_histogram_widget_reserves_bottom_margin_for_x_axis_label(qapp) -> None:
    widget = HistogramWidget()

    assert widget._figure is not None
    assert widget._figure.subplotpars.bottom >= 0.16

    widget.deleteLater()

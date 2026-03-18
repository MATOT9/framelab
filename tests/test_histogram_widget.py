from __future__ import annotations

import time
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6 import QtWidgets as qtw

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


def _plot_event(
    widget: HistogramWidget,
    *,
    xdata: float | None,
    ydata: float | None,
    button: object = 1,
    dblclick: bool = False,
    pixel_x: float | None = None,
    pixel_y: float | None = None,
    inaxes=None,
):
    if pixel_x is None or pixel_y is None:
        assert xdata is not None and ydata is not None
        pixel_x, pixel_y = widget._axes.transData.transform((xdata, ydata))
    return SimpleNamespace(
        inaxes=widget._axes if inaxes is None else inaxes,
        xdata=xdata,
        ydata=ydata,
        x=float(pixel_x),
        y=float(pixel_y),
        button=button,
        dblclick=dblclick,
    )


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


def test_histogram_widget_supports_zoom_pan_and_reset(qapp) -> None:
    widget = HistogramWidget()
    image = np.arange(100, dtype=np.float32).reshape(10, 10)
    widget.set_image(image)
    qapp.processEvents()

    full_xlim = tuple(widget._axes.get_xlim())
    full_ylim = tuple(widget._axes.get_ylim())
    center_x = float(sum(full_xlim) / 2.0)
    center_y = float(sum(full_ylim) / 2.0)

    widget._on_plot_scroll(
        _plot_event(widget, xdata=center_x, ydata=center_y, button="up"),
    )
    qapp.processEvents()
    zoom_xlim = tuple(widget._axes.get_xlim())
    assert (zoom_xlim[1] - zoom_xlim[0]) < (full_xlim[1] - full_xlim[0])

    widget._on_plot_press(
        _plot_event(widget, xdata=center_x, ydata=center_y, button=2),
    )
    widget._on_plot_motion(
        _plot_event(widget, xdata=center_x + 5.0, ydata=center_y, button=2),
    )
    qapp.processEvents()
    panned_xlim = tuple(widget._axes.get_xlim())
    assert panned_xlim[0] < zoom_xlim[0]
    widget._on_plot_release(_plot_event(widget, xdata=center_x, ydata=center_y))

    widget._on_plot_press(
        _plot_event(widget, xdata=center_x, ydata=center_y, dblclick=True),
    )
    qapp.processEvents()

    assert widget._axes.get_xlim() == pytest.approx(full_xlim)
    assert widget._axes.get_ylim() == pytest.approx(full_ylim)
    widget.deleteLater()


def test_histogram_context_menu_reset_restores_full_view(qapp, monkeypatch) -> None:
    widget = HistogramWidget()
    image = np.arange(100, dtype=np.float32).reshape(10, 10)
    widget.set_image(image)
    qapp.processEvents()
    full_xlim = tuple(widget._axes.get_xlim())

    widget.zoom_to_x_range(10.0, 20.0)
    qapp.processEvents()

    monkeypatch.setattr(
        widget,
        "_exec_plot_context_menu",
        lambda menu: menu.actions()[0],
    )
    widget._show_plot_context_menu()
    qapp.processEvents()

    assert widget._axes.get_xlim() == pytest.approx(full_xlim)
    widget.deleteLater()


def test_histogram_selection_zoom_keeps_full_image_histogram_counts(qapp) -> None:
    widget = HistogramWidget()
    image = np.arange(100, dtype=np.float32).reshape(10, 10)
    widget.set_image(image)
    qapp.processEvents()

    baseline_counts = np.asarray(widget._counts).copy()
    full_xlim = tuple(widget._axes.get_xlim())
    full_ylim = tuple(widget._axes.get_ylim())
    start_x = full_xlim[0] + (full_xlim[1] - full_xlim[0]) * 0.2
    end_x = full_xlim[0] + (full_xlim[1] - full_xlim[0]) * 0.45
    start_y = full_ylim[0] + (full_ylim[1] - full_ylim[0]) * 0.15
    end_y = full_ylim[0] + (full_ylim[1] - full_ylim[0]) * 0.6

    widget._on_plot_press(
        _plot_event(widget, xdata=start_x, ydata=start_y, button=1),
    )
    widget._on_plot_motion(
        _plot_event(widget, xdata=end_x, ydata=end_y, button=1),
    )
    widget._on_plot_release(
        _plot_event(widget, xdata=end_x, ydata=end_y, button=1),
    )
    qapp.processEvents()

    assert int(np.asarray(widget._counts).sum()) == image.size
    assert np.array_equal(widget._counts, baseline_counts)
    xlim = tuple(widget._axes.get_xlim())
    ylim = tuple(widget._axes.get_ylim())
    assert xlim[0] == pytest.approx(start_x)
    assert xlim[1] == pytest.approx(end_x)
    assert ylim[0] == pytest.approx(start_y)
    assert ylim[1] == pytest.approx(end_y)
    widget.deleteLater()


def test_histogram_selection_zoom_clamps_when_drag_leaves_plot_horizontally(
    qapp,
) -> None:
    widget = HistogramWidget()
    image = np.arange(100, dtype=np.float32).reshape(10, 10)
    widget.set_image(image)
    qapp.processEvents()

    full_xlim = tuple(widget._axes.get_xlim())
    full_ylim = tuple(widget._axes.get_ylim())
    start_x = full_xlim[0] + (full_xlim[1] - full_xlim[0]) * 0.25
    start_y = full_ylim[0] + (full_ylim[1] - full_ylim[0]) * 0.2
    end_y = full_ylim[0] + (full_ylim[1] - full_ylim[0]) * 0.55
    bbox = widget._axes.bbox
    inside_pixel_y = widget._axes.transData.transform((start_x, end_y))[1]

    widget._on_plot_press(
        _plot_event(widget, xdata=start_x, ydata=start_y, button=1),
    )
    widget._on_plot_motion(
        _plot_event(
            widget,
            xdata=None,
            ydata=None,
            button=1,
            pixel_x=float(bbox.x1) + 30.0,
            pixel_y=float(inside_pixel_y),
            inaxes=None,
        ),
    )
    widget._on_plot_release(
        _plot_event(
            widget,
            xdata=None,
            ydata=None,
            button=1,
            pixel_x=float(bbox.x1) + 30.0,
            pixel_y=float(inside_pixel_y),
            inaxes=None,
        ),
    )
    qapp.processEvents()

    xlim = tuple(widget._axes.get_xlim())
    ylim = tuple(widget._axes.get_ylim())
    assert xlim[0] == pytest.approx(start_x)
    assert xlim[1] == pytest.approx(full_xlim[1])
    assert ylim[1] == pytest.approx(end_y)
    widget.deleteLater()


def test_histogram_selection_zoom_clamps_when_drag_leaves_plot_vertically(
    qapp,
) -> None:
    widget = HistogramWidget()
    image = np.arange(100, dtype=np.float32).reshape(10, 10)
    widget.set_image(image)
    qapp.processEvents()

    full_xlim = tuple(widget._axes.get_xlim())
    full_ylim = tuple(widget._axes.get_ylim())
    start_x = full_xlim[0] + (full_xlim[1] - full_xlim[0]) * 0.2
    end_x = full_xlim[0] + (full_xlim[1] - full_xlim[0]) * 0.5
    start_y = full_ylim[0] + (full_ylim[1] - full_ylim[0]) * 0.25
    bbox = widget._axes.bbox
    inside_pixel_x = widget._axes.transData.transform((end_x, start_y))[0]

    widget._on_plot_press(
        _plot_event(widget, xdata=start_x, ydata=start_y, button=1),
    )
    widget._on_plot_motion(
        _plot_event(
            widget,
            xdata=None,
            ydata=None,
            button=1,
            pixel_x=float(inside_pixel_x),
            pixel_y=float(bbox.y1) + 25.0,
            inaxes=None,
        ),
    )
    widget._on_plot_release(
        _plot_event(
            widget,
            xdata=None,
            ydata=None,
            button=1,
            pixel_x=float(inside_pixel_x),
            pixel_y=float(bbox.y1) + 25.0,
            inaxes=None,
        ),
    )
    qapp.processEvents()

    xlim = tuple(widget._axes.get_xlim())
    ylim = tuple(widget._axes.get_ylim())
    assert xlim[0] == pytest.approx(start_x)
    assert xlim[1] == pytest.approx(end_x)
    assert ylim[1] == pytest.approx(full_ylim[1])
    widget.deleteLater()

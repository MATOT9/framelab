from __future__ import annotations

import time
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6 import QtWidgets as qtw

import framelab.widgets as widgets_module
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


def test_histogram_layout_updates_after_widget_shrinks(qapp) -> None:
    widget = HistogramWidget()
    image = np.arange(20_000, dtype=np.float32).reshape(200, 100)
    widget.resize(640, 360)
    widget.show()
    qapp.processEvents()

    widget.set_image(image)
    qapp.processEvents()
    widget._canvas.draw()
    wide_left = float(widget._figure.subplotpars.left)

    widget.resize(240, 360)
    qapp.processEvents()
    widget._canvas.draw()

    renderer = widget._canvas.get_renderer()
    tight_bbox = widget._axes.get_tightbbox(renderer)
    assert float(widget._figure.subplotpars.left) > wide_left
    assert float(tight_bbox.x0) >= -1.0
    widget.deleteLater()


def test_histogram_widget_uses_backend_counter_for_exact_histogram(
    qapp,
    monkeypatch,
) -> None:
    widget = HistogramWidget()
    calls: list[dict[str, object]] = []

    def _fake_compute_histogram(image, **kwargs):
        calls.append(
            {
                "shape": tuple(np.asarray(image).shape),
                "value_range": tuple(kwargs["value_range"]),
                "bin_count": int(kwargs["bin_count"]),
                "background": kwargs.get("background"),
            },
        )
        return np.array([2, 1, 1], dtype=np.uint64)

    monkeypatch.setattr(
        widgets_module.native_backend,
        "compute_histogram",
        _fake_compute_histogram,
    )

    image = np.array([[0, 1], [2, 3]], dtype=np.uint16)
    widget.set_image(image)
    qapp.processEvents()

    assert len(calls) == 1
    assert calls[0]["shape"] == (2, 2)
    assert calls[0]["background"] is None
    assert int(np.asarray(widget._counts).sum()) == 4
    widget.deleteLater()


def test_histogram_widget_uses_backend_range_for_background_exact_histogram(
    qapp,
    monkeypatch,
) -> None:
    widget = HistogramWidget()
    range_calls: list[dict[str, object]] = []
    hist_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        widgets_module.native_backend,
        "compute_value_range",
        lambda image, **kwargs: (
            range_calls.append(
                {
                    "shape": tuple(np.asarray(image).shape),
                    "background_shape": tuple(np.asarray(kwargs["background"]).shape),
                },
            )
            or (-2.0, 6.0)
        ),
    )
    monkeypatch.setattr(
        widgets_module.native_backend,
        "compute_histogram",
        lambda image, **kwargs: (
            hist_calls.append(
                {
                    "shape": tuple(np.asarray(image).shape),
                    "background_shape": tuple(np.asarray(kwargs["background"]).shape),
                    "value_range": tuple(kwargs["value_range"]),
                },
            )
            or np.array([1, 2, 1], dtype=np.uint64)
        ),
    )

    image = np.array([[2, 4], [6, 8]], dtype=np.uint16)
    background = np.array([[1, 1], [1, 1]], dtype=np.uint16)
    widget.set_image(image, background=background)
    qapp.processEvents()

    assert len(range_calls) == 1
    assert len(hist_calls) == 1
    assert hist_calls[0]["value_range"] == (-2.0, 6.0)
    assert np.asarray(widget._edges)[0] == pytest.approx(-2.0)
    assert np.asarray(widget._edges)[-1] == pytest.approx(6.0)
    widget.deleteLater()


def test_histogram_widget_makes_approximate_sampled_inputs_contiguous(
    qapp,
    monkeypatch,
) -> None:
    widget = HistogramWidget()
    widget.set_exact_refresh_suppressed(True)
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        widgets_module.native_backend,
        "compute_value_range",
        lambda image, **kwargs: (
            calls.append(
                {
                    "kind": "range",
                    "shape": tuple(np.asarray(image).shape),
                    "image_contiguous": bool(np.asarray(image).flags.c_contiguous),
                    "background_contiguous": bool(
                        np.asarray(kwargs["background"]).flags.c_contiguous,
                    ),
                },
            )
            or (0.0, 1.0)
        ),
    )
    monkeypatch.setattr(
        widgets_module.native_backend,
        "compute_histogram",
        lambda image, **kwargs: (
            calls.append(
                {
                    "kind": "hist",
                    "shape": tuple(np.asarray(image).shape),
                    "image_contiguous": bool(np.asarray(image).flags.c_contiguous),
                    "background_contiguous": bool(
                        np.asarray(kwargs["background"]).flags.c_contiguous,
                    ),
                },
            )
            or np.array([4, 5, 6], dtype=np.uint64)
        ),
    )

    image = np.arange(900_000, dtype=np.float32).reshape(1000, 900)
    background = np.zeros_like(image)
    widget.set_image(image, exact=False, background=background)
    qapp.processEvents()

    assert [call["kind"] for call in calls] == ["range", "hist"]
    assert calls[0]["shape"][0] == 1
    assert calls[1]["shape"] == calls[0]["shape"]
    assert calls[0]["shape"][1] <= widget._APPROXIMATE_SAMPLE_LIMIT
    assert all(call["image_contiguous"] for call in calls)
    assert all(call["background_contiguous"] for call in calls)
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


def test_histogram_context_menu_can_toggle_log_y_scale(qapp, monkeypatch) -> None:
    widget = HistogramWidget()
    image = np.arange(1, 101, dtype=np.float32).reshape(10, 10)
    widget.set_image(image)
    qapp.processEvents()

    monkeypatch.setattr(
        widget,
        "_exec_plot_context_menu",
        lambda menu: (
            menu.actions()[1].setChecked(True) or menu.actions()[1]
        ),
    )
    widget._show_plot_context_menu()
    qapp.processEvents()

    assert widget._log_scale_y
    assert widget._axes.get_yscale() == "log"
    assert widget._axes.get_ylim()[0] > 0.0
    widget.deleteLater()


def test_histogram_uses_full_image_x_range_including_outliers(qapp) -> None:
    widget = HistogramWidget()
    image = np.arange(110, dtype=np.float32).reshape(11, 10)
    image[-1, -1] = 5000.0
    widget.set_image(image)
    qapp.processEvents()

    xlim = tuple(widget._axes.get_xlim())
    assert xlim[0] <= float(np.min(image))
    assert xlim[1] >= float(np.max(image))
    assert widget._edges[-1] == pytest.approx(float(np.max(image)))
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


def test_histogram_zoom_out_keeps_x_axis_near_zero_floor(qapp) -> None:
    widget = HistogramWidget()
    image = np.arange(100, dtype=np.float32).reshape(10, 10)
    widget.set_image(image)
    qapp.processEvents()

    full_xlim = tuple(widget._axes.get_xlim())
    center_x = float(sum(full_xlim) / 2.0)
    center_y = float(sum(widget._axes.get_ylim()) / 2.0)
    lower_bound, _upper_bound = widget._x_view_bounds()

    for _ in range(25):
        widget._on_plot_scroll(
            _plot_event(widget, xdata=center_x, ydata=center_y, button="down"),
        )
    qapp.processEvents()

    xlim = tuple(widget._axes.get_xlim())
    assert xlim[0] >= lower_bound - 1e-6
    assert xlim[0] > -5.0
    widget.deleteLater()


def test_histogram_uses_same_major_and_minor_grid_style_as_analysis_plot(qapp) -> None:
    widget = HistogramWidget()
    image = np.arange(100, dtype=np.float32).reshape(10, 10)
    widget.set_theme("dark")
    widget.set_image(image)
    qapp.processEvents()

    major_tick = widget._axes.xaxis.get_major_ticks()[0]
    minor_tick = widget._axes.xaxis.get_minor_ticks()[0]
    major_line = major_tick.gridline
    minor_line = minor_tick.gridline

    assert major_line.get_visible()
    assert minor_line.get_visible()
    assert major_line.get_color() == "#64748b"
    assert minor_line.get_color() == "#94a3b8"
    assert major_line.get_alpha() == pytest.approx(0.42)
    assert minor_line.get_alpha() == pytest.approx(0.24)
    assert major_line.get_linewidth() == pytest.approx(0.85)
    assert minor_line.get_linewidth() == pytest.approx(0.65)
    assert minor_line.get_linestyle() == ":"
    widget.deleteLater()

"""Tests for plot-grid and export polish in the iris gain analysis plugin."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6 import QtWidgets as qtw

from framelab.plugins.analysis.iris_gain._shared import (
    MATPLOTLIB_AVAILABLE,
    _CurveSeries,
)
from framelab.plugins.analysis.iris_gain.plugin import IrisGainAnalysisPlugin


pytestmark = [pytest.mark.ui, pytest.mark.analysis]


def _make_plugin() -> tuple[IrisGainAnalysisPlugin, qtw.QWidget]:
    host = qtw.QWidget()
    plugin = IrisGainAnalysisPlugin()
    plugin.create_widget(host)
    curve = _CurveSeries(
        curve_id=1,
        label="Series 1",
        x_values=[1.0, 2.0, 3.0],
        y_values=[10.0, 11.5, 13.0],
        std_values=[0.5, 0.5, 0.5],
        sem_values=[0.25, 0.25, 0.25],
        error_values=[0.5, 0.5, 0.5],
        point_counts=[4, 4, 4],
    )
    plugin._update_plot(
        [curve],
        "Iris Position",
        "Mean Intensity",
        "std",
        [],
        False,
        "off",
    )
    return plugin, host


@pytest.mark.skipif(not MATPLOTLIB_AVAILABLE, reason="matplotlib not installed")
def test_iris_gain_plot_shows_major_and_minor_grid_lines(qapp) -> None:
    plugin, host = _make_plugin()
    try:
        assert plugin._canvas is not None
        assert plugin._axes is not None
        plugin._canvas.draw()

        major_lines = [
            tick.gridline
            for tick in plugin._axes.xaxis.get_major_ticks()
            if tick.gridline.get_visible()
        ]
        minor_lines = [
            tick.gridline
            for tick in plugin._axes.xaxis.get_minor_ticks()
            if tick.gridline.get_visible()
        ]

        assert major_lines
        assert minor_lines
        assert any(line.get_linestyle() in {":", "dotted"} for line in minor_lines)
        assert max((line.get_alpha() or 0.0) for line in major_lines) > max(
            (line.get_alpha() or 0.0) for line in minor_lines
        )
    finally:
        host.close()
        host.deleteLater()
        qapp.processEvents()


@pytest.mark.skipif(not MATPLOTLIB_AVAILABLE, reason="matplotlib not installed")
def test_iris_gain_plot_exports_png_jpg_and_pdf(tmp_path: Path, qapp) -> None:
    plugin, host = _make_plugin()
    try:
        outputs = [
            tmp_path / "trend.png",
            tmp_path / "trend.jpg",
            tmp_path / "trend.pdf",
        ]

        for path in outputs:
            saved = plugin._export_plot_to_file(path, dpi=180)
            assert saved == path
            assert path.is_file()
            assert path.stat().st_size > 0

        assert plugin._plot_export_dpi == 180
        assert plugin._plot_export_last_path == str(outputs[-1])
    finally:
        host.close()
        host.deleteLater()
        qapp.processEvents()

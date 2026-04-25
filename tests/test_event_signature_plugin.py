from __future__ import annotations

import pytest
from PySide6 import QtWidgets as qtw

from framelab.plugins.analysis import AnalysisContext, AnalysisRecord
from framelab.plugins.analysis.signature_event.plugin import (
    EventSignatureAnalysisPlugin,
)


pytestmark = [pytest.mark.analysis, pytest.mark.ui]


def _context(*, elapsed: bool = True) -> AnalysisContext:
    records: list[AnalysisRecord] = []
    for row, (max_pixel, roi_topk) in enumerate(((10.0, 5.0), (12.0, 7.0))):
        metadata: dict[str, object] = {
            "frame_index": row,
            "max_pixel": max_pixel,
            "roi_topk_mean": roi_topk,
        }
        if elapsed:
            metadata["elapsed_time_s"] = 1.25 * row
        records.append(
            AnalysisRecord(
                path=f"/tmp/frame-{row}.tif",
                metadata=metadata,
                mean=roi_topk,
                std=0.0,
                sem=0.0,
            ),
        )
    return AnalysisContext(
        mode="roi_topk",
        records=tuple(records),
        metadata_fields=(
            "elapsed_time_s",
            "frame_index",
            "max_pixel",
            "roi_topk_mean",
        ),
        normalization_enabled=False,
        normalization_scale=1.0,
    )


def _plugin(qapp) -> tuple[EventSignatureAnalysisPlugin, qtw.QWidget]:
    host = qtw.QWidget()
    plugin = EventSignatureAnalysisPlugin()
    plugin.create_widget(host)
    return plugin, host


def _set_combo(combo: qtw.QComboBox, value: str) -> None:
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


@pytest.mark.parametrize(
    ("x_mode", "y_mode", "expected"),
    [
        ("frame_index", "max_pixel", [(0.0, 10.0), (1.0, 12.0)]),
        ("elapsed_time_s", "max_pixel", [(0.0, 10.0), (1.25, 12.0)]),
        ("frame_index", "roi_topk_mean", [(0.0, 5.0), (1.0, 7.0)]),
        ("elapsed_time_s", "roi_topk_mean", [(0.0, 5.0), (1.25, 7.0)]),
    ],
)
def test_event_signature_plugin_populates_requested_plot_modes(
    qapp,
    x_mode: str,
    y_mode: str,
    expected: list[tuple[float, float]],
) -> None:
    plugin, host = _plugin(qapp)
    try:
        context = _context(elapsed=True)
        plugin.on_context_changed(context)
        assert plugin._x_axis_combo is not None
        assert plugin._y_axis_combo is not None
        _set_combo(plugin._x_axis_combo, x_mode)
        _set_combo(plugin._y_axis_combo, y_mode)
        plugin.run_analysis(context)
        qapp.processEvents()

        assert plugin._plot_points == pytest.approx(expected)
        assert plugin._table is not None
        assert plugin._table.rowCount() == 2
        assert plugin._table.item(0, 4).text() == f"{expected[0][1]:.6g}"
    finally:
        host.close()
        host.deleteLater()


def test_event_signature_elapsed_axis_requires_elapsed_metadata(qapp) -> None:
    plugin, host = _plugin(qapp)
    try:
        context = _context(elapsed=False)
        plugin.on_context_changed(context)
        plugin.run_analysis(context)
        assert plugin._x_axis_combo is not None

        assert plugin._x_axis_combo.findData("elapsed_time_s") < 0
        assert plugin._x_axis_combo.currentData() == "frame_index"
        assert plugin._plot_points == pytest.approx([(0.0, 10.0), (1.0, 12.0)])
    finally:
        host.close()
        host.deleteLater()


def test_event_signature_context_refresh_is_passive(qapp) -> None:
    plugin, host = _plugin(qapp)
    try:
        context = _context(elapsed=True)
        plugin.on_context_changed(context)

        assert plugin._context is context
        assert plugin._plot_points == []
        assert plugin._analysis_dirty
    finally:
        host.close()
        host.deleteLater()

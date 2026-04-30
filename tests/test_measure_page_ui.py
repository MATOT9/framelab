"""Integration tests for Measure-page contextual chrome."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PySide6 import QtCore, QtTest, QtWidgets as qtw
from tifffile import imwrite

import framelab.main_window.inspect_page as inspect_page_module
from framelab.metrics_state import MetricFamily, MetricFamilyState, ScanMetricPreset
from framelab.refresh_policy import RefreshReason
from framelab.runtime_tasks import RuntimeTaskState
from framelab.ui_primitives import StatusChip
from framelab.ui_density import VisibilityPolicy
from framelab.ui_settings import DensityMode
from framelab.window import FrameLabWindow


pytestmark = [pytest.mark.ui, pytest.mark.core]


@pytest.fixture
def measure_window(framelab_window_factory) -> FrameLabWindow:
    window = framelab_window_factory(enabled_plugin_ids=())
    window.ui_state_snapshot.splitter_sizes.clear()
    return window


def _measure_summary_values(window: FrameLabWindow) -> dict[str, str]:
    values: dict[str, str] = {}
    for card in window._measure_summary_strip.findChildren(qtw.QFrame, "SummaryCard"):
        label = card.findChild(qtw.QLabel, "SummaryLabel")
        value = card.findChild(qtw.QLabel, "SummaryValue")
        if label is None or value is None:
            continue
        values[label.text()] = value.text()
    return values


def _measure_header_chip_levels(window: FrameLabWindow) -> dict[str, str]:
    values: dict[str, str] = {}
    for chip in window._measure_header.findChildren(StatusChip):
        values[chip.text()] = str(chip.property("statusLevel") or "")
    return values


def _write_measure_dataset(tmp_path: Path) -> Path:
    dataset_root = tmp_path / "measure-dataset"
    dataset_root.mkdir(parents=True, exist_ok=True)
    imwrite(dataset_root / "a_dark.tiff", np.full((4, 4), 4, dtype=np.uint16))
    imwrite(dataset_root / "b_bright.tiff", np.full((4, 4), 12, dtype=np.uint16))
    return dataset_root


def _write_timestamped_measure_dataset(tmp_path: Path) -> Path:
    dataset_root = tmp_path / "timestamped-measure-dataset"
    dataset_root.mkdir(parents=True, exist_ok=True)
    imwrite(
        dataset_root / "00000000_20260419_183326_086Z_w4_h4_pMono12Packed.tiff",
        np.full((4, 4), 4, dtype=np.uint16),
    )
    imwrite(
        dataset_root / "00000001_20260419_183327_336Z_w4_h4_pMono12Packed.tiff",
        np.full((4, 4), 12, dtype=np.uint16),
    )
    return dataset_root


def _set_measure_current_row(window: FrameLabWindow, source_row: int) -> None:
    model = window.table.model()
    assert model is not None
    index = model.index(source_row, 1)
    if not index.isValid():
        index = model.index(source_row, 0)
    assert index.isValid()
    window.table.setCurrentIndex(index)


def test_measure_display_menu_updates_rounding_and_normalization(
    measure_window: FrameLabWindow,
) -> None:
    measure_window.measure_normalize_action.setChecked(True)
    assert measure_window.metrics_state.normalize_intensity_values

    measure_window._measure_rounding_actions["std"].trigger()
    assert measure_window.metrics_state.rounding_mode == "std"
    assert "normalized" in measure_window.measure_display_button.toolTip()
    assert "Std rounding" in measure_window.measure_display_button.toolTip()


def test_measure_help_visibility_respects_preview_flags(
    measure_window: FrameLabWindow,
) -> None:
    measure_window.show_image_preview = True
    measure_window.show_histogram_preview = True
    measure_window._set_measure_help_visibility(False)
    assert measure_window.preview_help_label.isHidden()

    measure_window._set_measure_help_visibility(True)
    assert not measure_window.preview_help_label.isHidden()

    measure_window.show_histogram_preview = False
    measure_window._set_measure_help_visibility(True)
    assert not measure_window.preview_help_label.isHidden()


def test_measure_splitter_state_round_trip(measure_window: FrameLabWindow) -> None:
    splitter = measure_window.measure_main_splitter
    splitter.setSizes([720, 360])
    stored_sizes = splitter.sizes()

    measure_window._persist_splitter_state("measure.main_splitter", splitter)

    assert (
        measure_window.ui_state_snapshot.splitter_sizes["measure.main_splitter"]
        == stored_sizes
    )

    measure_window.ui_state_snapshot.splitter_sizes["measure.main_splitter"] = [200, 800]
    splitter.setSizes([600, 400])
    measure_window._restore_splitter_state("measure.main_splitter", splitter)
    restored_sizes = splitter.sizes()

    assert len(restored_sizes) == 2
    assert restored_sizes[1] > restored_sizes[0]


def test_low_signal_threshold_updates_summary_and_row_highlighting(
    tmp_path: Path,
    measure_window: FrameLabWindow,
    wait_for_dataset_load,
) -> None:
    dataset_root = _write_measure_dataset(tmp_path)
    dark_path = str((dataset_root / "a_dark.tiff").resolve())
    bright_path = str((dataset_root / "b_bright.tiff").resolve())
    measure_window.folder_edit.setText(str(dataset_root))
    measure_window.load_folder()
    wait_for_dataset_load(measure_window)

    assert _measure_summary_values(measure_window).get("Low Signal") == "Inactive"

    measure_window.low_signal_spin.setValue(10)
    measure_window._apply_low_signal_threshold_update()
    dark_index = measure_window.dataset_state.paths.index(dark_path)
    bright_index = measure_window.dataset_state.paths.index(bright_path)

    summary_values = _measure_summary_values(measure_window)
    assert summary_values.get("Low Signal") == "1"
    assert (
        measure_window.table_model.data(
            measure_window.table_model.index(dark_index, 0),
            QtCore.Qt.BackgroundRole,
        )
        == measure_window.table_model.LOW_SIGNAL_ROW_BRUSH
    )
    assert (
        measure_window.table_model.data(
            measure_window.table_model.index(bright_index, 0),
            QtCore.Qt.BackgroundRole,
        )
        is None
    )


def test_scan_only_measure_table_keeps_static_metrics_available(
    tmp_path: Path,
    measure_window: FrameLabWindow,
    wait_for_dataset_load,
) -> None:
    dataset_root = _write_measure_dataset(tmp_path)
    measure_window.folder_edit.setText(str(dataset_root))
    measure_window.load_folder()
    wait_for_dataset_load(measure_window)

    assert measure_window.metrics_state.scan_metric_preset == ScanMetricPreset.MINIMAL
    max_column = measure_window.MEASURE_COLUMN_INDEX["max_pixel"]
    min_column = measure_window.MEASURE_COLUMN_INDEX["min_non_zero"]
    saturation_column = measure_window.MEASURE_COLUMN_INDEX["sat_count"]

    assert measure_window.table_model.data(
        measure_window.table_model.index(0, max_column),
    ) == "4"
    assert measure_window.table_model.data(
        measure_window.table_model.index(0, min_column),
    ) == "4"
    assert measure_window.table_model.data(
        measure_window.table_model.index(0, saturation_column),
    ) == "-"
    assert (
        _measure_summary_values(measure_window).get("Saturated Images")
        == "Not computed"
    )


def test_measure_control_changes_are_pending_until_apply(
    tmp_path: Path,
    measure_window: FrameLabWindow,
    monkeypatch,
    wait_for_dataset_load,
) -> None:
    dataset_root = _write_measure_dataset(tmp_path)
    dynamic_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        measure_window,
        "_start_dynamic_stats_job",
        lambda **kwargs: dynamic_calls.append(dict(kwargs)),
    )

    measure_window.folder_edit.setText(str(dataset_root))
    measure_window.load_folder()
    wait_for_dataset_load(measure_window)

    measure_window.threshold_spin.setValue(100)
    measure_window.low_signal_spin.setValue(8)
    measure_window.avg_mode_combo.setCurrentIndex(
        measure_window.avg_mode_combo.findData("topk"),
    )
    measure_window.avg_spin.setValue(7)

    assert dynamic_calls == []
    assert measure_window.metrics_state.threshold_value == pytest.approx(65520.0)
    assert measure_window.metrics_state.low_signal_threshold_value == pytest.approx(0.0)
    assert measure_window.metrics_state.avg_count_value == 32
    assert measure_window.metrics_state.pending_threshold_value == pytest.approx(100.0)
    assert (
        measure_window.metrics_state.pending_low_signal_threshold_value
        == pytest.approx(8.0)
    )
    assert measure_window.metrics_state.pending_avg_count_value == 7
    assert (
        measure_window.metrics_state.metric_family_state(MetricFamily.SATURATION)
        == MetricFamilyState.PENDING_INPUTS
    )
    assert (
        measure_window.metrics_state.metric_family_state(MetricFamily.LOW_SIGNAL)
        == MetricFamilyState.PENDING_INPUTS
    )
    assert (
        measure_window.metrics_state.metric_family_state(MetricFamily.TOPK)
        == MetricFamilyState.PENDING_INPUTS
    )

    measure_window._apply_topk_update()

    assert dynamic_calls == [
        {
            "update_kind": "full",
            "refresh_analysis": True,
            "requested_families": (MetricFamily.TOPK,),
            "reason": RefreshReason.APPLY_TOPK,
        },
    ]
    assert measure_window.metrics_state.avg_count_value == 7
    assert measure_window.metrics_state.threshold_value == pytest.approx(65520.0)
    assert measure_window.metrics_state.low_signal_threshold_value == pytest.approx(0.0)


def test_background_invalidation_keeps_static_scan_ready(
    tmp_path: Path,
    measure_window: FrameLabWindow,
    wait_for_dataset_load,
) -> None:
    dataset_root = _write_measure_dataset(tmp_path)
    measure_window.folder_edit.setText(str(dataset_root))
    measure_window.load_folder()
    wait_for_dataset_load(measure_window)

    metrics = measure_window.metrics_state
    metrics.set_metric_family_state(MetricFamily.STATIC_SCAN, MetricFamilyState.READY)
    metrics.set_metric_family_state(MetricFamily.TOPK, MetricFamilyState.READY)
    metrics.set_metric_family_state(
        MetricFamily.BACKGROUND_APPLIED,
        MetricFamilyState.READY,
    )
    metrics.set_metric_family_state(
        MetricFamily.SATURATION,
        MetricFamilyState.NOT_REQUESTED,
    )

    measure_window._invalidate_background_cache(reason=RefreshReason.BACKGROUND_CHANGE)

    assert metrics.metric_family_state(MetricFamily.STATIC_SCAN) == MetricFamilyState.READY
    assert metrics.metric_family_state(MetricFamily.TOPK) == MetricFamilyState.STALE
    assert (
        metrics.metric_family_state(MetricFamily.BACKGROUND_APPLIED)
        == MetricFamilyState.STALE
    )
    assert (
        metrics.metric_family_state(MetricFamily.SATURATION)
        == MetricFamilyState.NOT_REQUESTED
    )


def test_threshold_apply_updates_runtime_task_state(
    tmp_path: Path,
    measure_window: FrameLabWindow,
    wait_for_dataset_load,
    wait_until,
) -> None:
    dataset_root = _write_measure_dataset(tmp_path)
    measure_window.folder_edit.setText(str(dataset_root))
    measure_window.load_folder()
    wait_for_dataset_load(measure_window)

    measure_window.threshold_spin.setValue(100)
    measure_window._apply_threshold_update()

    wait_until(lambda: not measure_window.metrics_state.is_stats_running, timeout_ms=5000)
    latest = measure_window.runtime_tasks.latest_task()
    assert latest is not None
    assert latest.task_id.startswith("dynamic_stats:")
    assert latest.label == "Threshold update"
    assert latest.state == RuntimeTaskState.SUCCEEDED


def test_roi_apply_updates_runtime_task_state(
    tmp_path: Path,
    measure_window: FrameLabWindow,
    wait_for_dataset_load,
    wait_until,
) -> None:
    dataset_root = _write_measure_dataset(tmp_path)
    measure_window.folder_edit.setText(str(dataset_root))
    measure_window.load_folder()
    wait_for_dataset_load(measure_window)
    measure_window.avg_mode_combo.setCurrentIndex(
        measure_window.avg_mode_combo.findData("roi"),
    )
    measure_window.metrics_state.roi_rect = (0, 0, 2, 2)
    measure_window._start_roi_apply_job()

    wait_until(lambda: not measure_window.metrics_state.is_roi_applying, timeout_ms=5000)
    latest = measure_window.runtime_tasks.latest_task()
    assert latest is not None
    assert latest.task_id.startswith("roi_apply:")
    assert latest.label == "ROI apply"
    assert latest.state == RuntimeTaskState.SUCCEEDED


def test_low_signal_threshold_does_not_add_preview_pixel_overlay(
    tmp_path: Path,
    measure_window: FrameLabWindow,
    wait_for_dataset_load,
) -> None:
    dataset_root = _write_measure_dataset(tmp_path)
    dark_path = str((dataset_root / "a_dark.tiff").resolve())
    measure_window.folder_edit.setText(str(dataset_root))
    measure_window.load_folder()
    wait_for_dataset_load(measure_window)
    measure_window.threshold_spin.setValue(100)
    measure_window._apply_threshold_update()
    measure_window.low_signal_spin.setValue(10)
    measure_window._apply_low_signal_threshold_update()
    dark_index = measure_window.dataset_state.paths.index(dark_path)
    measure_window.dataset_state.set_selected_index(
        dark_index,
        path_count=measure_window.dataset_state.path_count(),
    )
    measure_window._set_table_current_source_row(dark_index)
    measure_window._display_image(dark_index)

    rgb = measure_window.image_preview._rgb_buffer

    assert rgb is not None
    assert not np.any(
        (rgb[..., 0] == 255)
        & (rgb[..., 1] == 0)
        & (rgb[..., 2] == 0)
    )


def test_elapsed_time_column_shows_only_for_timestamped_scopes(
    tmp_path: Path,
    measure_window: FrameLabWindow,
    wait_for_dataset_load,
) -> None:
    elapsed_column = measure_window.MEASURE_COLUMN_INDEX["elapsed_time_s"]
    plain_root = _write_measure_dataset(tmp_path)
    measure_window.folder_edit.setText(str(plain_root))
    measure_window.load_folder()
    wait_for_dataset_load(measure_window)

    assert measure_window.table.isColumnHidden(elapsed_column)

    timestamped_root = _write_timestamped_measure_dataset(tmp_path)
    measure_window.folder_edit.setText(str(timestamped_root))
    measure_window.load_folder()
    wait_for_dataset_load(measure_window)

    assert not measure_window.table.isColumnHidden(elapsed_column)
    assert (
        measure_window.table_model.headerData(
            elapsed_column,
            QtCore.Qt.Horizontal,
            QtCore.Qt.UserRole,
        )
        == "elapsed time [s]"
    )
    assert (
        measure_window.table_model.data(
            measure_window.table_model.index(0, elapsed_column),
        )
        == "0.000"
    )
    assert (
        measure_window.table_model.data(
            measure_window.table_model.index(1, elapsed_column),
        )
        == "1.250"
    )


def test_roi_selection_updates_roi_max_for_selected_image_immediately(
    tmp_path: Path,
    measure_window: FrameLabWindow,
    wait_for_dataset_load,
) -> None:
    dataset_root = _write_measure_dataset(tmp_path)
    dark_path = str((dataset_root / "a_dark.tiff").resolve())
    measure_window.folder_edit.setText(str(dataset_root))
    measure_window.load_folder()
    wait_for_dataset_load(measure_window)

    dark_index = measure_window.dataset_state.paths.index(dark_path)
    measure_window.dataset_state.set_selected_index(
        dark_index,
        path_count=measure_window.dataset_state.path_count(),
    )
    measure_window._set_table_current_source_row(dark_index)

    assert measure_window._apply_roi_rect_to_current_dataset(
        (0, 0, 2, 2),
        status_message=None,
    )

    roi_max_column = measure_window.MEASURE_COLUMN_INDEX["roi_max"]
    roi_sum_column = measure_window.MEASURE_COLUMN_INDEX["roi_sum"]
    assert float(measure_window.metrics_state.roi_maxs[dark_index]) == pytest.approx(4.0)
    assert float(measure_window.metrics_state.roi_sums[dark_index]) == pytest.approx(16.0)
    assert measure_window.table_model.data(
        measure_window.table_model.index(dark_index, roi_max_column),
    ) == "4"
    assert measure_window.table_model.data(
        measure_window.table_model.index(dark_index, roi_sum_column),
    ) == "16"


def test_roi_columns_show_in_roi_average_modes(
    tmp_path: Path,
    measure_window: FrameLabWindow,
    wait_for_dataset_load,
) -> None:
    dataset_root = _write_measure_dataset(tmp_path)
    roi_max_column = measure_window.MEASURE_COLUMN_INDEX["roi_max"]
    roi_sum_column = measure_window.MEASURE_COLUMN_INDEX["roi_sum"]
    measure_window.folder_edit.setText(str(dataset_root))
    measure_window.load_folder()
    wait_for_dataset_load(measure_window)

    assert measure_window.table.isColumnHidden(roi_max_column)
    assert measure_window.table.isColumnHidden(roi_sum_column)

    measure_window.avg_mode_combo.setCurrentIndex(
        measure_window.avg_mode_combo.findData("topk"),
    )
    assert measure_window.table.isColumnHidden(roi_max_column)
    assert measure_window.table.isColumnHidden(roi_sum_column)

    measure_window.avg_mode_combo.setCurrentIndex(
        measure_window.avg_mode_combo.findData("roi"),
    )
    assert not measure_window.table.isColumnHidden(roi_max_column)
    assert not measure_window.table.isColumnHidden(roi_sum_column)

    measure_window.avg_mode_combo.setCurrentIndex(
        measure_window.avg_mode_combo.findData("roi_topk"),
    )
    assert not measure_window.table.isColumnHidden(roi_max_column)
    assert not measure_window.table.isColumnHidden(roi_sum_column)
    assert not measure_window.topk_controls_widget.isHidden()
    assert not measure_window.roi_controls_widget.isHidden()


def test_compact_measure_header_mirrors_low_signal_and_saturation_status(
    tmp_path: Path,
    measure_window: FrameLabWindow,
    qapp,
    wait_for_dataset_load,
) -> None:
    dataset_root = _write_measure_dataset(tmp_path)
    measure_window.folder_edit.setText(str(dataset_root))
    measure_window.load_folder()
    wait_for_dataset_load(measure_window)
    measure_window.threshold_spin.setValue(10)
    measure_window._apply_threshold_update()
    measure_window.low_signal_spin.setValue(5)
    measure_window._apply_low_signal_threshold_update()
    compact_prefs = replace(
        measure_window.ui_preferences,
        density_mode=DensityMode.COMPACT,
    )
    measure_window._apply_ui_preferences(compact_prefs, persist=False)
    measure_window._apply_measure_page_visibility_policy(
        VisibilityPolicy(
            show_subtitles=True,
            show_summary_strip=False,
            collapse_data_advanced_row=False,
            collapse_analysis_plugin_controls=False,
            show_measure_help_labels=False,
            show_plot_help_labels=False,
        ),
    )
    measure_window._density_refresh_ready = False
    if measure_window._density_refresh_timer is not None:
        measure_window._density_refresh_timer.stop()

    for _ in range(500):
        qapp.processEvents()
        measure_window._measure_summary_strip.set_collapsed(True)
        measure_window._measure_header.set_compact_chip_mode(True)
        measure_window._refresh_measure_header_state()
        if "Saturated 1" in _measure_header_chip_levels(measure_window):
            break
        QtTest.QTest.qWait(10)

    header_levels = _measure_header_chip_levels(measure_window)

    assert measure_window._measure_summary_strip.is_collapsed()
    assert header_levels["Saturated 1"] == "error"
    assert header_levels["Low Signal 1"] == "warning"


def test_measure_header_shows_backend_badge_from_shared_snapshot(
    measure_window: FrameLabWindow,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        inspect_page_module.native_backend,
        "backend_status_snapshot",
        lambda: {
            "native_available": True,
            "active_backend": "python",
            "native_latched_off": True,
            "last_fallback_reason": "compute_histogram failed: boom",
        },
    )

    measure_window._refresh_measure_header_state()

    header_levels = _measure_header_chip_levels(measure_window)
    summary_values = _measure_summary_values(measure_window)

    assert header_levels["Backend Python"] == "warning"
    assert summary_values["Backend"] == "Python"


def test_measure_selection_debounces_preview_refresh_but_updates_selection_immediately(
    tmp_path: Path,
    measure_window: FrameLabWindow,
    monkeypatch,
    wait_for_dataset_load,
    wait_until,
) -> None:
    dataset_root = _write_measure_dataset(tmp_path)
    measure_window.folder_edit.setText(str(dataset_root))
    measure_window.load_folder()
    wait_for_dataset_load(measure_window)

    renders: list[tuple[int, bool]] = []
    monkeypatch.setattr(
        measure_window,
        "_render_display_image",
        lambda idx, *, exact_preview, preview_generation=None: renders.append(
            (int(idx), bool(exact_preview)),
        ),
    )

    _set_measure_current_row(measure_window, 1)

    assert measure_window.dataset_state.selected_index == 1
    assert renders == []

    wait_until(lambda: renders == [(1, True)], timeout_ms=1000)


def test_measure_selection_burst_coalesces_to_latest_preview_row(
    tmp_path: Path,
    measure_window: FrameLabWindow,
    monkeypatch,
    wait_for_dataset_load,
    wait_until,
) -> None:
    dataset_root = _write_measure_dataset(tmp_path)
    measure_window.folder_edit.setText(str(dataset_root))
    measure_window.load_folder()
    wait_for_dataset_load(measure_window)

    renders: list[tuple[int, bool]] = []
    monkeypatch.setattr(
        measure_window,
        "_render_display_image",
        lambda idx, *, exact_preview, preview_generation=None: renders.append(
            (int(idx), bool(exact_preview)),
        ),
    )

    _set_measure_current_row(measure_window, 1)
    _set_measure_current_row(measure_window, 0)
    _set_measure_current_row(measure_window, 1)

    wait_until(lambda: renders == [(1, True)], timeout_ms=1000)
    assert measure_window.dataset_state.selected_index == 1


def test_measure_settled_preview_discards_stale_selection_results(
    tmp_path: Path,
    measure_window: FrameLabWindow,
    monkeypatch,
    wait_for_dataset_load,
    wait_until,
) -> None:
    dataset_root = _write_measure_dataset(tmp_path)
    measure_window.folder_edit.setText(str(dataset_root))
    measure_window.load_folder()
    wait_for_dataset_load(measure_window)

    renders: list[tuple[int, bool]] = []
    monkeypatch.setattr(
        measure_window,
        "_render_display_image",
        lambda idx, *, exact_preview, preview_generation=None: renders.append(
            (int(idx), bool(exact_preview)),
        ),
    )

    _set_measure_current_row(measure_window, 1)
    _set_measure_current_row(measure_window, 0)
    wait_until(lambda: renders == [(0, True)], timeout_ms=1000)


def test_measure_histogram_waits_until_histogram_tab_is_active(
    tmp_path: Path,
    measure_window: FrameLabWindow,
    monkeypatch,
    wait_for_dataset_load,
    wait_until,
) -> None:
    dataset_root = _write_measure_dataset(tmp_path)
    measure_window.folder_edit.setText(str(dataset_root))
    measure_window.load_folder()
    wait_for_dataset_load(measure_window)
    measure_window.show_histogram_preview = True
    measure_window._on_preview_visibility_changed()
    measure_window.preview_pages.setCurrentIndex(0)
    QtTest.QTest.qWait(180)

    histogram_calls: list[bool] = []
    monkeypatch.setattr(
        measure_window.histogram_widget,
        "set_image",
        lambda *args, **kwargs: histogram_calls.append(True),
    )

    _set_measure_current_row(measure_window, 1)
    QtTest.QTest.qWait(180)
    assert histogram_calls == []

    measure_window.preview_pages.setCurrentIndex(1)
    wait_until(lambda: len(histogram_calls) == 1, timeout_ms=1000)

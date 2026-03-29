"""Integration tests for Measure-page contextual chrome."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PySide6 import QtCore, QtTest, QtWidgets as qtw
from tifffile import imwrite

import framelab.main_window.inspect_page as inspect_page_module
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
    assert float(measure_window.metrics_state.roi_maxs[dark_index]) == pytest.approx(4.0)
    assert measure_window.table_model.data(
        measure_window.table_model.index(dark_index, roi_max_column),
    ) == "4"


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

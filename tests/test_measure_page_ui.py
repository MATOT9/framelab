"""Integration tests for Measure-page contextual chrome."""

from __future__ import annotations

import pytest

from framelab.window import FrameLabWindow


pytestmark = [pytest.mark.ui, pytest.mark.core]


@pytest.fixture
def measure_window(framelab_window_factory) -> FrameLabWindow:
    window = framelab_window_factory(enabled_plugin_ids=())
    window.ui_state_snapshot.splitter_sizes.clear()
    return window


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

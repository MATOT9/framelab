"""Integration tests for density-driven main window layout metrics."""

from __future__ import annotations

from dataclasses import replace

import pytest

from framelab.ui_settings import DensityMode
from framelab.window import FrameLabWindow


pytestmark = [pytest.mark.ui, pytest.mark.core]


@pytest.fixture
def density_window(framelab_window_factory) -> FrameLabWindow:
    return framelab_window_factory()


def test_compact_density_updates_root_and_page_layouts(
    density_window: FrameLabWindow,
) -> None:
    compact_prefs = replace(
        density_window.ui_preferences,
        density_mode=DensityMode.COMPACT,
    )
    density_window._apply_ui_preferences(compact_prefs, persist=False)
    tokens = density_window._active_density_tokens

    root_layout = density_window.centralWidget().layout()
    assert root_layout.contentsMargins().left() == tokens.root_margin
    assert root_layout.spacing() == tokens.page_spacing
    assert density_window._data_page_layout.spacing() == tokens.page_spacing
    assert density_window._measure_page_layout.spacing() == tokens.page_spacing
    assert density_window._analysis_page_layout.spacing() == tokens.page_spacing
    assert (
        density_window._data_command_layout.contentsMargins().left()
        == tokens.command_bar_margin_h
    )
    assert (
        density_window._measure_metrics_layout.contentsMargins().left()
        == tokens.command_bar_margin_h
    )
    assert (
        density_window._analysis_selector_layout.contentsMargins().left()
        == tokens.panel_margin_h
    )
    assert density_window._analysis_side_rail_layout.spacing() == tokens.panel_spacing


def test_schedule_density_refresh_is_safe_before_bootstrap() -> None:
    class _FakeTimer:
        def __init__(self) -> None:
            self.starts = 0

        def start(self) -> None:
            self.starts += 1

    class _StubWindow:
        pass

    stub = _StubWindow()
    stub._density_refresh_ready = False
    stub._density_refresh_timer = _FakeTimer()

    FrameLabWindow._schedule_density_refresh(stub)
    assert stub._density_refresh_timer.starts == 0

    stub._density_refresh_ready = True
    FrameLabWindow._schedule_density_refresh(stub)
    assert stub._density_refresh_timer.starts == 1

"""Integration tests for Analysis-page disclosure and hint visibility."""

from __future__ import annotations

from dataclasses import replace

import pytest
from PySide6 import QtWidgets as qtw

from framelab.ui_settings import DensityMode
from framelab.window import FrameLabWindow


pytestmark = [pytest.mark.ui, pytest.mark.analysis]


@pytest.fixture
def analysis_window(framelab_window_factory, process_events) -> FrameLabWindow:
    window = framelab_window_factory(
        enabled_plugin_ids=("iris_gain_vs_exposure",),
    )
    window.ui_state_snapshot.panel_states.clear()
    window.ui_state_snapshot.splitter_sizes.clear()
    window._session_panel_overrides.clear()
    if hasattr(window, "_metadata_inspector_dock"):
        window._metadata_inspector_dock.hide()
    process_events()
    return window


def _show_analysis_page(window: FrameLabWindow, process_events) -> None:
    analysis_index = window.workflow_tabs.indexOf(window.analysis_page)
    window.workflow_tabs.setCurrentIndex(analysis_index)
    window.resize(1400, 900)
    window.show()
    process_events()
    window._restore_or_default_analysis_main_splitter()
    plugin = window._current_analysis_plugin()
    if plugin is not None:
        window._restore_active_analysis_workspace_splitter(plugin)
    process_events()


def test_analysis_host_splits_selector_controls_and_workspace(
    analysis_window: FrameLabWindow,
    process_events,
) -> None:
    _show_analysis_page(analysis_window, process_events)
    plugin = analysis_window._current_analysis_plugin()

    assert plugin is not None
    assert analysis_window.analysis_main_splitter.count() == 2
    assert analysis_window.analysis_controls_stack.currentWidget() is plugin._controls_panel
    assert analysis_window.analysis_workspace_stack.currentWidget() is plugin._workspace_widget
    assert analysis_window.analysis_stack is analysis_window.analysis_workspace_stack
    assert plugin.workspace_splitter() is plugin._workspace_splitter
    assert isinstance(plugin._controls_panel.layout(), qtw.QVBoxLayout)
    main_sizes = analysis_window.analysis_main_splitter.sizes()
    workspace_sizes = plugin.workspace_splitter().sizes()
    assert main_sizes[1] > main_sizes[0]
    assert workspace_sizes[1] >= workspace_sizes[0]


def test_analysis_plugin_controls_toggle_updates_session_override(
    analysis_window: FrameLabWindow,
    process_events,
) -> None:
    _show_analysis_page(analysis_window, process_events)
    plugin = analysis_window._current_analysis_plugin()

    assert plugin is not None
    assert analysis_window.analysis_controls_stack.isHidden()
    assert not analysis_window.analysis_plugin_controls_toggle.isChecked()

    analysis_window.analysis_plugin_controls_toggle.setChecked(True)
    process_events()

    assert not analysis_window.analysis_controls_stack.isHidden()
    assert analysis_window.analysis_plugin_controls_toggle.isChecked()
    assert analysis_window._session_panel_overrides["analysis.plugin_controls"]
    assert analysis_window.ui_state_snapshot.panel_states["analysis.plugin_controls"]


def test_analysis_plugin_controls_omit_group_heading_labels(
    analysis_window: FrameLabWindow,
    process_events,
) -> None:
    _show_analysis_page(analysis_window, process_events)
    plugin = analysis_window._current_analysis_plugin()

    assert plugin is not None
    labels = [
        label.text()
        for label in plugin._controls_panel.findChildren(qtw.QLabel)
    ]

    assert "Axes" not in labels
    assert "Trend & Display" not in labels


def test_analysis_main_splitter_persists_user_resize(
    analysis_window: FrameLabWindow,
    process_events,
) -> None:
    _show_analysis_page(analysis_window, process_events)
    splitter = analysis_window.analysis_main_splitter
    initial_sizes = splitter.sizes()

    splitter.moveSplitter(380, 1)
    process_events()
    stored_sizes = analysis_window.ui_state_snapshot.splitter_sizes[
        analysis_window._analysis_main_splitter_key()
    ]

    assert len(stored_sizes) == 2
    assert stored_sizes != initial_sizes


def test_plugin_workspace_splitter_restore_uses_plugin_key(
    analysis_window: FrameLabWindow,
    process_events,
) -> None:
    _show_analysis_page(analysis_window, process_events)
    plugin = analysis_window._current_analysis_plugin()

    assert plugin is not None
    splitter = plugin.workspace_splitter()
    assert splitter is not None
    key = analysis_window._analysis_workspace_splitter_key(plugin)

    splitter.moveSplitter(100, 1)
    process_events()
    before_restore = splitter.sizes()

    analysis_window.ui_state_snapshot.splitter_sizes[key] = [280, 220]
    analysis_window._restore_active_analysis_workspace_splitter(plugin)
    process_events()
    restored_sizes = splitter.sizes()

    assert analysis_window.ui_state_snapshot.splitter_sizes[key] == [280, 220]
    assert len(restored_sizes) == 2
    assert restored_sizes != before_restore
    assert not analysis_window._analysis_workspace_split_is_pathological(restored_sizes)


def test_pathological_saved_workspace_split_is_rebalanced(
    analysis_window: FrameLabWindow,
    process_events,
) -> None:
    _show_analysis_page(analysis_window, process_events)
    plugin = analysis_window._current_analysis_plugin()

    assert plugin is not None
    splitter = plugin.workspace_splitter()
    assert splitter is not None
    key = analysis_window._analysis_workspace_splitter_key(plugin)

    analysis_window.ui_state_snapshot.splitter_sizes[key] = [921, 154]
    analysis_window._restore_active_analysis_workspace_splitter(plugin)
    process_events()
    restored_sizes = splitter.sizes()

    assert len(restored_sizes) == 2
    assert abs(restored_sizes[0] - restored_sizes[1]) <= 1


def test_analysis_plot_hint_visibility_follows_density_policy(
    analysis_window: FrameLabWindow,
    process_events,
) -> None:
    _show_analysis_page(analysis_window, process_events)
    plugin = analysis_window._current_analysis_plugin()

    assert plugin is not None
    comfortable_prefs = replace(
        analysis_window.ui_preferences,
        density_mode=DensityMode.COMFORTABLE,
    )
    analysis_window._apply_ui_preferences(comfortable_prefs, persist=False)
    assert not plugin._plot_hint_label.isHidden()

    compact_prefs = replace(
        analysis_window.ui_preferences,
        density_mode=DensityMode.COMPACT,
    )
    analysis_window._apply_ui_preferences(compact_prefs, persist=False)
    assert plugin._plot_hint_label.isHidden()
    analysis_window._apply_ui_preferences(comfortable_prefs, persist=False)
    assert not plugin._plot_hint_label.isHidden()


def test_analysis_context_stays_dirty_until_analysis_page_is_visible(
    analysis_window: FrameLabWindow,
    process_events,
    monkeypatch,
) -> None:
    plugin = analysis_window._current_analysis_plugin()

    assert plugin is not None
    analysis_window.workflow_tabs.setCurrentIndex(0)
    process_events()

    calls: list[object] = []
    original = plugin.on_context_changed

    def _wrapped(context) -> None:
        calls.append(context)
        original(context)

    monkeypatch.setattr(plugin, "on_context_changed", _wrapped)

    analysis_window._on_normalize_intensity_toggled(True)
    process_events()

    assert calls == []
    assert analysis_window._analysis_context_dirty

    _show_analysis_page(analysis_window, process_events)

    assert len(calls) == 1
    assert not analysis_window._analysis_context_dirty
    assert plugin._context is not None


def test_visible_analysis_page_coalesces_multiple_context_invalidations(
    analysis_window: FrameLabWindow,
    process_events,
    monkeypatch,
) -> None:
    _show_analysis_page(analysis_window, process_events)
    plugin = analysis_window._current_analysis_plugin()

    assert plugin is not None
    calls: list[object] = []
    original = plugin.on_context_changed

    def _wrapped(context) -> None:
        calls.append(context)
        original(context)

    monkeypatch.setattr(plugin, "on_context_changed", _wrapped)

    analysis_window._on_normalize_intensity_toggled(True)
    analysis_window._set_rounding_mode("std")
    process_events()

    assert len(calls) == 1
    assert not analysis_window._analysis_context_dirty

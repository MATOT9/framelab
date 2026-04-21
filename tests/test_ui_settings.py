"""Tests for persistent UI preferences without last-session UI cache restore."""

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path

import pytest

from framelab.ui_settings import (
    DensityMode,
    RecentWorkflowEntry,
    RecentWorkspaceDocumentEntry,
    UiPreferences,
    UiStateSnapshot,
    UiStateStore,
)


pytestmark = [pytest.mark.fast, pytest.mark.core]


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return tmp_path / "preferences.ini"


@pytest.fixture
def store(config_path: Path) -> UiStateStore:
    return UiStateStore(config_path)


def test_load_returns_default_preferences_and_no_cached_ui_state(
    store: UiStateStore,
) -> None:
    snapshot = store.load()

    assert snapshot.preferences.theme_mode == "dark"
    assert snapshot.preferences.density_mode == DensityMode.AUTO
    assert snapshot.preferences.show_page_subtitles
    assert snapshot.preferences.show_image_preview
    assert not snapshot.preferences.show_histogram_preview
    assert snapshot.preferences.restore_panel_states
    assert snapshot.preferences.restore_last_tab
    assert snapshot.preferences.scan_worker_count_override is None
    assert snapshot.preferences.use_mmap_for_raw
    assert snapshot.preferences.enable_raw_simd
    assert snapshot.panel_states == {}
    assert snapshot.splitter_sizes == {}
    assert snapshot.last_tab_index is None
    assert snapshot.last_analysis_plugin_id is None
    assert snapshot.workflow_workspace_root is None
    assert snapshot.workflow_profile_id is None
    assert snapshot.workflow_anchor_type_id is None
    assert snapshot.workflow_active_node_id is None
    assert snapshot.recent_workflows == []
    assert snapshot.recent_workspace_documents == []


def test_save_and_reload_round_trips_preferences_only(
    store: UiStateStore,
    config_path: Path,
) -> None:
    snapshot = UiStateSnapshot(
        preferences=UiPreferences(
            theme_mode="light",
            density_mode=DensityMode.COMPACT,
            show_page_subtitles=False,
            show_image_preview=False,
            show_histogram_preview=True,
            restore_panel_states=False,
            restore_last_tab=False,
            collapse_analysis_plugin_controls_by_default=False,
            collapse_data_advanced_row_by_default=False,
            collapse_summary_strips_by_default=True,
            scan_worker_count_override=5,
            use_mmap_for_raw=False,
            enable_raw_simd=False,
        ),
        panel_states={
            "analysis.plugin_controls": False,
            "data.advanced_row": True,
        },
        splitter_sizes={"measure.main_splitter": [640, 360]},
        last_tab_index=2,
        last_analysis_plugin_id="iris_gain",
        workflow_workspace_root="/tmp/workspaces/calibration",
        workflow_profile_id="calibration",
        workflow_anchor_type_id="session",
        workflow_active_node_id="calibration:session:cam-a/campaign-1/session-01",
        recent_workflows=[
            RecentWorkflowEntry(
                workspace_root="/tmp/workspaces/calibration",
                profile_id="calibration",
                anchor_type_id="root",
                active_node_id="calibration:root",
            ),
        ],
        recent_workspace_documents=[
            RecentWorkspaceDocumentEntry(
                path="/tmp/workspaces/calibration/session.framelab",
            ),
        ],
    )

    store.save(snapshot)
    reloaded = store.load()

    assert reloaded.preferences.theme_mode == "light"
    assert reloaded.preferences.density_mode == DensityMode.COMPACT
    assert not reloaded.preferences.show_page_subtitles
    assert not reloaded.preferences.show_image_preview
    assert reloaded.preferences.show_histogram_preview
    assert not reloaded.preferences.restore_panel_states
    assert not reloaded.preferences.restore_last_tab
    assert not reloaded.preferences.collapse_analysis_plugin_controls_by_default
    assert not reloaded.preferences.collapse_data_advanced_row_by_default
    assert reloaded.preferences.collapse_summary_strips_by_default
    assert reloaded.preferences.scan_worker_count_override == 5
    assert not reloaded.preferences.use_mmap_for_raw
    assert not reloaded.preferences.enable_raw_simd
    assert reloaded.panel_states == {}
    assert reloaded.splitter_sizes == {}
    assert reloaded.last_tab_index is None
    assert reloaded.last_analysis_plugin_id is None
    assert reloaded.workflow_workspace_root is None
    assert reloaded.workflow_profile_id is None
    assert reloaded.workflow_anchor_type_id is None
    assert reloaded.workflow_active_node_id is None
    assert reloaded.recent_workflows == []
    assert reloaded.recent_workspace_documents == [
        RecentWorkspaceDocumentEntry(
            path="/tmp/workspaces/calibration/session.framelab",
        ),
    ]

    config = ConfigParser()
    config.read(config_path, encoding="utf-8")
    assert config.get("appearance", "theme") == "light"
    assert not config.has_section("panels")
    assert not config.has_section("splitters")
    assert config.has_section("recent_workspace_documents")
    assert not config.has_section("recent_workflows")
    assert not config.has_option("workspace", "last_workflow_tab")
    assert not config.has_option("workspace", "workflow_root")
    assert not config.has_option("analysis_page", "last_plugin_id")


def test_invalid_values_fall_back_to_defaults_and_ignore_cached_state(
    store: UiStateStore,
    config_path: Path,
) -> None:
    config_path.write_text(
        "\n".join(
            [
                "[appearance]",
                "theme = neon",
                "density_mode = compressed",
                "show_page_subtitles = maybe",
                "[workspace]",
                "show_image_preview = absolutely",
                "show_histogram_preview = yes",
                "restore_panel_states = perhaps",
                "restore_last_tab = no",
                "last_workflow_tab = 2",
                "workflow_root = /tmp/workspace",
                "workflow_profile_id = calibration",
                "[data_page]",
                "collapse_advanced_row_by_default = no",
                "[analysis_page]",
                "collapse_plugin_controls_by_default = invalid",
                "last_plugin_id = iris_gain",
                "[panels]",
                "analysis.plugin_controls = false",
                "[splitters]",
                "measure.main_splitter = 300, 700",
            ],
        )
        + "\n",
        encoding="utf-8",
    )

    snapshot = store.load()

    assert snapshot.preferences.theme_mode == "dark"
    assert snapshot.preferences.density_mode == DensityMode.AUTO
    assert snapshot.preferences.show_page_subtitles
    assert snapshot.preferences.show_image_preview
    assert snapshot.preferences.show_histogram_preview
    assert snapshot.preferences.restore_panel_states
    assert not snapshot.preferences.restore_last_tab
    assert not snapshot.preferences.collapse_data_advanced_row_by_default
    assert snapshot.preferences.collapse_analysis_plugin_controls_by_default
    assert snapshot.preferences.scan_worker_count_override is None
    assert snapshot.preferences.use_mmap_for_raw
    assert snapshot.preferences.enable_raw_simd
    assert snapshot.panel_states == {}
    assert snapshot.splitter_sizes == {}
    assert snapshot.last_tab_index is None
    assert snapshot.last_analysis_plugin_id is None
    assert snapshot.workflow_workspace_root is None
    assert snapshot.workflow_profile_id is None
    assert snapshot.workflow_anchor_type_id is None
    assert snapshot.workflow_active_node_id is None
    assert snapshot.recent_workflows == []
    assert snapshot.recent_workspace_documents == []


def test_legacy_cached_ui_state_sections_are_ignored(
    store: UiStateStore,
    config_path: Path,
) -> None:
    config_path.write_text(
        "\n".join(
            [
                "[workspace]",
                "workflow_root = /tmp/legacy-workspace",
                "workflow_profile_id = calibration",
                "workflow_anchor_type_id = root",
                "workflow_active_node_id = calibration:root",
                "last_workflow_tab = 2",
                "[analysis_page]",
                "last_plugin_id = iris_gain",
                "[panels]",
                "workflow.explorer_dock = false",
                "[splitters]",
                "measure.main_splitter = 200,400",
                "[recent_workflows]",
                (
                    "entry_01 = "
                    "{\"workspace_root\": \"/tmp/legacy-workspace\", "
                    "\"profile_id\": \"calibration\"}"
                ),
            ],
        )
        + "\n",
        encoding="utf-8",
    )

    snapshot = store.load()

    assert snapshot.panel_states == {}
    assert snapshot.splitter_sizes == {}
    assert snapshot.last_tab_index is None
    assert snapshot.last_analysis_plugin_id is None
    assert snapshot.workflow_workspace_root is None
    assert snapshot.workflow_profile_id is None
    assert snapshot.workflow_anchor_type_id is None
    assert snapshot.workflow_active_node_id is None
    assert snapshot.recent_workflows == []
    assert snapshot.recent_workspace_documents == []


def test_compatibility_helpers_no_longer_persist_ui_state(
    store: UiStateStore,
) -> None:
    store.set_panel_state("workflow.explorer_dock", False)
    store.set_splitter_sizes("measure.main_splitter", [300, 500])

    assert store.panel_state("workflow.explorer_dock") is None
    assert store.splitter_sizes("measure.main_splitter") is None

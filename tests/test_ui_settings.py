"""Tests for persistent UI preferences and workspace state."""

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path

import pytest
import framelab.scan_settings as scan_settings_module
from framelab.ui_settings import (
    DensityMode,
    RecentWorkflowEntry,
    UiPreferences,
    UiStateSnapshot,
    UiStateStore,
)


pytestmark = [pytest.mark.fast, pytest.mark.core]


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return tmp_path / "ui_state.ini"


@pytest.fixture
def store(config_path: Path) -> UiStateStore:
    return UiStateStore(config_path)


def test_load_returns_defaults_when_config_missing(store: UiStateStore) -> None:
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


def test_save_and_reload_round_trips_preferences_and_state(
    store: UiStateStore,
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
            RecentWorkflowEntry(
                workspace_root="/tmp/workspaces/trials/trial-0004",
                profile_id="trials",
                anchor_type_id="trial",
                active_node_id="trials:trial",
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
    assert reloaded.panel_states == {
        "analysis.plugin_controls": False,
        "data.advanced_row": True,
    }
    assert reloaded.splitter_sizes == {"measure.main_splitter": [640, 360]}
    assert reloaded.last_tab_index == 2
    assert reloaded.last_analysis_plugin_id == "iris_gain"
    assert reloaded.workflow_workspace_root == "/tmp/workspaces/calibration"
    assert reloaded.workflow_profile_id == "calibration"
    assert reloaded.workflow_anchor_type_id == "session"
    assert (
        reloaded.workflow_active_node_id
        == "calibration:session:cam-a/campaign-1/session-01"
    )
    assert reloaded.recent_workflows == [
        RecentWorkflowEntry(
            workspace_root="/tmp/workspaces/calibration",
            profile_id="calibration",
            anchor_type_id="root",
            active_node_id="calibration:root",
        ),
        RecentWorkflowEntry(
            workspace_root="/tmp/workspaces/trials/trial-0004",
            profile_id="trials",
            anchor_type_id="trial",
            active_node_id="trials:trial",
        ),
    ]


def test_incremental_panel_and_splitter_updates_preserve_other_sections(
    store: UiStateStore,
    config_path: Path,
) -> None:
    config = ConfigParser()
    config.add_section("scan")
    config.set("scan", "skip_patterns", "*.bak")
    with config_path.open("w", encoding="utf-8") as handle:
        config.write(handle)

    store.set_panel_state("analysis.plugin_controls", False)
    store.set_splitter_sizes("measure.main_splitter", [400, 300])

    reloaded_config = ConfigParser()
    reloaded_config.read(config_path, encoding="utf-8")

    assert reloaded_config.get("scan", "skip_patterns") == "*.bak"
    assert not store.panel_state("analysis.plugin_controls")
    assert store.splitter_sizes("measure.main_splitter") == [400, 300]


def test_invalid_values_fall_back_to_defaults(
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
                "last_workflow_tab = not-a-number",
                "[data_page]",
                "collapse_advanced_row_by_default = no",
                "[analysis_page]",
                "collapse_plugin_controls_by_default = invalid",
                "last_plugin_id = iris_gain",
                "[panels]",
                "analysis.plugin_controls = invalid",
                "[splitters]",
                "measure.main_splitter = 300, nope",
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
    assert snapshot.last_analysis_plugin_id == "iris_gain"
    assert snapshot.workflow_workspace_root is None
    assert snapshot.workflow_profile_id is None
    assert snapshot.workflow_anchor_type_id is None
    assert snapshot.workflow_active_node_id is None
    assert snapshot.recent_workflows == []


def test_invalid_recent_workflow_entries_are_ignored(
    store: UiStateStore,
    config_path: Path,
) -> None:
    config_path.write_text(
        "\n".join(
            [
                "[recent_workflows]",
                "entry_01 = not-json",
                "entry_02 = {\"workspace_root\": \"/tmp/work\", \"profile_id\": \"\"}",
                (
                    "entry_03 = "
                    "{\"workspace_root\": \"/tmp/work\", \"profile_id\": \"calibration\", "
                    "\"anchor_type_id\": \"session\", "
                    "\"active_node_id\": \"calibration:session\"}"
                ),
            ],
        )
        + "\n",
        encoding="utf-8",
    )

    snapshot = store.load()

    assert snapshot.recent_workflows == [
        RecentWorkflowEntry(
            workspace_root="/tmp/work",
            profile_id="calibration",
            anchor_type_id="session",
            active_node_id="calibration:session",
        ),
    ]


def test_skip_patterns_persist_in_ui_state_without_creating_legacy_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    monkeypatch.setattr(scan_settings_module, "_repo_root", lambda: repo_root)

    scan_settings_module.save_skip_patterns(["*.bak", "notes"])

    ui_state_path = scan_settings_module.skip_config_path()
    legacy_config_path = repo_root / "config" / "config.ini"
    assert ui_state_path.is_file()
    assert not legacy_config_path.exists()
    assert scan_settings_module.load_skip_patterns() == ["*.bak", "notes"]

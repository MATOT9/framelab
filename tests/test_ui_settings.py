"""Tests for persistent UI preferences and workspace state."""

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path

import pytest
from framelab.ui_settings import (
    DensityMode,
    UiPreferences,
    UiStateSnapshot,
    UiStateStore,
)


pytestmark = [pytest.mark.fast, pytest.mark.core]


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return tmp_path / "config.ini"


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
    assert snapshot.panel_states == {}
    assert snapshot.splitter_sizes == {}
    assert snapshot.last_tab_index is None
    assert snapshot.last_analysis_plugin_id is None


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
        ),
        panel_states={
            "analysis.plugin_controls": False,
            "data.advanced_row": True,
        },
        splitter_sizes={"measure.main_splitter": [640, 360]},
        last_tab_index=2,
        last_analysis_plugin_id="iris_gain",
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
    assert reloaded.panel_states == {
        "analysis.plugin_controls": False,
        "data.advanced_row": True,
    }
    assert reloaded.splitter_sizes == {"measure.main_splitter": [640, 360]}
    assert reloaded.last_tab_index == 2
    assert reloaded.last_analysis_plugin_id == "iris_gain"


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
    assert snapshot.panel_states == {}
    assert snapshot.splitter_sizes == {}
    assert snapshot.last_tab_index is None
    assert snapshot.last_analysis_plugin_id == "iris_gain"

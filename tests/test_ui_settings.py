"""Tests for persistent UI preferences and workspace state."""

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path
import tempfile
import unittest

from framelab.ui_settings import (
    DensityMode,
    UiPreferences,
    UiStateSnapshot,
    UiStateStore,
)


class UiStateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.config_path = Path(self._tmpdir.name) / "config.ini"
        self.store = UiStateStore(self.config_path)

    def test_load_returns_defaults_when_config_missing(self) -> None:
        snapshot = self.store.load()

        self.assertEqual(snapshot.preferences.theme_mode, "dark")
        self.assertEqual(snapshot.preferences.density_mode, DensityMode.AUTO)
        self.assertTrue(snapshot.preferences.show_page_subtitles)
        self.assertTrue(snapshot.preferences.show_image_preview)
        self.assertFalse(snapshot.preferences.show_histogram_preview)
        self.assertTrue(snapshot.preferences.restore_panel_states)
        self.assertTrue(snapshot.preferences.restore_last_tab)
        self.assertEqual(snapshot.panel_states, {})
        self.assertEqual(snapshot.splitter_sizes, {})
        self.assertIsNone(snapshot.last_tab_index)
        self.assertIsNone(snapshot.last_analysis_plugin_id)

    def test_save_and_reload_round_trips_preferences_and_state(self) -> None:
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

        self.store.save(snapshot)
        reloaded = self.store.load()

        self.assertEqual(reloaded.preferences.theme_mode, "light")
        self.assertEqual(reloaded.preferences.density_mode, DensityMode.COMPACT)
        self.assertFalse(reloaded.preferences.show_page_subtitles)
        self.assertFalse(reloaded.preferences.show_image_preview)
        self.assertTrue(reloaded.preferences.show_histogram_preview)
        self.assertFalse(reloaded.preferences.restore_panel_states)
        self.assertFalse(reloaded.preferences.restore_last_tab)
        self.assertFalse(
            reloaded.preferences.collapse_analysis_plugin_controls_by_default,
        )
        self.assertFalse(
            reloaded.preferences.collapse_data_advanced_row_by_default,
        )
        self.assertTrue(reloaded.preferences.collapse_summary_strips_by_default)
        self.assertEqual(
            reloaded.panel_states,
            {
                "analysis.plugin_controls": False,
                "data.advanced_row": True,
            },
        )
        self.assertEqual(
            reloaded.splitter_sizes,
            {"measure.main_splitter": [640, 360]},
        )
        self.assertEqual(reloaded.last_tab_index, 2)
        self.assertEqual(reloaded.last_analysis_plugin_id, "iris_gain")

    def test_incremental_panel_and_splitter_updates_preserve_other_sections(self) -> None:
        config = ConfigParser()
        config.add_section("scan")
        config.set("scan", "skip_patterns", "*.bak")
        with self.config_path.open("w", encoding="utf-8") as handle:
            config.write(handle)

        self.store.set_panel_state("analysis.plugin_controls", False)
        self.store.set_splitter_sizes("measure.main_splitter", [400, 300])

        reloaded_config = ConfigParser()
        reloaded_config.read(self.config_path, encoding="utf-8")

        self.assertEqual(reloaded_config.get("scan", "skip_patterns"), "*.bak")
        self.assertFalse(self.store.panel_state("analysis.plugin_controls"))
        self.assertEqual(
            self.store.splitter_sizes("measure.main_splitter"),
            [400, 300],
        )

    def test_invalid_values_fall_back_to_defaults(self) -> None:
        self.config_path.write_text(
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

        snapshot = self.store.load()

        self.assertEqual(snapshot.preferences.theme_mode, "dark")
        self.assertEqual(snapshot.preferences.density_mode, DensityMode.AUTO)
        self.assertTrue(snapshot.preferences.show_page_subtitles)
        self.assertTrue(snapshot.preferences.show_image_preview)
        self.assertTrue(snapshot.preferences.show_histogram_preview)
        self.assertTrue(snapshot.preferences.restore_panel_states)
        self.assertFalse(snapshot.preferences.restore_last_tab)
        self.assertFalse(snapshot.preferences.collapse_data_advanced_row_by_default)
        self.assertTrue(
            snapshot.preferences.collapse_analysis_plugin_controls_by_default,
        )
        self.assertEqual(snapshot.panel_states, {})
        self.assertEqual(snapshot.splitter_sizes, {})
        self.assertIsNone(snapshot.last_tab_index)
        self.assertEqual(snapshot.last_analysis_plugin_id, "iris_gain")


if __name__ == "__main__":
    unittest.main()

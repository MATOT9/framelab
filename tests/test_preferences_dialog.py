"""Tests for the preferences dialog live-preview behavior."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets as qtw

from framelab.preferences_dialog import PreferencesDialog
from framelab.ui_settings import DensityMode, UiPreferences, UiStateSnapshot


class PreferencesDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = qtw.QApplication.instance() or qtw.QApplication([])

    def test_current_preferences_reflect_initial_snapshot(self) -> None:
        prefs = UiPreferences(
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
        )
        dialog = PreferencesDialog(UiStateSnapshot(preferences=prefs))
        self.addCleanup(dialog.deleteLater)

        self.assertEqual(dialog.current_preferences(), prefs)

    def test_reject_emits_revert_after_live_preview_change(self) -> None:
        initial = UiPreferences(theme_mode="dark")
        dialog = PreferencesDialog(UiStateSnapshot(preferences=initial))
        self.addCleanup(dialog.deleteLater)
        seen: list[UiPreferences] = []
        dialog.preferences_changed.connect(lambda prefs: seen.append(prefs))

        dialog._theme_combo.setCurrentIndex(dialog._theme_combo.findData("light"))
        qtw.QApplication.processEvents()
        dialog.reject()
        qtw.QApplication.processEvents()

        self.assertGreaterEqual(len(seen), 2)
        self.assertEqual(seen[0].theme_mode, "light")
        self.assertEqual(seen[-1].theme_mode, "dark")


if __name__ == "__main__":
    unittest.main()

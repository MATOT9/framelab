"""Integration tests for Measure-page contextual chrome."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets as qtw

from framelab.window import FrameLabWindow


class MeasurePageUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = qtw.QApplication.instance() or qtw.QApplication([])

    def _build_window(self) -> FrameLabWindow:
        window = FrameLabWindow(enabled_plugin_ids=())
        self.addCleanup(window.deleteLater)
        window.ui_state_snapshot.splitter_sizes.clear()
        return window

    def test_measure_display_menu_updates_rounding_and_normalization(self) -> None:
        window = self._build_window()

        window.measure_normalize_action.setChecked(True)
        self.assertTrue(window.metrics_state.normalize_intensity_values)

        window._measure_rounding_actions["std"].trigger()
        self.assertEqual(window.metrics_state.rounding_mode, "std")
        self.assertIn("normalized", window.measure_display_button.toolTip())
        self.assertIn("Std rounding", window.measure_display_button.toolTip())

    def test_measure_help_visibility_respects_preview_flags(self) -> None:
        window = self._build_window()

        window.show_image_preview = True
        window.show_histogram_preview = True
        window._set_measure_help_visibility(False)
        self.assertTrue(window.preview_help_label.isHidden())
        self.assertTrue(window.histogram_help_label.isHidden())

        window._set_measure_help_visibility(True)
        self.assertFalse(window.preview_help_label.isHidden())
        self.assertFalse(window.histogram_help_label.isHidden())

        window.show_histogram_preview = False
        window._set_measure_help_visibility(True)
        self.assertFalse(window.preview_help_label.isHidden())
        self.assertTrue(window.histogram_help_label.isHidden())

    def test_measure_splitter_state_round_trip(self) -> None:
        window = self._build_window()
        splitter = window.measure_main_splitter
        splitter.setSizes([720, 360])
        stored_sizes = splitter.sizes()

        window._persist_splitter_state("measure.main_splitter", splitter)

        self.assertEqual(
            window.ui_state_snapshot.splitter_sizes["measure.main_splitter"],
            stored_sizes,
        )

        window.ui_state_snapshot.splitter_sizes["measure.main_splitter"] = [200, 800]
        splitter.setSizes([600, 400])
        window._restore_splitter_state("measure.main_splitter", splitter)
        restored_sizes = splitter.sizes()

        self.assertEqual(len(restored_sizes), 2)
        self.assertGreater(restored_sizes[1], restored_sizes[0])


if __name__ == "__main__":
    unittest.main()

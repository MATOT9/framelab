"""Integration tests for density-driven main window layout metrics."""

from __future__ import annotations

import os
import unittest
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets as qtw

from framelab.ui_settings import DensityMode
from framelab.window import FrameLabWindow


class WindowDensityIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = qtw.QApplication.instance() or qtw.QApplication([])

    def test_compact_density_updates_root_and_page_layouts(self) -> None:
        window = FrameLabWindow(enabled_plugin_ids=())
        self.addCleanup(window.deleteLater)

        compact_prefs = replace(window.ui_preferences, density_mode=DensityMode.COMPACT)
        window._apply_ui_preferences(compact_prefs, persist=False)
        tokens = window._active_density_tokens

        root_layout = window.centralWidget().layout()
        self.assertEqual(root_layout.contentsMargins().left(), tokens.root_margin)
        self.assertEqual(root_layout.spacing(), tokens.page_spacing)
        self.assertEqual(window._data_page_layout.spacing(), tokens.page_spacing)
        self.assertEqual(window._measure_page_layout.spacing(), tokens.page_spacing)
        self.assertEqual(window._analysis_page_layout.spacing(), tokens.page_spacing)
        self.assertEqual(
            window._data_command_layout.contentsMargins().left(),
            tokens.command_bar_margin_h,
        )
        self.assertEqual(
            window._measure_metrics_layout.contentsMargins().left(),
            tokens.command_bar_margin_h,
        )
        self.assertEqual(
            window._analysis_selector_layout.contentsMargins().left(),
            tokens.panel_margin_h,
        )
        self.assertEqual(
            window._analysis_side_rail_layout.spacing(),
            tokens.panel_spacing,
        )


if __name__ == "__main__":
    unittest.main()

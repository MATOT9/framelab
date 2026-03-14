"""Integration tests for Analysis-page disclosure and hint visibility."""

from __future__ import annotations

import os
import unittest
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets as qtw

from framelab.ui_settings import DensityMode
from framelab.window import FrameLabWindow


class AnalysisPageUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = qtw.QApplication.instance() or qtw.QApplication([])

    def _build_window(self) -> FrameLabWindow:
        window = FrameLabWindow(enabled_plugin_ids=("iris_gain_vs_exposure",))
        self.addCleanup(window.deleteLater)
        window.ui_state_snapshot.panel_states.clear()
        window.ui_state_snapshot.splitter_sizes.clear()
        window._session_panel_overrides.clear()
        return window

    def _show_analysis_page(self, window: FrameLabWindow) -> None:
        analysis_index = window.workflow_tabs.indexOf(window.analysis_page)
        window.workflow_tabs.setCurrentIndex(analysis_index)
        window.resize(1400, 900)
        window.show()
        self.addCleanup(window.close)
        self._app.processEvents()
        window._restore_or_default_analysis_main_splitter()
        plugin = window._current_analysis_plugin()
        if plugin is not None:
            window._restore_active_analysis_workspace_splitter(plugin)
        self._app.processEvents()

    def test_analysis_host_splits_selector_controls_and_workspace(self) -> None:
        window = self._build_window()
        self._show_analysis_page(window)
        plugin = window._current_analysis_plugin()

        self.assertIsNotNone(plugin)
        assert plugin is not None
        self.assertEqual(window.analysis_main_splitter.count(), 2)
        self.assertIs(window.analysis_controls_stack.currentWidget(), plugin._controls_panel)
        self.assertIs(
            window.analysis_workspace_stack.currentWidget(),
            plugin._workspace_widget,
        )
        self.assertIs(window.analysis_stack, window.analysis_workspace_stack)
        self.assertIs(plugin.workspace_splitter(), plugin._workspace_splitter)
        self.assertIsInstance(plugin._controls_panel.layout(), qtw.QVBoxLayout)
        main_sizes = window.analysis_main_splitter.sizes()
        workspace_sizes = plugin.workspace_splitter().sizes()
        self.assertGreater(main_sizes[1], main_sizes[0])
        self.assertGreaterEqual(workspace_sizes[1], workspace_sizes[0])

    def test_analysis_plugin_controls_toggle_updates_session_override(self) -> None:
        window = self._build_window()
        self._show_analysis_page(window)
        plugin = window._current_analysis_plugin()

        self.assertIsNotNone(plugin)
        assert plugin is not None
        self.assertTrue(window.analysis_controls_stack.isHidden())
        self.assertFalse(window.analysis_plugin_controls_toggle.isChecked())

        window.analysis_plugin_controls_toggle.setChecked(True)
        self._app.processEvents()

        self.assertFalse(window.analysis_controls_stack.isHidden())
        self.assertTrue(window.analysis_plugin_controls_toggle.isChecked())
        self.assertTrue(window._session_panel_overrides["analysis.plugin_controls"])
        self.assertTrue(
            window.ui_state_snapshot.panel_states["analysis.plugin_controls"],
        )

    def test_analysis_main_splitter_persists_user_resize(self) -> None:
        window = self._build_window()
        self._show_analysis_page(window)
        splitter = window.analysis_main_splitter
        initial_sizes = splitter.sizes()

        splitter.moveSplitter(380, 1)
        self._app.processEvents()
        stored_sizes = window.ui_state_snapshot.splitter_sizes[
            window._analysis_main_splitter_key()
        ]

        self.assertEqual(len(stored_sizes), 2)
        self.assertNotEqual(stored_sizes, initial_sizes)

    def test_plugin_workspace_splitter_restore_uses_plugin_key(self) -> None:
        window = self._build_window()
        self._show_analysis_page(window)
        plugin = window._current_analysis_plugin()

        self.assertIsNotNone(plugin)
        assert plugin is not None
        splitter = plugin.workspace_splitter()
        self.assertIsNotNone(splitter)
        assert splitter is not None
        key = window._analysis_workspace_splitter_key(plugin)

        splitter.moveSplitter(100, 1)
        self._app.processEvents()
        before_restore = splitter.sizes()

        window.ui_state_snapshot.splitter_sizes[key] = [280, 220]
        window._restore_active_analysis_workspace_splitter(plugin)
        self._app.processEvents()
        restored_sizes = splitter.sizes()

        self.assertEqual(len(restored_sizes), 2)
        self.assertNotEqual(restored_sizes, before_restore)
        self.assertGreater(restored_sizes[0], restored_sizes[1])

    def test_pathological_saved_workspace_split_is_rebalanced(self) -> None:
        window = self._build_window()
        self._show_analysis_page(window)
        plugin = window._current_analysis_plugin()

        self.assertIsNotNone(plugin)
        assert plugin is not None
        splitter = plugin.workspace_splitter()
        self.assertIsNotNone(splitter)
        assert splitter is not None
        key = window._analysis_workspace_splitter_key(plugin)

        window.ui_state_snapshot.splitter_sizes[key] = [921, 154]
        window._restore_active_analysis_workspace_splitter(plugin)
        self._app.processEvents()
        restored_sizes = splitter.sizes()

        self.assertEqual(len(restored_sizes), 2)
        self.assertLessEqual(abs(restored_sizes[0] - restored_sizes[1]), 1)

    def test_analysis_plot_hint_visibility_follows_density_policy(self) -> None:
        window = self._build_window()
        self._show_analysis_page(window)
        plugin = window._current_analysis_plugin()

        self.assertIsNotNone(plugin)
        assert plugin is not None
        comfortable_prefs = replace(
            window.ui_preferences,
            density_mode=DensityMode.COMFORTABLE,
        )
        window._apply_ui_preferences(comfortable_prefs, persist=False)
        self.assertFalse(plugin._plot_hint_label.isHidden())

        compact_prefs = replace(
            window.ui_preferences,
            density_mode=DensityMode.COMPACT,
        )
        window._apply_ui_preferences(compact_prefs, persist=False)
        self.assertTrue(plugin._plot_hint_label.isHidden())
        window._apply_ui_preferences(comfortable_prefs, persist=False)
        self.assertFalse(plugin._plot_hint_label.isHidden())


if __name__ == "__main__":
    unittest.main()

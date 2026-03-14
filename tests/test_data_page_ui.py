"""Integration tests for Data-page disclosure and skip-rule chrome."""

from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets as qtw

from framelab.ui_primitives import StatusChip
from framelab.window import FrameLabWindow


class DataPageUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = qtw.QApplication.instance() or qtw.QApplication([])

    def _build_window(self) -> FrameLabWindow:
        window = FrameLabWindow(enabled_plugin_ids=())
        self.addCleanup(window.deleteLater)
        window.ui_state_snapshot.panel_states.clear()
        window._session_panel_overrides.clear()
        return window

    def test_data_advanced_row_toggle_updates_session_override(self) -> None:
        window = self._build_window()

        prefs = replace(
            window.ui_preferences,
            restore_panel_states=True,
            collapse_data_advanced_row_by_default=True,
        )
        window._apply_ui_preferences(prefs, persist=False)

        self.assertTrue(window._data_advanced_container.isHidden())
        self.assertFalse(window.data_advanced_toggle.isChecked())

        window.data_advanced_toggle.setChecked(True)

        self.assertFalse(window._data_advanced_container.isHidden())
        self.assertTrue(window.data_advanced_toggle.isChecked())
        self.assertTrue(window._session_panel_overrides["data.advanced_row"])
        self.assertTrue(window.ui_state_snapshot.panel_states["data.advanced_row"])

    def test_session_override_survives_policy_reapply_when_restore_disabled(self) -> None:
        window = self._build_window()

        prefs = replace(
            window.ui_preferences,
            restore_panel_states=False,
            collapse_data_advanced_row_by_default=True,
        )
        window._apply_ui_preferences(prefs, persist=False)
        self.assertTrue(window._data_advanced_container.isHidden())

        window.data_advanced_toggle.setChecked(True)
        window._apply_dynamic_visibility_policy()

        self.assertFalse(window._data_advanced_container.isHidden())
        self.assertTrue(window.data_advanced_toggle.isChecked())

    def test_skip_rule_summary_preview_compacts_active_patterns(self) -> None:
        window = self._build_window()

        window._set_skip_patterns(
            ["temp", "*/cache/*", "*.bak", "notes"],
            persist=False,
        )

        self.assertEqual(window.skip_pattern_count_chip.text(), "4 rules")
        self.assertIn("4 active rules", window.skip_pattern_hint.text())
        self.assertEqual(
            window.skip_pattern_preview_label.text(),
            "Active patterns: temp, */cache/*, *.bak +1 more",
        )
        self.assertFalse(window.skip_pattern_preview_label.isHidden())

        window._set_skip_patterns([], persist=False)

        self.assertEqual(window.skip_pattern_count_chip.text(), "0 rules")
        self.assertIn("No active skip rules", window.skip_pattern_hint.text())
        self.assertEqual(window.skip_pattern_preview_label.text(), "")
        self.assertTrue(window.skip_pattern_preview_label.isHidden())

    def test_metadata_controls_row_is_no_longer_collapsible(self) -> None:
        window = self._build_window()

        window.data_advanced_toggle.setChecked(True)

        self.assertFalse(hasattr(window, "metadata_controls_toggle"))
        self.assertFalse(window.metadata_controls_body.isHidden())
        self.assertFalse(window.metadata_source_combo.isHidden())

    def test_ebus_status_scans_selected_root_recursively(self) -> None:
        window = self._build_window()

        with tempfile.TemporaryDirectory() as temp_dir:
            dataset_root = Path(temp_dir) / "dataset"
            acquisition_root = dataset_root / "session-01" / "acq-0001"
            frames_dir = acquisition_root / "frames"
            frames_dir.mkdir(parents=True)
            snapshot_path = acquisition_root / "camera_snapshot.pvcfg"
            snapshot_path.write_text(
                "DeviceModelName=Test Camera\n",
                encoding="utf-8",
            )

            window.folder_edit.setText(str(dataset_root))
            window._refresh_ebus_config_status(dataset_root)

            self.assertEqual(
                window.ebus_config_status_label.text(),
                "eBUS config: camera_snapshot.pvcfg",
            )
            self.assertEqual(
                window.ebus_config_status_label.toolTip(),
                str(snapshot_path),
            )

            header_chip_texts = [
                chip.text()
                for chip in window._data_header.findChildren(StatusChip)
            ]
            self.assertIn("eBUS config detected", header_chip_texts)

            summary_values: dict[str, str] = {}
            for card in window._data_summary_strip.findChildren(qtw.QFrame, "SummaryCard"):
                label = card.findChild(qtw.QLabel, "SummaryLabel")
                value = card.findChild(qtw.QLabel, "SummaryValue")
                if label is None or value is None:
                    continue
                summary_values[label.text()] = value.text()

            self.assertEqual(summary_values.get("eBUS"), "1 file")


if __name__ == "__main__":
    unittest.main()

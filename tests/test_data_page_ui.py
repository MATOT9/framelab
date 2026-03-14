"""Integration tests for Data-page disclosure and skip-rule chrome."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6 import QtWidgets as qtw

from framelab.ui_primitives import StatusChip
from framelab.window import FrameLabWindow


pytestmark = [pytest.mark.ui, pytest.mark.data]


@pytest.fixture
def data_window(framelab_window_factory) -> FrameLabWindow:
    window = framelab_window_factory(enabled_plugin_ids=())
    window.ui_state_snapshot.panel_states.clear()
    window._session_panel_overrides.clear()
    return window


def test_data_advanced_row_toggle_updates_session_override(
    data_window: FrameLabWindow,
) -> None:
    prefs = replace(
        data_window.ui_preferences,
        restore_panel_states=True,
        collapse_data_advanced_row_by_default=True,
    )
    data_window._apply_ui_preferences(prefs, persist=False)

    assert data_window._data_advanced_container.isHidden()
    assert not data_window.data_advanced_toggle.isChecked()

    data_window.data_advanced_toggle.setChecked(True)

    assert not data_window._data_advanced_container.isHidden()
    assert data_window.data_advanced_toggle.isChecked()
    assert data_window._session_panel_overrides["data.advanced_row"]
    assert data_window.ui_state_snapshot.panel_states["data.advanced_row"]


def test_session_override_survives_policy_reapply_when_restore_disabled(
    data_window: FrameLabWindow,
) -> None:
    prefs = replace(
        data_window.ui_preferences,
        restore_panel_states=False,
        collapse_data_advanced_row_by_default=True,
    )
    data_window._apply_ui_preferences(prefs, persist=False)
    assert data_window._data_advanced_container.isHidden()

    data_window.data_advanced_toggle.setChecked(True)
    data_window._apply_dynamic_visibility_policy()

    assert not data_window._data_advanced_container.isHidden()
    assert data_window.data_advanced_toggle.isChecked()


def test_skip_rule_summary_preview_compacts_active_patterns(
    data_window: FrameLabWindow,
) -> None:
    data_window._set_skip_patterns(
        ["temp", "*/cache/*", "*.bak", "notes"],
        persist=False,
    )

    assert data_window.skip_pattern_count_chip.text() == "4 rules"
    assert "4 active rules" in data_window.skip_pattern_hint.text()
    assert (
        data_window.skip_pattern_preview_label.text()
        == "Active patterns: temp, */cache/*, *.bak +1 more"
    )
    assert not data_window.skip_pattern_preview_label.isHidden()

    data_window._set_skip_patterns([], persist=False)

    assert data_window.skip_pattern_count_chip.text() == "0 rules"
    assert "No active skip rules" in data_window.skip_pattern_hint.text()
    assert data_window.skip_pattern_preview_label.text() == ""
    assert data_window.skip_pattern_preview_label.isHidden()


def test_metadata_controls_row_is_no_longer_collapsible(
    data_window: FrameLabWindow,
) -> None:
    data_window.data_advanced_toggle.setChecked(True)

    assert not hasattr(data_window, "metadata_controls_toggle")
    assert not data_window.metadata_controls_body.isHidden()
    assert not data_window.metadata_source_combo.isHidden()


def test_ebus_status_scans_selected_root_recursively(
    data_window: FrameLabWindow,
    tmp_path: Path,
) -> None:
    dataset_root = tmp_path / "dataset"
    acquisition_root = dataset_root / "session-01" / "acq-0001"
    frames_dir = acquisition_root / "frames"
    frames_dir.mkdir(parents=True)
    snapshot_path = acquisition_root / "camera_snapshot.pvcfg"
    snapshot_path.write_text(
        "DeviceModelName=Test Camera\n",
        encoding="utf-8",
    )

    data_window.folder_edit.setText(str(dataset_root))
    data_window._refresh_ebus_config_status(dataset_root)

    assert data_window.ebus_config_status_label.text() == "eBUS config: camera_snapshot.pvcfg"
    assert data_window.ebus_config_status_label.toolTip() == str(snapshot_path)

    header_chip_texts = [
        chip.text()
        for chip in data_window._data_header.findChildren(StatusChip)
    ]
    assert "eBUS config detected" in header_chip_texts

    summary_values: dict[str, str] = {}
    for card in data_window._data_summary_strip.findChildren(qtw.QFrame, "SummaryCard"):
        label = card.findChild(qtw.QLabel, "SummaryLabel")
        value = card.findChild(qtw.QLabel, "SummaryValue")
        if label is None or value is None:
            continue
        summary_values[label.text()] = value.text()

    assert summary_values.get("eBUS") == "1 file"

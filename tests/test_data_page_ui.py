"""Integration tests for Data-page disclosure and skip-rule chrome."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6 import QtWidgets as qtw

from framelab.metrics_state import MetricFamily, ScanMetricPreset
from framelab.processing_failures import make_processing_failure
from framelab.node_metadata import save_nodecard
from framelab.ui_primitives import StatusChip
from framelab.window import FrameLabWindow
from framelab.workers import DatasetLoadSummary


pytestmark = [pytest.mark.ui, pytest.mark.data]


@pytest.fixture
def data_window(framelab_window_factory) -> FrameLabWindow:
    window = framelab_window_factory(enabled_plugin_ids=())
    window.ui_state_snapshot.panel_states.clear()
    window._session_panel_overrides.clear()
    return window


def _submenu_by_title(menu: qtw.QMenu, title: str) -> qtw.QMenu | None:
    """Return one submenu by visible action title."""

    for action in menu.actions():
        if action.text() == title:
            return action.menu()
    return None


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


def test_scan_metric_preset_combo_updates_controller_and_header(
    data_window: FrameLabWindow,
) -> None:
    index = data_window.scan_metric_preset_combo.findData(
        ScanMetricPreset.TOPK_STUDY.value,
    )

    data_window.scan_metric_preset_combo.setCurrentIndex(index)

    assert data_window.metrics_state.scan_metric_preset == ScanMetricPreset.TOPK_STUDY
    assert data_window.metrics_state.scan_metric_families() == (
        MetricFamily.STATIC_SCAN,
        MetricFamily.SATURATION,
        MetricFamily.TOPK,
    )
    assert data_window._workspace_document_dirty is True
    header_chip_texts = [
        chip.text()
        for chip in data_window._data_header.findChildren(StatusChip)
    ]
    assert "Scan: Top-K Study" in header_chip_texts


def test_custom_scan_metric_family_menu_updates_custom_setup(
    data_window: FrameLabWindow,
) -> None:
    custom_index = data_window.scan_metric_preset_combo.findData(
        ScanMetricPreset.CUSTOM.value,
    )
    data_window.scan_metric_preset_combo.setCurrentIndex(custom_index)
    action = data_window._scan_metric_family_actions[MetricFamily.ROI_TOPK.value]

    action.setChecked(True)

    assert data_window.metrics_state.scan_metric_preset == ScanMetricPreset.CUSTOM
    assert data_window.metrics_state.scan_metric_families() == (
        MetricFamily.STATIC_SCAN,
        MetricFamily.ROI_TOPK,
    )
    assert data_window.scan_metric_custom_button.isEnabled()


def test_edit_advanced_menu_always_exposes_core_ebus_tools(
    data_window: FrameLabWindow,
) -> None:
    ebus_menu = _submenu_by_title(data_window.edit_advanced_menu, "eBUS Config Tools")

    assert ebus_menu is not None
    action_texts = [action.text() for action in ebus_menu.actions() if not action.isSeparator()]
    assert action_texts == [
        "Inspect eBUS Config File...",
        "Compare eBUS Configs...",
    ]


def test_edit_advanced_menu_shows_wizard_bridge_when_plugin_is_enabled(
    framelab_window_factory,
) -> None:
    window = framelab_window_factory(
        enabled_plugin_ids=("acquisition_datacard_wizard",),
    )

    ebus_menu = _submenu_by_title(window.edit_advanced_menu, "eBUS Config Tools")

    assert ebus_menu is not None
    action_texts = [action.text() for action in ebus_menu.actions() if not action.isSeparator()]
    assert action_texts == [
        "Inspect eBUS Config File...",
        "Compare eBUS Configs...",
        "Open Datacard Wizard",
    ]


def test_ebus_status_scans_selected_root_recursively(
    data_window: FrameLabWindow,
    tmp_path: Path,
    wait_until,
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
    wait_until(
        lambda: data_window.ebus_config_status_label.text() == "eBUS config: camera_snapshot.pvcfg",
        timeout_ms=1000,
    )

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


def test_data_header_defers_recursive_ebus_discovery_to_background_scan(
    data_window: FrameLabWindow,
    tmp_path: Path,
    wait_until,
) -> None:
    dataset_root = tmp_path / "dataset"
    acquisition_root = dataset_root / "session-01" / "acq-0001"
    acquisition_root.mkdir(parents=True)
    snapshot_path = acquisition_root / "camera_snapshot.pvcfg"
    snapshot_path.write_text("DeviceModelName=Test Camera\n", encoding="utf-8")

    data_window.folder_edit.setText(str(dataset_root))
    data_window._refresh_data_header_state()

    assert any(
        chip.text() == "Scanning eBUS..."
        for chip in data_window._data_header.findChildren(StatusChip)
    )
    wait_until(
        lambda: getattr(data_window, "_ebus_config_discovery_thread", None) is None,
        timeout_ms=1000,
    )
    wait_until(
        lambda: data_window._ebus_summary_value(
            data_window._cached_recursive_ebus_configs(dataset_root)[0],
        ) == "1 file",
        timeout_ms=1000,
    )
    assert snapshot_path.exists()


def test_folder_json_metadata_scan_detects_nodecards_recursively(
    tmp_path: Path,
) -> None:
    dataset_root = tmp_path / "workspace"
    node_root = dataset_root / "camera-a" / "campaign-a"
    node_root.mkdir(parents=True, exist_ok=True)
    save_nodecard(
        node_root,
        {"camera_settings": {"exposure_us": 1000}},
        profile_id="calibration",
        node_type_id="campaign",
    )

    assert FrameLabWindow._folder_has_json_metadata(dataset_root)


def test_dataset_load_failure_surfaces_primary_raw_cause_and_hint(
    framelab_window_factory,
    monkeypatch,
    tmp_path: Path,
) -> None:
    window = framelab_window_factory(enabled_plugin_ids=())
    job_id = 17
    captured: list[tuple[str, str]] = []
    reason = (
        "RawDecodeSpecError: Missing RAW decode spec fields: "
        "pixel_format, width, height"
    )

    monkeypatch.setattr(
        window,
        "_show_error",
        lambda title, message: captured.append((title, message)),
    )
    window._dataset_load_job_id = job_id
    window._on_dataset_load_finished(
        DatasetLoadSummary(
            job_id=job_id,
            dataset_root=str(tmp_path),
            loaded_count=0,
            total_candidates=2,
            failures=(
                make_processing_failure(
                    stage="scan",
                    path=tmp_path / "frame_a.bin",
                    reason=reason,
                ),
                make_processing_failure(
                    stage="scan",
                    path=tmp_path / "frame_b.bin",
                    reason=reason,
                ),
            ),
        ),
    )

    assert captured
    assert captured[0][0] == "Load failed"
    message = captured[0][1]
    assert "All 2 supported image files failed to load." in message
    assert f"Most likely cause: {reason}" in message
    assert (
        "Add acquisition/session/campaign metadata, attach an eBUS config in "
        "the acquisition, or provide session-local RAW fallback values, then "
        "re-scan."
    ) in message
    assert "Open Processing Issues for per-file details." in message
    assert ".pvcfg" not in message
    assert window._processing_failure_count() == 2


def test_dataset_load_failure_summarizes_mixed_reasons_without_fake_root_cause(
    framelab_window_factory,
    monkeypatch,
    tmp_path: Path,
) -> None:
    window = framelab_window_factory(enabled_plugin_ids=())
    job_id = 18
    captured: list[tuple[str, str]] = []
    reason_a = (
        "RawDecodeSpecError: Missing RAW decode spec fields: "
        "pixel_format, width, height"
    )
    reason_b = "InvalidImageError: Expected 2D image, got shape (3, 4, 5)"

    monkeypatch.setattr(
        window,
        "_show_error",
        lambda title, message: captured.append((title, message)),
    )
    window._dataset_load_job_id = job_id
    window._on_dataset_load_finished(
        DatasetLoadSummary(
            job_id=job_id,
            dataset_root=str(tmp_path),
            loaded_count=0,
            total_candidates=2,
            failures=(
                make_processing_failure(
                    stage="scan",
                    path=tmp_path / "frame_a.bin",
                    reason=reason_a,
                ),
                make_processing_failure(
                    stage="scan",
                    path=tmp_path / "frame_b.bin",
                    reason=reason_b,
                ),
            ),
        ),
    )

    assert captured
    message = captured[0][1]
    assert "All 2 supported image files failed to load." in message
    assert "Observed failure types:" in message
    assert "Most likely cause:" not in message
    assert reason_a in message
    assert reason_b in message
    assert "Open Processing Issues for per-file details." in message

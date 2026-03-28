from __future__ import annotations

import json
from pathlib import Path

import pytest

import framelab.window as window_module
from PySide6 import QtWidgets as qtw
from PySide6.QtCore import Qt
from framelab.dock_title_bar import should_use_custom_dock_title_bar
from framelab.metadata_inspector_dock import MetadataInspectorDock
from framelab.node_metadata import load_nodecard, save_nodecard
from framelab.ui_settings import UiStateSnapshot, UiStateStore


pytestmark = [pytest.mark.ui, pytest.mark.core]


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _write_session_datacard(session_root: Path) -> None:
    _write_json(
        session_root / "session_datacard.json",
        {
            "schema_version": "1.0",
            "entity": "session",
            "identity": {"label": session_root.name},
            "paths": {
                "session_root_rel": None,
                "acquisitions_root_rel": "acquisitions",
                "notes_rel": None,
            },
            "session_defaults": {},
            "notes": "",
        },
    )


def _make_workspace_with_metadata(
    tmp_path: Path,
) -> tuple[Path, Path, Path, str]:
    workspace_root = tmp_path / "calibration"
    camera_root = workspace_root / "camera-a"
    session_root = camera_root / "campaign-2026" / "2026-03-05__sess01"
    acquisitions_root = session_root / "acquisitions"
    acquisitions_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)

    save_nodecard(
        camera_root,
        {"camera_settings": {"exposure_us": 1200}},
        profile_id="calibration",
        node_type_id="camera",
    )
    save_nodecard(
        session_root,
        {"instrument": {"optics": {"iris": {"position": 5}}}},
        profile_id="calibration",
        node_type_id="session",
    )

    session_node_id = (
        "calibration:session:"
        "camera-a/campaign-2026/2026-03-05__sess01"
    )
    return workspace_root, camera_root, session_root, session_node_id


def _make_trials_workspace_with_metadata(
    tmp_path: Path,
) -> tuple[Path, Path, str]:
    workspace_root = tmp_path / "trials"
    session_root = workspace_root / "trial-07" / "camera-a" / "2026-03-05__sess01"
    acquisitions_root = session_root / "acquisitions"
    acquisitions_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)

    save_nodecard(
        session_root,
        {"workflow": {"conditions": "dry"}},
        profile_id="trials",
        node_type_id="session",
    )

    session_node_id = "trials:session:trial-07/camera-a/2026-03-05__sess01"
    return workspace_root, session_root, session_node_id


def _make_workspace_with_acquisition_datacard(
    tmp_path: Path,
) -> tuple[Path, Path, Path, str]:
    workspace_root = tmp_path / "calibration"
    camera_root = workspace_root / "camera-a"
    session_root = camera_root / "campaign-2026" / "2026-03-05__sess01"
    acquisitions_root = session_root / "acquisitions"
    acquisition_root = acquisitions_root / "acq-0001"
    acquisition_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)

    save_nodecard(
        session_root,
        {
            "workflow": {"operator": "maxime"},
            "instrument": {"optics": {"iris": {"position": 2.25}}},
        },
        profile_id="calibration",
        node_type_id="session",
    )
    _write_json(
        acquisition_root / "acquisition_datacard.json",
        {
            "schema_version": "1.0",
            "entity": "acquisition",
            "identity": {"label": acquisition_root.name},
            "paths": {"frames_dir": "frames"},
            "intent": {},
            "defaults": {
                "camera_settings": {"exposure_us": 1200},
                "instrument": {"optics": {"iris": {"position": 3.5}}},
            },
            "overrides": [
                {
                    "selector": {"frame_range": [0, 2]},
                    "changes": {"camera_settings": {"exposure_us": 1400}},
                    "reason": "sweep",
                },
            ],
            "quality": {},
        },
    )

    session_node_id = (
        "calibration:session:"
        "camera-a/campaign-2026/2026-03-05__sess01"
    )
    return workspace_root, session_root, acquisition_root, session_node_id


def _row_for_key(table, key: str) -> int:
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        if item is not None and item.toolTip() == key:
            return row
    raise AssertionError(f"could not find row for metadata key {key!r}")


def test_metadata_inspector_dock_displays_effective_and_local_metadata(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, _camera_root, _session_root, session_node_id = (
        _make_workspace_with_metadata(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )

    dock = window._metadata_inspector_dock
    assert isinstance(dock, MetadataInspectorDock)
    assert dock.features() & qtw.QDockWidget.DockWidgetFloatable
    assert dock.allowedAreas() == Qt.AllDockWidgetAreas
    assert not dock.windowIcon().isNull()
    if should_use_custom_dock_title_bar():
        assert dock.titleBarWidget() is not None
        assert dock.titleBarWidget().objectName() == "DockTitleBar"
    else:
        assert dock.titleBarWidget() is None
    assert dock.widget().objectName() == "MetadataInspectorDockContent"

    exposure_row = _row_for_key(dock._effective_table, "camera_settings.exposure_us")
    iris_row = _row_for_key(dock._effective_table, "instrument.optics.iris.position")

    exposure_source = dock._effective_table.cellWidget(exposure_row, 2)
    iris_source = dock._effective_table.cellWidget(iris_row, 2)

    assert exposure_source.text() == "Inherited"
    assert iris_source.text() == "Local"
    assert dock._effective_table.item(exposure_row, 3).text() == "camera-a"
    assert dock._effective_table.item(iris_row, 3).text() == "This node"
    assert dock._local_table.rowCount() == 1


def test_metadata_inspector_dock_hides_advanced_actions_behind_menu(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, _camera_root, _session_root, session_node_id = (
        _make_workspace_with_metadata(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )

    dock = window._metadata_inspector_dock

    assert not dock._advanced_button.isHidden()
    assert dock._add_field_button.isHidden()
    assert dock._add_group_button.isHidden()
    assert dock._apply_template_button.isHidden()
    assert dock._promote_field_button.isHidden()
    assert dock._demote_field_button.isHidden()
    assert dock._advanced_button.toolTip()
    assert dock._advanced_promote_action.toolTip()
    assert dock._advanced_demote_action.toolTip()


def test_metadata_inspector_dock_saves_local_metadata_and_refreshes_host_scope(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, session_root, session_node_id = (
        _make_trials_workspace_with_metadata(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "trials",
        active_node_id=session_node_id,
    )

    dock = window._metadata_inspector_dock
    dock._add_local_row()
    new_row = dock._local_table.rowCount() - 1
    dock._local_table.item(new_row, 0).setText("custom.operator")
    dock._local_table.item(new_row, 1).setText("maxime")
    dock._save_local_metadata()

    saved = load_nodecard(session_root)
    assert saved.metadata["workflow"]["conditions"] == "dry"
    assert saved.metadata["custom"]["operator"] == "maxime"
    assert window.dataset_state.scope_effective_metadata["custom.operator"] == "maxime"


def test_metadata_inspector_dock_respects_governance_and_applies_template(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, _camera_root, session_root, session_node_id = (
        _make_workspace_with_metadata(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )

    dock = window._metadata_inspector_dock
    dock._apply_template()
    saved = load_nodecard(session_root)

    assert dock._add_field_button.isEnabled()
    assert dock._add_group_button.isEnabled()
    assert dock._group_status_layout.count() > 1
    assert dock._add_field_button.toolTip()
    assert dock._apply_template_button.toolTip()
    assert dock._promote_field_button.toolTip()
    assert dock._demote_field_button.toolTip()
    assert saved.metadata["instrument"]["optics"]["iris"]["position"] == 5
    assert saved.metadata["workflow"]["operator"] == ""


def test_metadata_inspector_effective_table_widens_source_column_for_chip_text(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, _camera_root, _session_root, session_node_id = (
        _make_workspace_with_metadata(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )

    dock = window._metadata_inspector_dock
    exposure_row = _row_for_key(dock._effective_table, "camera_settings.exposure_us")
    source_chip = dock._effective_table.cellWidget(exposure_row, 2)

    assert source_chip is not None
    assert dock._effective_table.columnWidth(2) >= source_chip.sizeHint().width()


def test_metadata_inspector_dock_lists_acquisition_datacard_fields_and_override_state(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, _session_root, acquisition_root, _session_node_id = (
        _make_workspace_with_acquisition_datacard(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(str(workspace_root), "calibration")
    acquisition_node_id = window.workflow_state_controller.resolve_node_id_for_path(
        acquisition_root,
    )
    assert acquisition_node_id is not None
    window.set_active_workflow_node(acquisition_node_id)

    dock = window._metadata_inspector_dock
    exposure_row = _row_for_key(dock._effective_table, "camera_settings.exposure_us")
    iris_row = _row_for_key(dock._effective_table, "instrument.optics.iris.position")

    assert dock._effective_table.item(exposure_row, 1).text() == ""
    assert dock._effective_table.cellWidget(exposure_row, 2).text() == "Override"
    assert dock._effective_table.item(iris_row, 1).text() == "3.5"
    assert dock._effective_table.cellWidget(iris_row, 2).text() == "Datacard"


def test_metadata_inspector_remove_selected_deletes_override_backed_field_from_acquisition(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, _session_root, acquisition_root, _session_node_id = (
        _make_workspace_with_acquisition_datacard(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(str(workspace_root), "calibration")
    acquisition_node_id = window.workflow_state_controller.resolve_node_id_for_path(
        acquisition_root,
    )
    assert acquisition_node_id is not None
    window.set_active_workflow_node(acquisition_node_id)

    dock = window._metadata_inspector_dock
    exposure_row = _row_for_key(dock._effective_table, "camera_settings.exposure_us")
    dock._effective_table.setCurrentCell(exposure_row, 0)

    assert dock._panel._remove_field_button.isEnabled()
    dock._panel._remove_selected_rows()

    saved_datacard = json.loads(
        (acquisition_root / "acquisition_datacard.json").read_text(encoding="utf-8"),
    )
    assert (
        saved_datacard.get("defaults", {})
        .get("camera_settings", {})
        .get("exposure_us")
        is None
    )
    assert all(
        "exposure_us"
        not in row.get("changes", {}).get("camera_settings", {})
        for row in saved_datacard.get("overrides", [])
    )
    with pytest.raises(AssertionError):
        _row_for_key(dock._effective_table, "camera_settings.exposure_us")


def test_metadata_field_move_transfers_datacard_default_to_session_node(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, session_root, acquisition_root, session_node_id = (
        _make_workspace_with_acquisition_datacard(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(str(workspace_root), "calibration")
    acquisition_node_id = window.workflow_state_controller.resolve_node_id_for_path(
        acquisition_root,
    )
    assert acquisition_node_id is not None
    window.set_active_workflow_node(acquisition_node_id)

    dock = window._metadata_inspector_dock
    iris_row = _row_for_key(dock._effective_table, "instrument.optics.iris.position")
    dock._effective_table.setCurrentCell(iris_row, 0)
    payload = dock._panel._drag_payload_for_selected_field()

    assert payload is not None
    assert payload["storage_kind"] == "acquisition_datacard_defaults"
    assert window._move_metadata_field_to_workflow_node_payload(payload, session_node_id)

    saved_session = load_nodecard(session_root)
    saved_datacard = json.loads(
        (acquisition_root / "acquisition_datacard.json").read_text(encoding="utf-8"),
    )

    assert saved_session.metadata["instrument"]["optics"]["iris"]["position"] == 3.5
    assert (
        saved_datacard["defaults"]
        .get("instrument", {})
        .get("optics", {})
        .get("iris", {})
        .get("position")
        is None
    )


def test_metadata_field_move_transfers_session_field_to_acquisition_node_storage(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, session_root, acquisition_root, session_node_id = (
        _make_workspace_with_acquisition_datacard(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )
    acquisition_node_id = window.workflow_state_controller.resolve_node_id_for_path(
        acquisition_root,
    )
    assert acquisition_node_id is not None

    dock = window._metadata_inspector_dock
    operator_row = _row_for_key(dock._effective_table, "workflow.operator")
    dock._effective_table.setCurrentCell(operator_row, 0)
    payload = dock._panel._drag_payload_for_selected_field()

    assert payload is not None
    assert payload["storage_kind"] == "nodecard"
    assert window._move_metadata_field_to_workflow_node_payload(payload, acquisition_node_id)

    saved_session = load_nodecard(session_root)
    saved_acquisition = load_nodecard(acquisition_root)

    assert "workflow" not in saved_session.metadata or "operator" not in saved_session.metadata.get(
        "workflow",
        {},
    )
    assert saved_acquisition.metadata["workflow"]["operator"] == "maxime"


def test_metadata_inspector_dock_allows_trials_ad_hoc_group_creation(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
) -> None:
    workspace_root, _session_root, session_node_id = _make_trials_workspace_with_metadata(
        tmp_path,
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "trials",
        active_node_id=session_node_id,
    )
    dock = window._metadata_inspector_dock
    responses = iter(
        [
            ("Field Ops", True),
            ("Wind Note", True),
        ],
    )
    monkeypatch.setattr(
        qtw.QInputDialog,
        "getText",
        lambda *args, **kwargs: next(responses),
    )

    dock._add_ad_hoc_group()

    assert dock._add_field_button.isEnabled()
    assert dock._add_group_button.isEnabled()
    assert dock._local_table.item(dock._local_table.rowCount() - 1, 0).text() == (
        "field_ops.wind_note"
    )


def test_metadata_inspector_dock_visibility_restores_from_ui_state(
    tmp_path: Path,
    monkeypatch,
    qapp,
) -> None:
    config_path = tmp_path / "ui_state.ini"
    store = UiStateStore(config_path)
    store.save(
        UiStateSnapshot(
            panel_states={MetadataInspectorDock.PANEL_STATE_KEY: False},
        ),
    )
    monkeypatch.setattr(
        window_module,
        "UiStateStore",
        lambda: UiStateStore(config_path),
    )

    window = window_module.FrameLabWindow(enabled_plugin_ids=())
    try:
        assert not window._metadata_inspector_dock.isVisible()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_metadata_inspector_stays_hidden_on_start_when_workflow_restores_without_panel_state(
    tmp_path: Path,
    monkeypatch,
    qapp,
) -> None:
    config_path = tmp_path / "ui_state.ini"
    workspace_root, _camera_root, _session_root, session_node_id = (
        _make_workspace_with_metadata(tmp_path)
    )
    store = UiStateStore(config_path)
    store.save(
        UiStateSnapshot(
            workflow_workspace_root=str(workspace_root),
            workflow_profile_id="calibration",
            workflow_anchor_type_id="root",
            workflow_active_node_id=session_node_id,
        ),
    )
    monkeypatch.setattr(
        window_module,
        "UiStateStore",
        lambda: UiStateStore(config_path),
    )

    window = window_module.FrameLabWindow(enabled_plugin_ids=())
    try:
        assert window.workflow_state_controller.profile_id == "calibration"
        assert not window._metadata_inspector_dock.isVisible()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()

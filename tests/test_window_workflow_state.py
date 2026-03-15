"""Window-level tests for persisted workflow controller state."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PySide6 import QtWidgets as qtw
from tifffile import imwrite

import framelab.window as window_module
from framelab.ui_primitives import StatusChip
from framelab.ui_settings import UiStateSnapshot, UiStateStore


pytestmark = [pytest.mark.ui, pytest.mark.core]


def _write_json(path: Path, payload: dict) -> None:
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


def _write_acquisition_datacard(acquisition_root: Path) -> None:
    _write_json(
        acquisition_root / "acquisition_datacard.json",
        {
            "schema_version": "1.0",
            "entity": "acquisition",
            "identity": {"acquisition_id": acquisition_root.name},
            "paths": {"frames_dir": "frames"},
            "defaults": {},
            "overrides": [],
            "quality": {},
            "external_sources": {},
        },
    )


def _write_frame(path: Path, value: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    imwrite(path, np.full((4, 4), value, dtype=np.uint16))


def _make_calibration_workspace(tmp_path: Path) -> tuple[Path, str]:
    workspace_root = tmp_path / "calibration"
    session_root = (
        workspace_root
        / "camera-a"
        / "campaign-2026"
        / "2026-03-05__sess01"
    )
    acquisitions_root = session_root / "acquisitions"
    acquisitions_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)

    first = acquisitions_root / "acq-0011__dark"
    (first / "frames").mkdir(parents=True, exist_ok=True)
    _write_acquisition_datacard(first)

    second = acquisitions_root / "acq-0012__bright"
    (second / "frames").mkdir(parents=True, exist_ok=True)
    _write_acquisition_datacard(second)

    return (
        workspace_root,
        (
            "calibration:acquisition:"
            "camera-a/campaign-2026/2026-03-05__sess01/acquisitions/acq-0012__bright"
        ),
    )


def _make_calibration_workspace_with_frames(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, str, str]:
    workspace_root = tmp_path / "calibration"
    session_root = (
        workspace_root
        / "camera-a"
        / "campaign-2026"
        / "2026-03-05__sess01"
    )
    acquisitions_root = session_root / "acquisitions"
    acquisitions_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)

    first = acquisitions_root / "acq-0011__dark"
    first.mkdir(parents=True, exist_ok=True)
    _write_acquisition_datacard(first)
    _write_frame(first / "frames" / "f0.tiff", 10)

    second = acquisitions_root / "acq-0012__bright"
    second.mkdir(parents=True, exist_ok=True)
    _write_acquisition_datacard(second)
    _write_frame(second / "frames" / "f0.tiff", 20)

    session_node_id = (
        "calibration:session:"
        "camera-a/campaign-2026/2026-03-05__sess01"
    )
    acquisition_node_id = (
        "calibration:acquisition:"
        "camera-a/campaign-2026/2026-03-05__sess01/acquisitions/acq-0011__dark"
    )
    return (
        workspace_root,
        session_root,
        first,
        second,
        session_node_id,
        acquisition_node_id,
    )


def test_window_restores_and_saves_workflow_context(
    tmp_path: Path,
    monkeypatch,
    qapp,
) -> None:
    config_path = tmp_path / "ui_state.ini"
    workspace_root, active_node_id = _make_calibration_workspace(tmp_path)
    store = UiStateStore(config_path)
    store.save(
        UiStateSnapshot(
            workflow_workspace_root=str(workspace_root),
            workflow_profile_id="calibration",
            workflow_anchor_type_id="root",
            workflow_active_node_id=active_node_id,
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
        assert window.workflow_state_controller.active_node_id == active_node_id
        assert window.metadata_state_controller.resolve_active_node_metadata() is not None
        assert (
            window.metadata_state_controller.resolve_active_node_metadata().schema.profile_id
            == "calibration"
        )

        window.set_active_workflow_node(window.workflow_state_controller.root_node_id)
        window._save_ui_state()
        reloaded = store.load()

        assert reloaded.workflow_workspace_root == str(workspace_root)
        assert reloaded.workflow_profile_id == "calibration"
        assert reloaded.workflow_anchor_type_id == "root"
        assert reloaded.workflow_active_node_id == "calibration:root"
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_window_restores_partial_workflow_anchor_from_saved_state(
    tmp_path: Path,
    monkeypatch,
    qapp,
) -> None:
    config_path = tmp_path / "ui_state.ini"
    (
        _workspace_root,
        session_root,
        first,
        _second,
        _session_node_id,
        _acquisition_node_id,
    ) = _make_calibration_workspace_with_frames(tmp_path)
    partial_acquisition_node_id = "calibration:acquisition:acquisitions/acq-0011__dark"
    store = UiStateStore(config_path)
    store.save(
        UiStateSnapshot(
            workflow_workspace_root=str(session_root),
            workflow_profile_id="calibration",
            workflow_anchor_type_id="session",
            workflow_active_node_id=partial_acquisition_node_id,
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
        assert window.workflow_state_controller.anchor_type_id == "session"
        assert window.workflow_state_controller.root_node_id == "calibration:session"
        assert window.workflow_state_controller.active_node_id == partial_acquisition_node_id
        assert window.folder_edit.text() == str(first.resolve())

        window._save_ui_state()
        reloaded = store.load()

        assert reloaded.workflow_workspace_root == str(session_root)
        assert reloaded.workflow_profile_id == "calibration"
        assert reloaded.workflow_anchor_type_id == "session"
        assert reloaded.workflow_active_node_id == partial_acquisition_node_id
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_set_workflow_context_syncs_folder_edit_and_scope_snapshot(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, session_root, _first, _second, session_node_id, _acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())

    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )

    assert window.folder_edit.text() == str(session_root.resolve())
    assert window.dataset_state.scope_snapshot.source == "workflow"
    assert window.dataset_state.scope_snapshot.kind == "session"
    assert window.dataset_state.scope_snapshot.workflow_profile_id == "calibration"
    assert window.dataset_state.scope_snapshot.workflow_anchor_type_id == "root"
    assert not window.dataset_state.scope_snapshot.workflow_is_partial
    assert window.dataset_state.scope_snapshot.active_node_id == session_node_id
    assert [node.type_id for node in window.dataset_state.scope_snapshot.ancestor_chain] == [
        "root",
        "camera",
        "campaign",
        "session",
    ]
    assert window.recent_workflow_entries()[0].workspace_root == str(workspace_root.resolve())
    assert window.recent_workflow_entries()[0].profile_id == "calibration"
    assert window.recent_workflow_entries()[0].anchor_type_id == "root"
    assert window.recent_workflow_entries()[0].active_node_id == session_node_id


def test_workflow_shell_breadcrumb_reflects_active_context(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
) -> None:
    workspace_root, session_root, _first, _second, session_node_id, _acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    config_path = tmp_path / "ui_state.ini"
    monkeypatch.setattr(
        window_module,
        "UiStateStore",
        lambda: UiStateStore(config_path),
    )
    window = framelab_window_factory(enabled_plugin_ids=())

    empty_chips = [
        chip.text()
        for chip in window._workflow_context_breadcrumb.findChildren(StatusChip)
    ]
    assert empty_chips == ["No workflow selected"]

    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )

    texts = [
        chip.text()
        for chip in window._workflow_context_breadcrumb.findChildren(StatusChip)
    ]
    assert texts[0] == "Calibration"
    assert texts[-1] == session_root.name


def test_partial_workflow_shell_breadcrumb_shows_anchor_scope(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    (
        _workspace_root,
        session_root,
        _first,
        _second,
        _session_node_id,
        acquisition_node_id,
    ) = _make_calibration_workspace_with_frames(tmp_path)
    window = framelab_window_factory(enabled_plugin_ids=())

    window.set_workflow_context(
        str(session_root),
        "calibration",
        anchor_type_id="session",
        active_node_id="calibration:acquisition:acquisitions/acq-0011__dark",
    )

    texts = [
        chip.text()
        for chip in window._workflow_context_breadcrumb.findChildren(StatusChip)
    ]
    assert texts[:3] == ["Calibration", "Session subtree", session_root.name]
    assert texts[-1] == "acq-0011__dark"
    assert window.dataset_state.scope_summary_value() == (
        "Acquisition: acq-0011__dark (Session subtree)"
    )


def test_load_folder_uses_active_workflow_scope_and_resolves_entered_child_node(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, session_root, first, _second, session_node_id, acquisition_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )

    window.load_folder()
    assert window.dataset_state.dataset_root == session_root.resolve()
    assert window.dataset_state.path_count() == 2
    assert window.dataset_state.scope_snapshot.active_node_id == session_node_id

    window.folder_edit.setText(str(first / "frames"))
    window.load_folder()

    assert window.workflow_state_controller.active_node_id == acquisition_node_id
    assert window.dataset_state.dataset_root == first.resolve()
    assert window.dataset_state.path_count() == 1
    assert window.folder_edit.text() == str(first.resolve())


def test_workflow_context_reframes_folder_actions_as_scope_actions(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, session_root, _first, _second, session_node_id, _acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=(), show=True)

    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )

    assert window.file_open_folder_action.text() == "Browse Scope Folder..."
    assert window.file_scan_scope_action.text() == "Scan Selected Scope"
    assert window.toolbar_open_action.text() == "Browse Scope Folder..."
    assert window.toolbar_scan_action.text() == "Scan Selected Scope"
    assert window._data_scope_label.text() == "Scope"
    assert window._data_browse_button.text() == "Browse Scope..."
    assert window._data_load_button.text() == "Scan Selected Scope"
    assert window.folder_edit.text() == str(session_root.resolve())


def test_window_can_rename_acquisition_from_workflow_structure_tools(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
) -> None:
    workspace_root, _session_root, _first, second, _session_node_id, _acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    second_node_id = (
        "calibration:acquisition:"
        "camera-a/campaign-2026/2026-03-05__sess01/acquisitions/acq-0012__bright"
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=second_node_id,
    )
    monkeypatch.setattr(
        qtw.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("renamed", True),
    )

    window._rename_workflow_acquisition(second_node_id)

    renamed_root = second.with_name("acq-0012__renamed")
    renamed_node_id = (
        "calibration:acquisition:"
        "camera-a/campaign-2026/2026-03-05__sess01/acquisitions/acq-0012__renamed"
    )
    assert renamed_root.is_dir()
    assert not second.exists()
    assert window.workflow_state_controller.active_node_id == renamed_node_id
    assert window.folder_edit.text() == str(renamed_root.resolve())


def test_window_can_delete_acquisition_from_workflow_structure_tools(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
) -> None:
    workspace_root, session_root, _first, second, session_node_id, _acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    second_node_id = (
        "calibration:acquisition:"
        "camera-a/campaign-2026/2026-03-05__sess01/acquisitions/acq-0012__bright"
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=second_node_id,
    )
    window.load_folder()
    monkeypatch.setattr(
        qtw.QMessageBox,
        "question",
        lambda *args, **kwargs: qtw.QMessageBox.Yes,
    )

    window._delete_workflow_acquisition(second_node_id)

    assert not second.exists()
    assert window.workflow_state_controller.active_node_id == session_node_id
    assert window.folder_edit.text() == str(session_root.resolve())
    assert not window.dataset_state.has_loaded_data()


def test_window_workflow_session_delete_defaults_confirmation_to_no(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
) -> None:
    workspace_root, session_root, _first, _second, session_node_id, _acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )
    captured: dict[str, object] = {}

    def _fake_question(*args, **kwargs):
        captured["default"] = args[4] if len(args) > 4 else kwargs.get("defaultButton")
        return qtw.QMessageBox.No

    monkeypatch.setattr(qtw.QMessageBox, "question", _fake_question)

    window._delete_workflow_session(session_node_id)

    assert captured["default"] == qtw.QMessageBox.No
    assert session_root.exists()
    assert window.workflow_state_controller.active_node_id == session_node_id


def test_window_can_create_and_delete_session_from_workflow_structure_tools(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
) -> None:
    workspace_root, session_root, _first, _second, _session_node_id, _acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    campaign_node_id = "calibration:campaign:camera-a/campaign-2026"
    created_node_id = "calibration:session:camera-a/campaign-2026/2026-03-06__sess02"
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=campaign_node_id,
    )

    created_root = window._create_workflow_session(campaign_node_id, "2026-03-06__sess02")

    assert created_root == session_root.parent / "2026-03-06__sess02"
    assert created_root is not None and created_root.is_dir()
    assert window.workflow_state_controller.active_node_id == created_node_id
    assert window.folder_edit.text() == str(created_root.resolve())

    monkeypatch.setattr(
        qtw.QMessageBox,
        "question",
        lambda *args, **kwargs: qtw.QMessageBox.Yes,
    )

    window._delete_workflow_session(created_node_id)

    assert created_root is not None and not created_root.exists()
    assert window.workflow_state_controller.active_node_id == campaign_node_id


def test_window_can_reindex_session_from_workflow_structure_tools(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
) -> None:
    workspace_root, session_root, first, second, session_node_id, _acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )
    monkeypatch.setattr(
        qtw.QInputDialog,
        "getInt",
        lambda *args, **kwargs: (21, True),
    )
    monkeypatch.setattr(
        qtw.QMessageBox,
        "question",
        lambda *args, **kwargs: qtw.QMessageBox.Yes,
    )

    window._reindex_workflow_session(session_node_id)

    assert not first.exists()
    assert not second.exists()
    assert (session_root / "acquisitions" / "acq-0021__dark").is_dir()
    assert (session_root / "acquisitions" / "acq-0022__bright").is_dir()
    assert window.workflow_state_controller.active_node_id == session_node_id

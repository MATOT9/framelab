from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PySide6 import QtWidgets as qtw
from PySide6.QtCore import Qt
from tifffile import imwrite

import framelab.acquisition_authoring_dialog as acquisition_authoring_dialog_module
from framelab.workflow_manager_dialog import WorkflowManagerDialog


pytestmark = [pytest.mark.ui, pytest.mark.data]


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


def _make_workspace(tmp_path: Path) -> tuple[Path, Path, Path, str, str]:
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

    acquisition_root = acquisitions_root / "acq-0011__dark"
    acquisition_root.mkdir(parents=True, exist_ok=True)
    _write_acquisition_datacard(acquisition_root)
    _write_frame(acquisition_root / "frames" / "f0.tiff", 10)

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
        acquisition_root,
        session_node_id,
        acquisition_node_id,
    )


def test_workflow_manager_loads_workspace_into_host(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, session_root, _acquisition_root, session_node_id, _acquisition_node_id = (
        _make_workspace(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())

    dialog = WorkflowManagerDialog(window)
    assert dialog.windowTitle() == "Workflow Tools"
    assert dialog._load_button.text() == "Rebind Workflow"
    assert dialog._metadata_button.text() == "Reveal Metadata Inspector"
    assert isinstance(dialog._structure_button, qtw.QPushButton)
    assert dialog._structure_button.text() == "Structure..."
    assert dialog.windowFlags() & Qt.WindowMaximizeButtonHint
    dialog._workspace_edit.setText(str(workspace_root))
    dialog._profile_combo.setCurrentIndex(dialog._profile_combo.findData("calibration"))
    dialog._load_workflow()

    assert window.workflow_state_controller.profile_id == "calibration"
    assert window.workflow_state_controller.active_node_id == "calibration:root"
    assert dialog._item_by_node_id[session_node_id].text(0) == session_root.name


def test_workflow_manager_sets_active_node_scope(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, _session_root, acquisition_root, session_node_id, acquisition_node_id = (
        _make_workspace(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )

    window._open_workflow_manager_dialog()
    dialog = window._workflow_manager_dialog
    assert isinstance(dialog, WorkflowManagerDialog)

    item = dialog._item_by_node_id[acquisition_node_id]
    dialog._tree.setCurrentItem(item)
    dialog._set_selected_node_active()

    assert window.workflow_state_controller.active_node_id == acquisition_node_id
    assert window.folder_edit.text() == str(acquisition_root.resolve())
    assert window.dataset_state.scope_snapshot.active_node_id == acquisition_node_id


def test_workflow_manager_batch_create_adds_acquisitions_under_session(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
) -> None:
    workspace_root, session_root, _acquisition_root, session_node_id, _acquisition_node_id = (
        _make_workspace(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )
    dialog = WorkflowManagerDialog(window)

    def _fake_exec(self) -> int:
        self._mode_combo.setCurrentIndex(self._mode_combo.findData("batch"))
        self._starting_number_spin.setValue(12)
        self._count_spin.setValue(2)
        self._labels_edit.setPlainText("flat\nbright")
        self._accept_creation()
        return qtw.QDialog.Accepted

    try:
        monkeypatch.setattr(
            acquisition_authoring_dialog_module.AcquisitionAuthoringDialog,
            "exec",
            _fake_exec,
        )
        dialog._tree.setCurrentItem(dialog._item_by_node_id[session_node_id])
        dialog._batch_create_acquisitions()

        assert (session_root / "acquisitions" / "acq-0012__flat").is_dir()
        assert (session_root / "acquisitions" / "acq-0013__bright").is_dir()
        assert dialog._structure_button.isEnabled()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_workflow_manager_structure_button_opens_menu(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
) -> None:
    workspace_root, _session_root, _acquisition_root, session_node_id, _acquisition_node_id = (
        _make_workspace(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )
    dialog = WorkflowManagerDialog(window)
    opened: list[object] = []

    try:
        monkeypatch.setattr(
            dialog._structure_menu,
            "popup",
            lambda point: opened.append(point),
        )
        dialog._show_structure_menu()

        assert opened
    finally:
        dialog.close()
        dialog.deleteLater()

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from tifffile import imwrite
from PySide6 import QtWidgets as qtw
from PySide6.QtCore import Qt

from framelab.ui_settings import RecentWorkflowEntry
from framelab.workflow_selection_dialog import WorkflowSelectionDialog


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


def _make_workspace(tmp_path: Path) -> tuple[Path, Path, str, str]:
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

    session_node_id = "calibration:session"
    full_session_node_id = (
        "calibration:session:"
        "camera-a/campaign-2026/2026-03-05__sess01"
    )
    return workspace_root, session_root, session_node_id, full_session_node_id


def test_workflow_selection_dialog_loads_recent_context(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, session_root, session_node_id, _full_session_node_id = _make_workspace(
        tmp_path,
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.ui_state_snapshot.recent_workflows = [
        RecentWorkflowEntry(
            workspace_root=str(session_root.resolve()),
            profile_id="calibration",
            anchor_type_id="session",
            active_node_id=session_node_id,
        ),
    ]

    dialog = WorkflowSelectionDialog(window)
    item = dialog._recent_list.item(0)
    dialog._recent_list.setCurrentItem(item)
    dialog._load_selected_workflow()

    assert dialog.result() == qtw.QDialog.Accepted
    assert window.workflow_state_controller.profile_id == "calibration"
    assert window.workflow_state_controller.anchor_type_id == "session"
    assert window.workflow_state_controller.active_node_id == session_node_id
    assert window.folder_edit.text() == str(session_root.resolve())


def test_workflow_selection_dialog_can_open_explicit_session_subtree(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, session_root, session_node_id, _full_session_node_id = _make_workspace(
        tmp_path,
    )
    window = framelab_window_factory(enabled_plugin_ids=())

    dialog = WorkflowSelectionDialog(window)
    profile_index = dialog._profile_combo.findData("calibration")
    dialog._profile_combo.setCurrentIndex(profile_index)
    dialog._workspace_edit.setText(str(session_root))
    anchor_index = dialog._anchor_combo.findData("session")
    dialog._anchor_combo.setCurrentIndex(anchor_index)
    dialog._load_selected_workflow()

    assert dialog.result() == qtw.QDialog.Accepted
    assert window.workflow_state_controller.profile_id == "calibration"
    assert window.workflow_state_controller.anchor_type_id == "session"
    assert window.workflow_state_controller.root_node_id == "calibration:session"
    assert window.workflow_state_controller.active_node_id == session_node_id


def test_workflow_selection_dialog_can_clear_current_workflow(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, _session_root, _session_node_id, full_session_node_id = _make_workspace(
        tmp_path,
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=full_session_node_id,
    )

    dialog = WorkflowSelectionDialog(window)
    dialog._clear_workflow()

    assert dialog.result() == qtw.QDialog.Accepted
    assert window.workflow_state_controller.profile_id is None
    assert window.workflow_state_controller.active_node_id is None


def test_workflow_selection_dialog_supports_drag_and_maximize(
    framelab_window_factory,
) -> None:
    window = framelab_window_factory(enabled_plugin_ids=())
    dialog = WorkflowSelectionDialog(window)

    assert dialog.windowFlags() & Qt.Window
    assert dialog.windowFlags() & Qt.WindowMaximizeButtonHint
    assert getattr(dialog, "_window_drag_controller", None) is not None


def test_workflow_selection_dialog_warns_for_folder_above_workspace_root(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
) -> None:
    workspace_root, _session_root, _session_node_id, _full_session_node_id = _make_workspace(
        tmp_path,
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    dialog = WorkflowSelectionDialog(window)
    dialog._profile_combo.setCurrentIndex(dialog._profile_combo.findData("calibration"))
    dialog._workspace_edit.setText(str(workspace_root.parent))

    captured: list[str] = []
    monkeypatch.setattr(
        qtw.QMessageBox,
        "warning",
        lambda _parent, _title, message: captured.append(message),
    )

    dialog._load_selected_workflow()

    assert captured
    assert "full workspace root" in captured[0].lower()
    assert window.workflow_state_controller.profile_id is None

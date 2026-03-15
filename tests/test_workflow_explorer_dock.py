from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PySide6 import QtWidgets as qtw
from PySide6.QtCore import Qt
from tifffile import imwrite

import framelab.acquisition_authoring_dialog as acquisition_authoring_dialog_module
import framelab.window as window_module
from framelab.ui_settings import UiStateSnapshot, UiStateStore
from framelab.workflow_explorer_dock import WorkflowExplorerDock


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


def _make_invalid_numbering_workspace(tmp_path: Path) -> tuple[Path, str]:
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
    for name in ("acq-0011__dark", "acq-0013__bright"):
        acquisition_root = acquisitions_root / name
        acquisition_root.mkdir(parents=True, exist_ok=True)
        _write_acquisition_datacard(acquisition_root)
    session_node_id = (
        "calibration:session:"
        "camera-a/campaign-2026/2026-03-05__sess01"
    )
    return workspace_root, session_node_id


def _make_large_workspace(tmp_path: Path, count: int = 18) -> tuple[Path, str]:
    workspace_root = tmp_path / "calibration"
    last_acquisition_node_id = ""
    for index in range(count):
        camera_root = workspace_root / f"camera-{index:02d}"
        session_root = camera_root / "campaign-2026" / f"2026-03-05__sess{index:02d}"
        acquisitions_root = session_root / "acquisitions"
        acquisitions_root.mkdir(parents=True, exist_ok=True)
        _write_session_datacard(session_root)
        acquisition_root = acquisitions_root / f"acq-{index + 1:04d}__dark"
        acquisition_root.mkdir(parents=True, exist_ok=True)
        _write_acquisition_datacard(acquisition_root)
        _write_frame(acquisition_root / "frames" / "f0.tiff", index)
        last_acquisition_node_id = (
            "calibration:acquisition:"
            f"camera-{index:02d}/campaign-2026/2026-03-05__sess{index:02d}/"
            f"acquisitions/acq-{index + 1:04d}__dark"
        )
    return workspace_root, last_acquisition_node_id


def _make_workspace_with_session_container(tmp_path: Path) -> tuple[Path, Path, str]:
    workspace_root = tmp_path / "calibration"
    campaign_root = workspace_root / "camera-a" / "campaign-2026"
    sessions_root = campaign_root / "01_sessions"
    session_root = sessions_root / "2026-03-05__sess01"
    acquisitions_root = session_root / "acquisitions"
    acquisitions_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)
    acquisition_root = acquisitions_root / "acq-0011__dark"
    acquisition_root.mkdir(parents=True, exist_ok=True)
    _write_acquisition_datacard(acquisition_root)
    _write_frame(acquisition_root / "frames" / "f0.tiff", 10)
    campaign_node_id = "calibration:campaign:camera-a/campaign-2026"
    return workspace_root, campaign_root, campaign_node_id


def test_workflow_explorer_dock_selection_updates_active_scope(
    tmp_path: Path,
    framelab_window_factory,
    process_events,
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

    dock = window._workflow_explorer_dock
    assert isinstance(dock, WorkflowExplorerDock)
    assert dock.features() & qtw.QDockWidget.DockWidgetFloatable
    assert dock.allowedAreas() == Qt.AllDockWidgetAreas
    assert not dock.windowIcon().isNull()
    assert dock.titleBarWidget() is not None
    assert dock.titleBarWidget().objectName() == "DockTitleBar"
    assert dock._tree.header().sectionResizeMode(0) == qtw.QHeaderView.Interactive

    item = dock._item_by_node_id[acquisition_node_id]
    dock._tree.setCurrentItem(item)
    process_events()

    assert window.workflow_state_controller.active_node_id == acquisition_node_id
    assert window.folder_edit.text() == str(acquisition_root.resolve())
    assert window.dataset_state.scope_snapshot.active_node_id == acquisition_node_id
    assert dock._lineage_rail.entry_labels()[-1] == acquisition_root.name


def test_workflow_explorer_dock_visibility_restores_from_ui_state(
    tmp_path: Path,
    monkeypatch,
    qapp,
) -> None:
    config_path = tmp_path / "ui_state.ini"
    store = UiStateStore(config_path)
    store.save(
        UiStateSnapshot(
            panel_states={WorkflowExplorerDock.PANEL_STATE_KEY: False},
        ),
    )
    monkeypatch.setattr(
        window_module,
        "UiStateStore",
        lambda: UiStateStore(config_path),
    )

    window = window_module.FrameLabWindow(enabled_plugin_ids=())
    try:
        assert not window._workflow_explorer_dock.isVisible()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_workflow_explorer_dock_can_create_acquisition_for_selected_session(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
    process_events,
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
    dock = window._workflow_explorer_dock

    def _fake_exec(self) -> int:
        self._labels_edit.setPlainText("flat")
        self._accept_creation()
        return qtw.QDialog.Accepted

    monkeypatch.setattr(
        acquisition_authoring_dialog_module.AcquisitionAuthoringDialog,
        "exec",
        _fake_exec,
    )

    dock._tree.setCurrentItem(dock._item_by_node_id[session_node_id])
    process_events()
    dock._new_acquisition()
    process_events()

    created_root = session_root / "acquisitions" / "acq-0012__flat"
    created_node_id = (
        "calibration:acquisition:"
        "camera-a/campaign-2026/2026-03-05__sess01/acquisitions/acq-0012__flat"
    )
    assert created_root.is_dir()
    assert window.workflow_state_controller.active_node_id == created_node_id
    assert window.folder_edit.text() == str(created_root.resolve())
    assert created_node_id in dock._item_by_node_id


def test_workflow_explorer_dock_surfaces_structure_warning_for_invalid_numbering(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, session_node_id = _make_invalid_numbering_workspace(tmp_path)
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )
    dock = window._workflow_explorer_dock

    assert not dock._new_acquisition_action.isEnabled()
    assert not dock._batch_create_action.isEnabled()
    assert "not contiguous" in dock._warning_label.text().lower()
    assert "not contiguous" in dock._structure_button.toolTip().lower()


def test_workflow_explorer_dock_preserves_scroll_position_on_selection(
    tmp_path: Path,
    framelab_window_factory,
    process_events,
) -> None:
    workspace_root, last_acquisition_node_id = _make_large_workspace(tmp_path)
    window = framelab_window_factory(
        enabled_plugin_ids=(),
        show=True,
        width=1400,
        height=900,
    )
    window.set_workflow_context(str(workspace_root), "calibration")
    dock = window._workflow_explorer_dock
    dock.show()
    dock._tree.expandAll()
    process_events()

    scrollbar = dock._tree.verticalScrollBar()
    assert scrollbar.maximum() > 0
    scrollbar.setValue(scrollbar.maximum())
    process_events()
    before = scrollbar.value()

    dock._tree.setCurrentItem(dock._item_by_node_id[last_acquisition_node_id])
    process_events()

    assert scrollbar.value() >= max(0, before - 5)


def test_workflow_explorer_dock_does_not_rebuild_tree_for_selection_only(
    tmp_path: Path,
    framelab_window_factory,
    process_events,
) -> None:
    workspace_root, _session_root, _acquisition_root, session_node_id, acquisition_node_id = (
        _make_workspace(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )
    dock = window._workflow_explorer_dock
    original_item = dock._item_by_node_id[acquisition_node_id]

    dock._tree.setCurrentItem(original_item)
    process_events()

    assert dock._item_by_node_id[acquisition_node_id] is original_item


def test_workflow_explorer_dock_creates_session_inline_under_campaign_root(
    tmp_path: Path,
    framelab_window_factory,
    process_events,
) -> None:
    workspace_root, _session_root, _acquisition_root, _session_node_id, _acquisition_node_id = (
        _make_workspace(tmp_path)
    )
    campaign_node_id = "calibration:campaign:camera-a/campaign-2026"
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(str(workspace_root), "calibration", active_node_id=campaign_node_id)
    dock = window._workflow_explorer_dock

    dock._begin_inline_session_creation(campaign_node_id)
    assert dock._pending_session_editor is not None
    dock._pending_session_editor.setText("2026-03-06__sess02")
    dock._finalize_pending_session_creation()
    process_events()

    created_root = workspace_root / "camera-a" / "campaign-2026" / "2026-03-06__sess02"
    created_node_id = "calibration:session:camera-a/campaign-2026/2026-03-06__sess02"
    assert created_root.is_dir()
    assert window.workflow_state_controller.active_node_id == created_node_id
    assert created_node_id in dock._item_by_node_id


def test_workflow_explorer_dock_creates_session_inline_inside_nested_session_container(
    tmp_path: Path,
    framelab_window_factory,
    process_events,
) -> None:
    workspace_root, campaign_root, campaign_node_id = _make_workspace_with_session_container(
        tmp_path,
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(str(workspace_root), "calibration", active_node_id=campaign_node_id)
    dock = window._workflow_explorer_dock

    dock._begin_inline_session_creation(campaign_node_id)
    assert dock._pending_session_editor is not None
    dock._pending_session_editor.setText("2026-03-06__sess02")
    dock._finalize_pending_session_creation()
    process_events()

    created_root = campaign_root / "01_sessions" / "2026-03-06__sess02"
    assert created_root.is_dir()


def test_workflow_explorer_dock_cancels_empty_inline_session_creation(
    tmp_path: Path,
    framelab_window_factory,
    process_events,
) -> None:
    workspace_root, _session_root, _acquisition_root, _session_node_id, _acquisition_node_id = (
        _make_workspace(tmp_path)
    )
    campaign_node_id = "calibration:campaign:camera-a/campaign-2026"
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(str(workspace_root), "calibration", active_node_id=campaign_node_id)
    dock = window._workflow_explorer_dock

    dock._begin_inline_session_creation(campaign_node_id)
    assert dock._pending_session_editor is not None
    dock._pending_session_editor.setText("   ")
    dock._finalize_pending_session_creation()
    process_events()

    assert not (workspace_root / "camera-a" / "campaign-2026" / "   ").exists()
    assert dock._pending_session_editor is None

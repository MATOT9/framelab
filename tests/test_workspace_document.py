"""Workspace-document persistence and restore tests."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from tifffile import imwrite

import framelab.window as window_module
from framelab.ui_settings import UiStateStore
from framelab.workspace_document import (
    WorkspaceDocumentBackgroundState,
    WorkspaceDocumentDatasetState,
    WorkspaceDocumentMeasureState,
    WorkspaceDocumentSnapshot,
    WorkspaceDocumentStore,
    WorkspaceDocumentUiState,
    WorkspaceDocumentWorkflowState,
)


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


def _make_workspace_with_frames(
    tmp_path: Path,
) -> tuple[Path, Path, str, list[Path]]:
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

    frame_paths: list[Path] = []
    for acquisition_name, value in (
        ("acq-0011__dark", 10),
        ("acq-0012__bright", 20),
    ):
        acquisition_root = acquisitions_root / acquisition_name
        acquisition_root.mkdir(parents=True, exist_ok=True)
        _write_acquisition_datacard(acquisition_root)
        frame_path = acquisition_root / "frames" / "f0.tiff"
        _write_frame(frame_path, value)
        frame_paths.append(frame_path.resolve())

    session_node_id = (
        "calibration:session:"
        "camera-a/campaign-2026/2026-03-05__sess01"
    )
    return (workspace_root, session_root, session_node_id, frame_paths)


def test_workspace_document_store_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "example.framelab"
    store = WorkspaceDocumentStore()
    snapshot = WorkspaceDocumentSnapshot(
        workflow=WorkspaceDocumentWorkflowState(
            workspace_root="/tmp/workspace",
            profile_id="calibration",
            anchor_type_id="root",
            active_node_id="node-1",
        ),
        dataset=WorkspaceDocumentDatasetState(
            scope_source="workflow",
            scan_root="/tmp/workspace/session",
            selected_image_path="/tmp/workspace/session/frame.tiff",
        ),
        measure=WorkspaceDocumentMeasureState(
            average_mode="roi",
            threshold_value=1234.0,
            avg_count_value=55,
            rounding_mode="std",
            normalize_intensity_values=True,
            roi_rect=(1, 2, 3, 4),
            roi_applied_to_all=True,
        ),
        background=WorkspaceDocumentBackgroundState(
            enabled=True,
            source_mode="single_file",
            clip_negative=False,
            exposure_policy="require_match",
            no_match_policy="fallback_raw",
            source_path="/tmp/background.tiff",
        ),
        ui=WorkspaceDocumentUiState(
            active_page="measure",
            analysis_plugin_id="plugin-a",
            show_image_preview=False,
            show_histogram_preview=True,
            panel_states={"workflow.explorer_dock": True},
            splitter_sizes={"measure.main_splitter": [300, 700]},
        ),
    )

    saved_path = store.save(path, snapshot)
    loaded = store.load(saved_path)

    assert saved_path.suffix == ".framelab"
    assert loaded.workflow.workspace_root == "/tmp/workspace"
    assert loaded.measure.roi_rect == (1, 2, 3, 4)
    assert loaded.measure.roi_applied_to_all is True
    assert loaded.background.source_path == "/tmp/background.tiff"
    assert loaded.ui.splitter_sizes["measure.main_splitter"] == [300, 700]


def test_workspace_document_dirty_state_tracks_saved_session(
    tmp_path: Path,
    monkeypatch,
    framelab_window_factory,
) -> None:
    config_path = tmp_path / "ui_state.ini"
    monkeypatch.setattr(
        window_module,
        "UiStateStore",
        lambda: UiStateStore(config_path),
    )

    window = framelab_window_factory(enabled_plugin_ids=())
    save_path = tmp_path / "session_state.framelab"

    assert window._save_workspace_document_to_path(save_path)
    assert window._workspace_document_dirty is False
    assert window.windowTitle().endswith("session_state.framelab")

    window._on_view_hist_action_toggled(True)
    assert window._workspace_document_dirty is True
    assert window.windowTitle().endswith("session_state.framelab*")

    window._on_view_hist_action_toggled(False)
    assert window._workspace_document_dirty is False
    assert window.windowTitle().endswith("session_state.framelab")


def test_window_actions_restore_workspace_document_session(
    tmp_path: Path,
    monkeypatch,
    framelab_window_factory,
) -> None:
    config_path = tmp_path / "ui_state.ini"
    monkeypatch.setattr(
        window_module,
        "UiStateStore",
        lambda: UiStateStore(config_path),
    )

    workspace_root, session_root, session_node_id, frame_paths = (
        _make_workspace_with_frames(tmp_path)
    )
    background_path = tmp_path / "background.tiff"
    imwrite(background_path, np.full((4, 4), 2, dtype=np.uint16))
    document_path = tmp_path / "restorable_session.framelab"

    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )
    window.load_folder()

    roi_index = window.avg_mode_combo.findData("roi")
    window.avg_mode_combo.setCurrentIndex(roi_index)
    window.threshold_spin.setValue(42)
    window._apply_live_update()
    window._on_normalize_intensity_toggled(True)
    window._set_rounding_mode("std")
    window.show_histogram_preview = True
    window._on_preview_visibility_changed()
    window._on_background_enabled_toggled(True)
    assert window._load_background_reference(
        source_text=str(background_path),
        mode="single_file",
    )
    assert window._apply_roi_rect_to_current_dataset((0, 0, 2, 2), status_message=None)
    window.metrics_state.roi_applied_to_all = True
    second_index = window.dataset_state.paths.index(str(frame_paths[1]))
    window.dataset_state.set_selected_index(
        second_index,
        path_count=window.dataset_state.path_count(),
    )
    window._set_table_current_source_row(second_index)
    window._display_image(second_index)
    window.workflow_tabs.setCurrentIndex(1)

    monkeypatch.setattr(
        window,
        "_select_workspace_document_path_to_save",
        lambda: document_path,
    )
    window.file_save_workspace_as_action.trigger()
    assert document_path.exists()
    assert window._workspace_document_dirty is False

    restored = framelab_window_factory(enabled_plugin_ids=())
    roi_apply_calls: list[bool] = []
    monkeypatch.setattr(
        restored,
        "_start_roi_apply_job",
        lambda: roi_apply_calls.append(True),
    )
    monkeypatch.setattr(
        restored,
        "_maybe_save_workspace_document_before_destructive_action",
        lambda: True,
    )
    monkeypatch.setattr(
        restored,
        "_select_workspace_document_path_to_open",
        lambda: document_path,
    )
    restored.file_open_workspace_action.trigger()

    assert restored.workflow_state_controller.profile_id == "calibration"
    assert restored.workflow_state_controller.active_node_id == session_node_id
    assert restored.dataset_state.dataset_root == session_root.resolve()
    assert restored._current_average_mode() == "roi"
    assert restored.metrics_state.threshold_value == pytest.approx(42.0)
    assert restored.metrics_state.normalize_intensity_values is True
    assert restored.metrics_state.rounding_mode == "std"
    assert restored.metrics_state.roi_rect == (0, 0, 2, 2)
    assert restored.metrics_state.background_config.enabled is True
    assert restored.metrics_state.background_source_text == str(background_path)
    assert restored.metrics_state.background_library.global_ref is not None
    assert restored.show_histogram_preview is True
    assert restored.dataset_state.selected_index == second_index
    assert restored.dataset_state.paths[second_index] == str(frame_paths[1])
    assert restored.workflow_tabs.currentIndex() == 1
    assert roi_apply_calls == [True]
    assert restored._workspace_document_dirty is False
    assert restored.windowTitle().endswith("restorable_session.framelab")


def test_open_workspace_document_reports_missing_paths_once(
    tmp_path: Path,
    monkeypatch,
    framelab_window_factory,
) -> None:
    config_path = tmp_path / "ui_state.ini"
    monkeypatch.setattr(
        window_module,
        "UiStateStore",
        lambda: UiStateStore(config_path),
    )

    missing_doc = tmp_path / "missing_paths.framelab"
    store = WorkspaceDocumentStore()
    store.save(
        missing_doc,
        WorkspaceDocumentSnapshot(
            workflow=WorkspaceDocumentWorkflowState(
                workspace_root=str(tmp_path / "missing-workspace"),
                profile_id="calibration",
            ),
            dataset=WorkspaceDocumentDatasetState(
                scope_source="manual",
                scan_root=str(tmp_path / "missing-scan-root"),
            ),
            background=WorkspaceDocumentBackgroundState(
                enabled=True,
                source_mode="single_file",
                source_path=str(tmp_path / "missing-background.tiff"),
            ),
        ),
    )

    window = framelab_window_factory(enabled_plugin_ids=())
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        window,
        "_show_info",
        lambda title, message: messages.append((title, message)),
    )

    assert window._open_workspace_document(missing_doc) is True
    assert len(messages) == 1
    assert "missing-workspace" in messages[0][1]
    assert "missing-scan-root" in messages[0][1]
    assert "missing-background.tiff" in messages[0][1]

"""Tests for workflow profiles and controller-backed tree loading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from framelab.node_metadata import save_nodecard
from framelab.workflow import WorkflowStateController, workflow_profile_by_id


pytestmark = [pytest.mark.core, pytest.mark.data]


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _write_session_datacard(
    session_root: Path,
    *,
    acquisitions_root_rel: str | None = None,
) -> None:
    _write_json(
        session_root / "session_datacard.json",
        {
            "schema_version": "1.0",
            "entity": "session",
            "identity": {"label": session_root.name},
            "paths": {
                "session_root_rel": None,
                "acquisitions_root_rel": acquisitions_root_rel,
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


def _make_acquisition(parent: Path, name: str) -> Path:
    acquisition_root = parent / name
    (acquisition_root / "frames").mkdir(parents=True, exist_ok=True)
    (acquisition_root / "frames" / "f0.tiff").touch()
    _write_acquisition_datacard(acquisition_root)
    return acquisition_root


def test_built_in_profiles_cover_calibration_and_trials() -> None:
    calibration = workflow_profile_by_id("calibration")
    trials = workflow_profile_by_id("trials")
    custom = workflow_profile_by_id("custom")

    assert calibration is not None
    assert trials is not None
    assert custom is not None
    assert calibration.node_type("root").child_type_ids == ("camera",)
    assert calibration.node_type("session").child_type_ids == ("acquisition",)
    assert trials.node_type("root").child_type_ids == ("year",)
    assert trials.node_type("year").child_type_ids == ("campaign",)
    assert trials.node_type("camera").child_type_ids == ("session",)
    assert trials.node_type("session").discovery_mode == "session_acquisitions"
    assert custom.node_type("root").child_type_ids == ()


def test_empty_root_nodecard_registers_structured_workspace_in_place(
    tmp_path: Path,
) -> None:
    calibration_root = tmp_path / "empty-calibration"
    trials_root = tmp_path / "empty-trials"
    calibration_root.mkdir()
    trials_root.mkdir()
    save_nodecard(
        calibration_root,
        {},
        profile_id="calibration",
        node_type_id="root",
    )
    save_nodecard(
        trials_root,
        {},
        profile_id="trials",
        node_type_id="root",
    )

    controller = WorkflowStateController()

    assert controller.supports_load_path(
        calibration_root,
        "calibration",
        anchor_type_id="root",
    )
    assert controller.supports_load_path(
        trials_root,
        "trials",
        anchor_type_id="root",
    )
    assert controller.infer_anchor_type(calibration_root, "calibration") == "root"
    assert controller.infer_anchor_type(trials_root, "trials") == "root"


def test_controller_loads_calibration_workspace_with_session_acquisitions(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "calibration"
    session_root = (
        workspace_root
        / "camera-a"
        / "campaign-2026"
        / "2026-03-05__sess01"
    )
    acquisitions_root = session_root / "acquisitions"
    acquisitions_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root, acquisitions_root_rel="acquisitions")
    acquisition_one = _make_acquisition(acquisitions_root, "acq-0011__dark")
    acquisition_two = _make_acquisition(acquisitions_root, "acq-0012__bright")

    controller = WorkflowStateController()
    result = controller.load_workspace(workspace_root, "calibration")

    assert result.profile_id == "calibration"
    assert controller.root_node_id == "calibration:root"
    root_children = controller.children_of(controller.root_node_id)
    assert [node.type_id for node in root_children] == ["camera"]
    session_node_id = controller.resolve_node_id_for_path(session_root)
    assert session_node_id is not None
    session_children = controller.children_of(session_node_id)
    assert [node.type_id for node in session_children] == [
        "acquisition",
        "acquisition",
    ]
    assert [node.folder_path.name for node in session_children] == [
        "acq-0011__dark",
        "acq-0012__bright",
    ]
    file_node_id = controller.resolve_node_id_for_path(
        acquisition_two / "frames" / "f0.tiff",
    )
    assert file_node_id is not None
    ancestry = controller.ancestry_for(file_node_id)
    assert [node.type_id for node in ancestry] == [
        "root",
        "camera",
        "campaign",
        "session",
        "acquisition",
    ]
    assert ancestry[-1].folder_path == acquisition_two.resolve()
    assert controller.active_node_id == controller.root_node_id
    assert controller.node(file_node_id) is not None
    assert controller.resolve_node_id_for_path(acquisition_one) is not None


def test_controller_loads_trials_workspace_with_year_and_campaign_levels(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "trials"
    session_root = (
        workspace_root
        / "2026"
        / "campaign-07"
        / "camera-b"
        / "2026-03-05__sess02"
    )
    acquisitions_root = session_root / "acquisitions"
    acquisitions_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)
    acquisition_root = _make_acquisition(acquisitions_root, "acq-0001")

    controller = WorkflowStateController()
    acquisition_node_id = (
        "trials:acquisition:"
        "2026/campaign-07/camera-b/2026-03-05__sess02/acquisitions/acq-0001"
    )
    controller.load_workspace(
        workspace_root,
        "trials",
        active_node_id=acquisition_node_id,
    )

    assert controller.active_node_id == acquisition_node_id
    ancestry = controller.ancestry_for(controller.active_node_id)
    assert [node.type_id for node in ancestry] == [
        "root",
        "year",
        "campaign",
        "camera",
        "session",
        "acquisition",
    ]
    assert ancestry[-1].folder_path == acquisition_root.resolve()


def test_controller_infers_session_anchor_for_partial_session_root(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "calibration"
    session_root = workspace_root / "camera-a" / "campaign-2026" / "session-1"
    acquisitions_root = session_root / "acquisitions"
    acquisitions_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)
    acquisition_root = _make_acquisition(acquisitions_root, "acq-0001")

    controller = WorkflowStateController()

    assert controller.infer_anchor_type(session_root, "calibration") == "session"

    result = controller.load_workspace(session_root, "calibration")

    assert result.anchor_type_id == "session"
    assert controller.root_node_id == "calibration:session"
    assert controller.active_node_id == "calibration:session"
    assert controller.anchor_summary_label() == "Session subtree"
    acquisition_node_id = controller.resolve_node_id_for_path(acquisition_root)
    assert acquisition_node_id == "calibration:acquisition:acquisitions/acq-0001"
    assert [node.type_id for node in controller.ancestry_for(acquisition_node_id)] == [
        "session",
        "acquisition",
    ]


def test_controller_can_load_camera_subtree_with_explicit_anchor(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "calibration"
    session_root = workspace_root / "camera-a" / "campaign-2026" / "session-1"
    acquisitions_root = session_root / "acquisitions"
    acquisitions_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)
    _make_acquisition(acquisitions_root, "acq-0001")

    controller = WorkflowStateController()
    camera_root = workspace_root / "camera-a"
    result = controller.load_workspace(
        camera_root,
        "calibration",
        anchor_type_id="camera",
    )

    assert result.anchor_type_id == "camera"
    assert controller.root_node_id == "calibration:camera"
    assert controller.anchor_summary_label() == "Camera subtree"
    root_children = controller.children_of(controller.root_node_id)
    assert [node.type_id for node in root_children] == ["campaign"]
    session_node_id = controller.resolve_node_id_for_path(session_root)
    assert session_node_id == "calibration:session:campaign-2026/session-1"


def test_controller_falls_back_to_custom_for_unstructured_folder(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "loose-tiffs"
    folder.mkdir()
    (folder / "image_0001.tiff").touch()

    controller = WorkflowStateController()
    result = controller.load_workspace(folder, "calibration")

    assert result.profile_id == "custom"
    assert result.anchor_type_id == "root"
    assert controller.profile_id == "custom"
    assert controller.is_custom_workspace()
    assert controller.anchor_summary_label() == "Custom folder"
    assert controller.root_node_id == "custom:root"
    assert controller.active_node_id == "custom:root"
    assert result.warnings
    assert "custom workflow" in result.warnings[0].lower()


def test_refresh_preserves_active_node_when_workspace_changes(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "calibration"
    session_root = workspace_root / "cam-x" / "campaign-1" / "session-1"
    acquisitions_root = session_root / "acquisitions"
    acquisitions_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)
    _make_acquisition(acquisitions_root, "acq-0001")
    selected_acquisition = _make_acquisition(acquisitions_root, "acq-0002")

    controller = WorkflowStateController()
    selected_id = (
        "calibration:acquisition:"
        "cam-x/campaign-1/session-1/acquisitions/acq-0002"
    )
    controller.load_workspace(
        workspace_root,
        "calibration",
        active_node_id=selected_id,
    )

    _make_acquisition(acquisitions_root, "acq-0003")
    refreshed = controller.refresh()

    assert refreshed is not None
    assert controller.active_node_id == selected_id
    assert controller.node(selected_id) is not None
    assert controller.resolve_node_id_for_path(selected_acquisition) == selected_id
    assert refreshed.node_count == 7


def test_invalid_active_node_falls_back_to_root(tmp_path: Path) -> None:
    workspace_root = tmp_path / "calibration"
    session_root = workspace_root / "cam-z" / "campaign-z" / "session-z"
    acquisitions_root = session_root / "acquisitions"
    acquisitions_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)
    _make_acquisition(acquisitions_root, "acq-0001")

    controller = WorkflowStateController()
    controller.load_workspace(
        workspace_root,
        "calibration",
        active_node_id="calibration:acquisition:missing/path",
    )

    assert controller.active_node_id == controller.root_node_id


def test_controller_warns_and_falls_back_for_parent_folder_above_supported_workspace_root(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "calibration"
    session_root = workspace_root / "camera-a" / "campaign-2026" / "session-1"
    acquisitions_root = session_root / "acquisitions"
    acquisitions_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)
    _make_acquisition(acquisitions_root, "acq-0001")

    controller = WorkflowStateController()

    assert not controller.supports_load_path(tmp_path, "calibration")
    warning = controller.unsupported_load_message(tmp_path, "calibration")
    assert warning is not None
    assert "custom workflow" in warning.lower()

    result = controller.load_workspace(tmp_path, "calibration")

    assert result.profile_id == "custom"


def test_controller_loads_campaign_with_nested_01_sessions_container(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "calibration"
    campaign_root = workspace_root / "camera-a" / "campaign-2026"
    session_root = campaign_root / "01_sessions" / "2026-03-05__sess01"
    acquisitions_root = session_root / "acquisitions"
    acquisitions_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)
    acquisition_root = _make_acquisition(acquisitions_root, "acq-0001")

    controller = WorkflowStateController()
    controller.load_workspace(workspace_root, "calibration")

    campaign_node_id = "calibration:campaign:camera-a/campaign-2026"
    campaign_children = controller.children_of(campaign_node_id)
    assert [node.type_id for node in campaign_children] == ["session"]
    assert campaign_children[0].folder_path == session_root.resolve()
    assert controller.resolve_node_id_for_path(acquisition_root) is not None


def test_controller_treats_01_sessions_folder_as_campaign_anchor(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "calibration"
    campaign_root = workspace_root / "camera-a" / "campaign-2026"
    sessions_root = campaign_root / "01_sessions"
    session_root = sessions_root / "2026-03-05__sess01"
    acquisitions_root = session_root / "acquisitions"
    acquisitions_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)
    _make_acquisition(acquisitions_root, "acq-0001")

    controller = WorkflowStateController()

    assert controller.infer_anchor_type(sessions_root, "calibration") == "campaign"
    result = controller.load_workspace(sessions_root, "calibration")

    assert result.anchor_type_id == "campaign"
    assert controller.anchor_summary_label() == "Campaign subtree"
    root_children = controller.children_of(controller.root_node_id)
    assert [node.type_id for node in root_children] == ["session"]


def test_detect_supported_workspace_walks_up_from_frames_dir(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "trials"
    session_root = workspace_root / "2026" / "campaign-alpha" / "camera-a" / "session-1"
    acquisitions_root = session_root / "acquisitions"
    acquisition_root = acquisitions_root / "acq-0011__scene"
    frames_root = acquisition_root / "frames"
    frames_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)
    _make_acquisition(acquisitions_root, "acq-0012")

    controller = WorkflowStateController()
    detection = controller.detect_supported_workspace(frames_root)

    assert detection is not None
    assert detection.profile_id == "trials"
    assert detection.anchor_type_id == "acquisition"
    assert detection.workspace_root == acquisition_root.resolve()


def test_detect_supported_workspace_skips_inaccessible_campaign_children(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace_root = tmp_path / "calibration"
    campaign_root = workspace_root / "camera-a" / "campaign-2026"
    session_root = campaign_root / "2026-03-05__sess01"
    acquisitions_root = session_root / "acquisitions"
    acquisition_root = acquisitions_root / "acq-0011__scene"
    frames_root = acquisition_root / "frames"
    frames_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)
    _make_acquisition(acquisitions_root, "acq-0012")
    blocked_sessions_root = campaign_root / "01_sessions"
    blocked_sessions_root.mkdir(parents=True, exist_ok=True)

    original_iterdir = Path.iterdir
    blocked_text = str(blocked_sessions_root.resolve())

    def _guarded_iterdir(path: Path):
        if str(path.resolve(strict=False)) == blocked_text:
            raise PermissionError("access denied")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", _guarded_iterdir)

    controller = WorkflowStateController()
    detection = controller.detect_supported_workspace(frames_root)

    assert detection is not None
    assert detection.profile_id == "calibration"
    assert detection.anchor_type_id == "acquisition"
    assert detection.workspace_root == acquisition_root.resolve()

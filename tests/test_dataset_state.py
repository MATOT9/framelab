from __future__ import annotations

from pathlib import Path

import pytest

from framelab.dataset_state import DatasetScopeNode, DatasetStateController


pytestmark = [pytest.mark.fast, pytest.mark.core]


@pytest.fixture
def controller() -> DatasetStateController:
    return DatasetStateController()


def test_set_loaded_dataset_tracks_root_and_paths(
    controller: DatasetStateController,
) -> None:
    controller.set_path_metadata({"old": {"value": 1}})
    controller.set_metadata_visible_paths(["old"])

    controller.set_loaded_dataset(
        Path("/tmp/dataset"),
        ["/tmp/dataset/a.tif", "/tmp/dataset/b.tif"],
    )

    assert controller.dataset_root == Path("/tmp/dataset")
    assert controller.paths == ["/tmp/dataset/a.tif", "/tmp/dataset/b.tif"]
    assert controller.path_metadata == {}
    assert controller.metadata_visible_paths == []
    assert controller.has_loaded_data()


def test_clear_loaded_dataset_preserves_metadata_source_preferences(
    controller: DatasetStateController,
) -> None:
    controller.update_metadata_source_availability(True)
    controller.request_metadata_source_mode("path")
    controller.set_loaded_dataset("/tmp/dataset", ["/tmp/dataset/a.tif"])

    controller.clear_loaded_dataset()

    assert controller.dataset_root is None
    assert controller.paths == []
    assert controller.metadata_source_mode == "path"
    assert controller.preferred_metadata_source_mode == "path"
    assert not controller.has_loaded_data()


def test_json_availability_falls_back_then_restores_preferred_source(
    controller: DatasetStateController,
) -> None:
    active = controller.update_metadata_source_availability(True)
    assert active == "json"
    changed = controller.request_metadata_source_mode("json")
    assert not changed

    active = controller.update_metadata_source_availability(False)
    assert active == "path"
    assert controller.metadata_source_mode == "path"
    assert controller.preferred_metadata_source_mode == "json"

    active = controller.update_metadata_source_availability(True)
    assert active == "json"
    assert controller.metadata_source_mode == "json"


def test_request_metadata_source_mode_rejects_unavailable_json(
    controller: DatasetStateController,
) -> None:
    changed = controller.request_metadata_source_mode("json")

    assert changed
    assert controller.metadata_source_mode == "path"
    assert controller.preferred_metadata_source_mode == "path"


def test_set_selected_index_clamps_to_loaded_path_count(
    controller: DatasetStateController,
) -> None:
    selected = controller.set_selected_index(9, path_count=3)

    assert selected == 2
    assert controller.selected_index == 2


def test_clear_loaded_dataset_resets_selected_index(
    controller: DatasetStateController,
) -> None:
    controller.set_loaded_dataset("/tmp/dataset", ["/tmp/dataset/a.tif"])
    controller.set_selected_index(0, path_count=1)

    controller.clear_loaded_dataset()

    assert controller.selected_index is None


def test_visible_metadata_and_source_index_helpers_follow_loaded_paths(
    controller: DatasetStateController,
) -> None:
    controller.set_loaded_dataset(
        "/tmp/dataset",
        ["/tmp/dataset/a.tif", "/tmp/dataset/b.tif"],
    )
    controller.set_path_metadata(
        {
            "/tmp/dataset/a.tif": {"group": 1},
            "/tmp/dataset/b.tif": {"group": 2},
        },
    )
    controller.set_metadata_visible_paths(
        ["/tmp/dataset/b.tif", "/tmp/dataset/a.tif"],
    )

    assert controller.path_count() == 2
    assert controller.visible_metadata_path(0) == "/tmp/dataset/b.tif"
    assert controller.source_index_for_path("/tmp/dataset/b.tif") == 1
    assert controller.metadata_for_path("/tmp/dataset/a.tif") == {"group": 1}
    assert controller.visible_metadata_path(9) is None
    assert controller.source_index_for_path("/tmp/dataset/missing.tif") is None


def test_workflow_scope_snapshot_tracks_active_node_and_metadata_context(
    controller: DatasetStateController,
) -> None:
    snapshot = controller.set_workflow_scope(
        root="/tmp/workspace/camera-a/session-01",
        kind="session",
        label="Session 01",
        workflow_profile_id="calibration",
        workflow_anchor_type_id="root",
        workflow_anchor_label="Full workspace",
        workflow_anchor_path="/tmp/workspace",
        workflow_is_partial=False,
        active_node_id="calibration:session:camera-a/session-01",
        active_node_type="session",
        active_node_path="/tmp/workspace/camera-a/session-01",
        ancestor_chain=(
            DatasetScopeNode(
                node_id="calibration:root",
                type_id="root",
                display_name="Calibration",
                folder_path=Path("/tmp/workspace"),
            ),
            DatasetScopeNode(
                node_id="calibration:session:camera-a/session-01",
                type_id="session",
                display_name="Session 01",
                folder_path=Path("/tmp/workspace/camera-a/session-01"),
            ),
        ),
        effective_metadata={"camera_settings.exposure_us": 1200},
        metadata_sources={"camera_settings.exposure_us": "node_inherited"},
    )

    assert snapshot.source == "workflow"
    assert snapshot.kind == "session"
    assert snapshot.workflow_profile_id == "calibration"
    assert snapshot.workflow_anchor_type_id == "root"
    assert snapshot.workflow_anchor_path == Path("/tmp/workspace")
    assert not snapshot.workflow_is_partial
    assert snapshot.active_node_type == "session"
    assert snapshot.root == Path("/tmp/workspace/camera-a/session-01")
    assert controller.scope_effective_metadata == {"camera_settings.exposure_us": 1200}
    assert controller.scope_metadata_sources == {
        "camera_settings.exposure_us": "node_inherited",
    }
    assert controller.scope_summary_value() == "Session: Session 01"


def test_partial_workflow_scope_summary_mentions_anchor_subtree(
    controller: DatasetStateController,
) -> None:
    controller.set_workflow_scope(
        root="/tmp/workspace/camera-a/session-01",
        kind="acquisition",
        label="Acq 0001",
        workflow_profile_id="calibration",
        workflow_anchor_type_id="session",
        workflow_anchor_label="Session subtree",
        workflow_anchor_path="/tmp/workspace/camera-a/session-01",
        workflow_is_partial=True,
        active_node_id="calibration:acquisition:acq-0001",
        active_node_type="acquisition",
        active_node_path="/tmp/workspace/camera-a/session-01/acq-0001",
        ancestor_chain=(),
    )

    assert controller.scope_summary_value() == "Acquisition: Acq 0001 (Session subtree)"


def test_manual_scope_summary_uses_folder_label(controller: DatasetStateController) -> None:
    controller.set_manual_scope("/tmp/data/session-a")

    assert controller.scope_snapshot.source == "manual"
    assert controller.scope_snapshot.root == Path("/tmp/data/session-a")
    assert controller.scope_summary_value() == "Folder: session-a"

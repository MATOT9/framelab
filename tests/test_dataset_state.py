from __future__ import annotations

from pathlib import Path

import pytest

from framelab.dataset_state import DatasetStateController


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

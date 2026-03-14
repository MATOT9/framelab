from __future__ import annotations

from pathlib import Path
import unittest

from framelab.dataset_state import DatasetStateController


class DatasetStateControllerTests(unittest.TestCase):
    def test_set_loaded_dataset_tracks_root_and_paths(self) -> None:
        controller = DatasetStateController()
        controller.set_path_metadata({"old": {"value": 1}})
        controller.set_metadata_visible_paths(["old"])

        controller.set_loaded_dataset(
            Path("/tmp/dataset"),
            ["/tmp/dataset/a.tif", "/tmp/dataset/b.tif"],
        )

        self.assertEqual(controller.dataset_root, Path("/tmp/dataset"))
        self.assertEqual(
            controller.paths,
            ["/tmp/dataset/a.tif", "/tmp/dataset/b.tif"],
        )
        self.assertEqual(controller.path_metadata, {})
        self.assertEqual(controller.metadata_visible_paths, [])
        self.assertTrue(controller.has_loaded_data())

    def test_clear_loaded_dataset_preserves_metadata_source_preferences(self) -> None:
        controller = DatasetStateController()
        controller.update_metadata_source_availability(True)
        controller.request_metadata_source_mode("path")
        controller.set_loaded_dataset("/tmp/dataset", ["/tmp/dataset/a.tif"])

        controller.clear_loaded_dataset()

        self.assertIsNone(controller.dataset_root)
        self.assertEqual(controller.paths, [])
        self.assertEqual(controller.metadata_source_mode, "path")
        self.assertEqual(controller.preferred_metadata_source_mode, "path")
        self.assertFalse(controller.has_loaded_data())

    def test_json_availability_falls_back_then_restores_preferred_source(self) -> None:
        controller = DatasetStateController()

        active = controller.update_metadata_source_availability(True)
        self.assertEqual(active, "json")
        changed = controller.request_metadata_source_mode("json")
        self.assertFalse(changed)

        active = controller.update_metadata_source_availability(False)
        self.assertEqual(active, "path")
        self.assertEqual(controller.metadata_source_mode, "path")
        self.assertEqual(controller.preferred_metadata_source_mode, "json")

        active = controller.update_metadata_source_availability(True)
        self.assertEqual(active, "json")
        self.assertEqual(controller.metadata_source_mode, "json")

    def test_request_metadata_source_mode_rejects_unavailable_json(self) -> None:
        controller = DatasetStateController()

        changed = controller.request_metadata_source_mode("json")

        self.assertTrue(changed)
        self.assertEqual(controller.metadata_source_mode, "path")
        self.assertEqual(controller.preferred_metadata_source_mode, "path")

    def test_set_selected_index_clamps_to_loaded_path_count(self) -> None:
        controller = DatasetStateController()

        selected = controller.set_selected_index(9, path_count=3)

        self.assertEqual(selected, 2)
        self.assertEqual(controller.selected_index, 2)

    def test_clear_loaded_dataset_resets_selected_index(self) -> None:
        controller = DatasetStateController()
        controller.set_loaded_dataset("/tmp/dataset", ["/tmp/dataset/a.tif"])
        controller.set_selected_index(0, path_count=1)

        controller.clear_loaded_dataset()

        self.assertIsNone(controller.selected_index)

    def test_visible_metadata_and_source_index_helpers_follow_loaded_paths(self) -> None:
        controller = DatasetStateController()
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

        self.assertEqual(controller.path_count(), 2)
        self.assertEqual(
            controller.visible_metadata_path(0),
            "/tmp/dataset/b.tif",
        )
        self.assertEqual(
            controller.source_index_for_path("/tmp/dataset/b.tif"),
            1,
        )
        self.assertEqual(
            controller.metadata_for_path("/tmp/dataset/a.tif"),
            {"group": 1},
        )
        self.assertIsNone(controller.visible_metadata_path(9))
        self.assertIsNone(controller.source_index_for_path("/tmp/dataset/missing.tif"))


if __name__ == "__main__":
    unittest.main()

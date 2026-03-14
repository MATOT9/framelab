from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from framelab.metadata import clear_metadata_cache, extract_path_metadata


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _campaign_payload(
    *,
    instrument_defaults: dict | None = None,
    campaign_defaults: dict | None = None,
) -> dict:
    return {
        "schema_version": "1.0",
        "entity": "campaign",
        "identity": {
            "camera_id": None,
            "campaign_id": "campaign",
            "timezone": None,
            "created_at_local": None,
            "closed_at_local": None,
            "status": "active",
            "label": "campaign",
        },
        "intent": {
            "description": "",
            "tags": [],
            "deliverables": [],
        },
        "instrument_defaults": instrument_defaults or {},
        "campaign_defaults": campaign_defaults or {},
        "high_level_changes": [],
        "outputs_index": {},
        "paths": {},
        "host_pc": {},
    }


def _session_payload(*, session_defaults: dict | None = None) -> dict:
    return {
        "schema_version": "1.0",
        "entity": "session",
        "identity": {
            "camera_id": None,
            "campaign_id": None,
            "session_id": "session",
            "date_local": None,
            "sess_number": None,
            "start_time_local": None,
            "end_time_local": None,
            "timezone": None,
            "label": "session",
        },
        "paths": {
            "session_root_rel": None,
            "acquisitions_root_rel": None,
            "notes_rel": None,
        },
        "session_defaults": session_defaults or {},
        "notes": "",
    }


def _acquisition_payload(
    *,
    defaults: dict | None = None,
    overrides: list[dict] | None = None,
    frames_dir: str = "frames",
) -> dict:
    return {
        "schema_version": "1.0",
        "entity": "acquisition",
        "identity": {
            "camera_id": None,
            "campaign_id": None,
            "session_id": None,
            "acquisition_id": None,
            "label": None,
            "created_at_local": None,
            "finalized_at_local": None,
            "timezone": None,
        },
        "paths": {"frames_dir": frames_dir},
        "intent": {
            "capture_type": "calibration",
            "subtype": "test",
            "scene": "flat",
            "tags": ["test"],
        },
        "defaults": defaults
        if defaults is not None
        else {
            "camera_settings": {},
            "instrument": {},
            "acquisition_settings": {},
        },
        "overrides": overrides or [],
        "quality": {
            "anomalies": [],
            "dropped_frames": [],
            "saturation_expected": False,
        },
    }


class MetadataResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_metadata_cache()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.repo = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        clear_metadata_cache()

    def _frame_path(
        self,
        *,
        campaign: bool = False,
        session: bool = False,
        acquisition: bool = True,
        acquisition_name: str = "acq-0011__test",
        frames_dir: str = "frames",
        frame_name: str = "f0.tiff",
    ) -> Path:
        root = self.repo
        if campaign:
            root = root / "campaign"
        if session:
            root = root / "01_sessions" / "2026-03-05__sess01"
        if acquisition:
            root = root / "acquisitions" / acquisition_name
        frames_root = root / frames_dir
        frames_root.mkdir(parents=True, exist_ok=True)
        frame_path = frames_root / frame_name
        frame_path.touch()
        return frame_path

    def _write_campaign(self, root: Path, **kwargs: object) -> None:
        _write_json(root / "campaign_datacard.json", _campaign_payload(**kwargs))

    def _write_session(self, root: Path, **kwargs: object) -> None:
        _write_json(root / "session_datacard.json", _session_payload(**kwargs))

    def _write_acquisition(self, root: Path, **kwargs: object) -> None:
        _write_json(
            root / "acquisition_datacard.json",
            _acquisition_payload(**kwargs),
        )

    def test_campaign_session_and_acquisition_defaults_layer_in_order(self) -> None:
        frame = self._frame_path(campaign=True, session=True)
        campaign_root = self.repo / "campaign"
        session_root = campaign_root / "01_sessions" / "2026-03-05__sess01"
        acquisition_root = session_root / "acquisitions" / "acq-0011__test"

        self._write_campaign(
            campaign_root,
            instrument_defaults={"optics": {"iris": {"position": 2}}},
            campaign_defaults={"camera_settings": {"exposure_us": 1000}},
        )
        self._write_session(
            session_root,
            session_defaults={"camera_settings": {"exposure_us": 1500}},
        )
        self._write_acquisition(
            acquisition_root,
            defaults={
                "camera_settings": {"exposure_us": 2000},
                "instrument": {},
                "acquisition_settings": {},
            },
        )

        metadata = extract_path_metadata(str(frame), metadata_source="json")
        self.assertEqual(metadata.get("exposure_source"), "acquisition_default")
        self.assertAlmostEqual(float(metadata["exposure_ms"]), 2.0)
        self.assertEqual(metadata.get("iris_source"), "campaign_default")
        self.assertEqual(float(metadata["iris_position"]), 2.0)

    def test_none_in_higher_layer_does_not_erase_inherited_value(self) -> None:
        frame = self._frame_path(campaign=True, session=True)
        campaign_root = self.repo / "campaign"
        session_root = campaign_root / "01_sessions" / "2026-03-05__sess01"
        acquisition_root = session_root / "acquisitions" / "acq-0011__test"

        self._write_campaign(
            campaign_root,
            campaign_defaults={"camera_settings": {"exposure_us": 1000}},
        )
        self._write_session(
            session_root,
            session_defaults={"camera_settings": {"exposure_us": None}},
        )
        self._write_acquisition(
            acquisition_root,
            defaults={
                "camera_settings": {},
                "instrument": {},
                "acquisition_settings": {},
            },
        )

        metadata = extract_path_metadata(str(frame), metadata_source="json")
        self.assertEqual(metadata.get("exposure_source"), "campaign_default")
        self.assertAlmostEqual(float(metadata["exposure_ms"]), 1.0)

    def test_matching_override_replaces_only_targeted_fields(self) -> None:
        frame = self._frame_path(frame_name="f0.tiff")
        acquisition_root = self.repo / "acquisitions" / "acq-0011__test"
        self._write_acquisition(
            acquisition_root,
            defaults={
                "camera_settings": {"exposure_us": 1000},
                "instrument": {"optics": {"iris": {"position": 4}}},
                "acquisition_settings": {},
            },
            overrides=[
                {
                    "selector": {"frame_range": [0, 0]},
                    "changes": {"camera_settings": {"exposure_us": 2500}},
                    "reason": "frame override",
                },
            ],
        )

        metadata = extract_path_metadata(str(frame), metadata_source="json")
        self.assertTrue(bool(metadata.get("frame_override_matched")))
        self.assertEqual(metadata.get("exposure_source"), "frame_override")
        self.assertAlmostEqual(float(metadata["exposure_ms"]), 2.5)
        self.assertEqual(metadata.get("iris_source"), "acquisition_default")
        self.assertEqual(float(metadata["iris_position"]), 4.0)

    def test_non_matching_override_falls_back_to_baseline(self) -> None:
        frame0 = self._frame_path(frame_name="f0.tiff")
        frame1 = self._frame_path(frame_name="f1.tiff")
        acquisition_root = self.repo / "acquisitions" / "acq-0011__test"
        self._write_acquisition(
            acquisition_root,
            defaults={
                "camera_settings": {"exposure_us": 1000},
                "instrument": {},
                "acquisition_settings": {},
            },
            overrides=[
                {
                    "selector": {"frame_range": [0, 0]},
                    "changes": {"camera_settings": {"exposure_us": 2500}},
                    "reason": "frame override",
                },
            ],
        )

        metadata0 = extract_path_metadata(str(frame0), metadata_source="json")
        metadata1 = extract_path_metadata(str(frame1), metadata_source="json")
        self.assertEqual(metadata0.get("frame_link_mode"), "frame_index")
        self.assertEqual(metadata1.get("frame_link_mode"), "frame_index_no_override")
        self.assertEqual(metadata1.get("exposure_source"), "acquisition_default")
        self.assertAlmostEqual(float(metadata1["exposure_ms"]), 1.0)

    def test_one_based_override_selectors_apply_for_filename_order_datasets(self) -> None:
        frame1 = self._frame_path(frame_name="frame_a.tiff")
        frame2 = self._frame_path(frame_name="frame_b.tiff")
        acquisition_root = self.repo / "acquisitions" / "acq-0011__test"
        self._write_acquisition(
            acquisition_root,
            defaults={
                "camera_settings": {"exposure_us": 1000},
                "instrument": {},
                "acquisition_settings": {},
            },
            overrides=[
                {
                    "selector": {"frame_range": [1, 2]},
                    "changes": {"camera_settings": {"exposure_us": 3000}},
                    "reason": "one-based override",
                },
            ],
        )

        metadata1 = extract_path_metadata(str(frame1), metadata_source="json")
        metadata2 = extract_path_metadata(str(frame2), metadata_source="json")
        self.assertEqual(int(metadata1["override_index_base_detected"]), 1)
        self.assertEqual(metadata1.get("exposure_source"), "frame_override")
        self.assertEqual(metadata2.get("exposure_source"), "frame_override")

    def test_json_source_can_mix_datacard_values_with_path_fallback(self) -> None:
        frame = self._frame_path(frame_name="exp_7ms_iris2.tiff")
        acquisition_root = self.repo / "acquisitions" / "acq-0011__test"
        self._write_acquisition(
            acquisition_root,
            defaults={
                "camera_settings": {"exposure_us": 1000},
                "instrument": {},
                "acquisition_settings": {},
            },
        )

        metadata = extract_path_metadata(str(frame), metadata_source="json")
        self.assertEqual(metadata.get("exposure_source"), "acquisition_default")
        self.assertAlmostEqual(float(metadata["exposure_ms"]), 1.0)
        self.assertEqual(metadata.get("iris_source"), "path_fallback")
        self.assertAlmostEqual(float(metadata["iris_position"]), 2.0)

    def test_json_source_uses_path_fallback_and_none_when_no_json_value_exists(self) -> None:
        fallback_frame = self._frame_path(
            acquisition=False,
            frame_name="exp_12ms_iris5.tiff",
        )
        missing_frame = self._frame_path(
            acquisition=False,
            frame_name="plain_image.tiff",
        )

        fallback_metadata = extract_path_metadata(
            str(fallback_frame),
            metadata_source="json",
        )
        missing_metadata = extract_path_metadata(
            str(missing_frame),
            metadata_source="json",
        )

        self.assertEqual(fallback_metadata.get("exposure_source"), "path_fallback")
        self.assertEqual(fallback_metadata.get("iris_source"), "path_fallback")
        self.assertAlmostEqual(float(fallback_metadata["exposure_ms"]), 12.0)
        self.assertAlmostEqual(float(fallback_metadata["iris_position"]), 5.0)
        self.assertEqual(missing_metadata.get("exposure_source"), "none")
        self.assertEqual(missing_metadata.get("iris_source"), "none")
        self.assertNotIn("exposure_ms", missing_metadata)
        self.assertNotIn("iris_position", missing_metadata)

    def test_path_source_uses_path_provenance_even_inside_json_backed_acquisition(self) -> None:
        frame = self._frame_path(frame_name="exp_7ms_iris2.tiff")
        acquisition_root = self.repo / "acquisitions" / "acq-0011__test"
        self._write_acquisition(
            acquisition_root,
            defaults={
                "camera_settings": {"exposure_us": 1000},
                "instrument": {"optics": {"iris": {"position": 9}}},
                "acquisition_settings": {},
            },
        )

        metadata = extract_path_metadata(str(frame), metadata_source="path")
        self.assertEqual(metadata.get("exposure_source"), "path")
        self.assertEqual(metadata.get("iris_source"), "path")
        self.assertAlmostEqual(float(metadata["exposure_ms"]), 7.0)
        self.assertAlmostEqual(float(metadata["iris_position"]), 2.0)

    def test_session_and_campaign_defaults_apply_without_acquisition_datacard(self) -> None:
        frame = self._frame_path(
            campaign=True,
            session=True,
            acquisition=True,
            acquisition_name="acq-0011__test",
        )
        campaign_root = self.repo / "campaign"
        session_root = campaign_root / "01_sessions" / "2026-03-05__sess01"

        self._write_campaign(
            campaign_root,
            campaign_defaults={"camera_settings": {"exposure_us": 800}},
        )
        self._write_session(
            session_root,
            session_defaults={
                "instrument": {"optics": {"iris": {"position": 6}}},
            },
        )

        metadata = extract_path_metadata(str(frame), metadata_source="json")
        self.assertTrue(bool(metadata.get("json_metadata_available")))
        self.assertEqual(metadata.get("exposure_source"), "campaign_default")
        self.assertEqual(metadata.get("iris_source"), "session_default")
        self.assertAlmostEqual(float(metadata["exposure_ms"]), 0.8)
        self.assertAlmostEqual(float(metadata["iris_position"]), 6.0)

    def test_malformed_acquisition_datacard_falls_back_to_session_defaults(self) -> None:
        frame = self._frame_path(campaign=True, session=True)
        campaign_root = self.repo / "campaign"
        session_root = campaign_root / "01_sessions" / "2026-03-05__sess01"
        acquisition_root = session_root / "acquisitions" / "acq-0011__test"

        self._write_campaign(campaign_root)
        self._write_session(
            session_root,
            session_defaults={"camera_settings": {"exposure_us": 1200}},
        )
        _write_text(acquisition_root / "acquisition_datacard.json", "{ invalid json")

        metadata = extract_path_metadata(str(frame), metadata_source="json")
        self.assertTrue(bool(metadata.get("json_metadata_available")))
        self.assertEqual(metadata.get("exposure_source"), "session_default")
        self.assertAlmostEqual(float(metadata["exposure_ms"]), 1.2)

    def test_unknown_default_fields_do_not_contaminate_known_metadata(self) -> None:
        frame = self._frame_path()
        acquisition_root = self.repo / "acquisitions" / "acq-0011__test"
        self._write_acquisition(
            acquisition_root,
            defaults={
                "camera_settings": {"exposure_us": 1000},
                "instrument": {},
                "acquisition_settings": {},
                "unknown_block": {"mystery": 123},
            },
        )

        metadata = extract_path_metadata(str(frame), metadata_source="json")
        self.assertEqual(metadata.get("exposure_source"), "acquisition_default")
        self.assertAlmostEqual(float(metadata["exposure_ms"]), 1.0)
        self.assertNotIn("unknown_block.mystery", metadata)

    def test_frame_index_mode_reports_filename_index(self) -> None:
        frame = self._frame_path(frame_name="f3.tiff")
        acquisition_root = self.repo / "acquisitions" / "acq-0011__test"
        self._write_acquisition(acquisition_root)

        metadata = extract_path_metadata(str(frame), metadata_source="json")
        self.assertEqual(metadata.get("frame_naming"), "f_index")
        self.assertEqual(metadata.get("frame_index_mode"), "filename_index")
        self.assertEqual(int(metadata["frame_index"]), 3)

    def test_frame_index_mode_reports_ebus_index_and_timestamp_fields(self) -> None:
        frame = self._frame_path(frame_name="7_0000002A.tiff")
        acquisition_root = self.repo / "acquisitions" / "acq-0011__test"
        self._write_acquisition(acquisition_root)

        metadata = extract_path_metadata(str(frame), metadata_source="json")
        self.assertEqual(metadata.get("frame_naming"), "ebus_index_timestamp")
        self.assertEqual(metadata.get("frame_index_mode"), "ebus_index")
        self.assertEqual(int(metadata["frame_index"]), 7)
        self.assertEqual(metadata.get("ebus_timestamp_hex"), "0000002A")
        self.assertEqual(int(metadata["ebus_timestamp_ms"]), 42)

    def test_frame_index_mode_reports_ebus_timestamp_order_when_indices_repeat(self) -> None:
        frame_a = self._frame_path(frame_name="0_0000000B.tiff")
        self._frame_path(frame_name="0_0000000A.tiff")
        acquisition_root = self.repo / "acquisitions" / "acq-0011__test"
        self._write_acquisition(acquisition_root)

        metadata_a = extract_path_metadata(str(frame_a), metadata_source="json")
        self.assertEqual(metadata_a.get("frame_index_mode"), "ebus_timestamp_order")
        self.assertEqual(int(metadata_a["frame_index"]), 1)

    def test_frame_link_mode_is_path_only_when_file_is_outside_configured_frames_dir(self) -> None:
        frame = self._frame_path(frames_dir="raw_frames", frame_name="f0.tiff")
        acquisition_root = self.repo / "acquisitions" / "acq-0011__test"
        self._write_acquisition(
            acquisition_root,
            frames_dir="frames",
            defaults={
                "camera_settings": {"exposure_us": 900},
                "instrument": {},
                "acquisition_settings": {},
            },
            overrides=[
                {
                    "selector": {"frame_range": [0, 0]},
                    "changes": {"camera_settings": {"exposure_us": 2000}},
                    "reason": "frame override",
                },
            ],
        )

        metadata = extract_path_metadata(str(frame), metadata_source="json")
        self.assertEqual(metadata.get("frame_link_mode"), "path_only")
        self.assertFalse(bool(metadata.get("frame_override_matched")))
        self.assertEqual(metadata.get("exposure_source"), "acquisition_default")
        self.assertAlmostEqual(float(metadata["exposure_ms"]), 0.9)

    def test_cache_requires_clear_for_datacard_changes_to_take_effect(self) -> None:
        frame = self._frame_path()
        acquisition_root = self.repo / "acquisitions" / "acq-0011__test"
        self._write_acquisition(
            acquisition_root,
            defaults={
                "camera_settings": {"exposure_us": 1000},
                "instrument": {},
                "acquisition_settings": {},
            },
        )

        first = extract_path_metadata(str(frame), metadata_source="json")
        self.assertAlmostEqual(float(first["exposure_ms"]), 1.0)

        self._write_acquisition(
            acquisition_root,
            defaults={
                "camera_settings": {"exposure_us": 2500},
                "instrument": {},
                "acquisition_settings": {},
            },
        )

        stale = extract_path_metadata(str(frame), metadata_source="json")
        self.assertAlmostEqual(float(stale["exposure_ms"]), 1.0)

        clear_metadata_cache()
        refreshed = extract_path_metadata(str(frame), metadata_source="json")
        self.assertAlmostEqual(float(refreshed["exposure_ms"]), 2.5)


if __name__ == "__main__":
    unittest.main()

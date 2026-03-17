from __future__ import annotations

import json
from pathlib import Path

import pytest

from framelab.metadata import (
    clear_metadata_cache,
    extract_path_metadata,
    invalidate_metadata_cache,
)
from framelab.node_metadata import save_nodecard


pytestmark = [pytest.mark.data, pytest.mark.core]


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


class _MetadataHarness:
    def __init__(self, repo: Path) -> None:
        self.repo = repo

    def frame_path(
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

    def write_campaign(self, root: Path, **kwargs: object) -> None:
        _write_json(root / "campaign_datacard.json", _campaign_payload(**kwargs))

    def write_session(self, root: Path, **kwargs: object) -> None:
        _write_json(root / "session_datacard.json", _session_payload(**kwargs))

    def write_acquisition(self, root: Path, **kwargs: object) -> None:
        _write_json(
            root / "acquisition_datacard.json",
            _acquisition_payload(**kwargs),
        )

    def write_node_metadata(
        self,
        root: Path,
        metadata: dict,
        *,
        profile_id: str | None = None,
        node_type_id: str | None = None,
    ) -> None:
        root.mkdir(parents=True, exist_ok=True)
        save_nodecard(
            root,
            metadata,
            profile_id=profile_id,
            node_type_id=node_type_id,
        )


@pytest.fixture
def metadata_harness(tmp_path: Path) -> _MetadataHarness:
    clear_metadata_cache()
    harness = _MetadataHarness(tmp_path)
    yield harness
    clear_metadata_cache()


def test_campaign_session_and_acquisition_defaults_layer_in_order(
    metadata_harness: _MetadataHarness,
) -> None:
    frame = metadata_harness.frame_path(campaign=True, session=True)
    campaign_root = metadata_harness.repo / "campaign"
    session_root = campaign_root / "01_sessions" / "2026-03-05__sess01"
    acquisition_root = session_root / "acquisitions" / "acq-0011__test"

    metadata_harness.write_campaign(
        campaign_root,
        instrument_defaults={"optics": {"iris": {"position": 2}}},
        campaign_defaults={"camera_settings": {"exposure_us": 1000}},
    )
    metadata_harness.write_session(
        session_root,
        session_defaults={"camera_settings": {"exposure_us": 1500}},
    )
    metadata_harness.write_acquisition(
        acquisition_root,
        defaults={
            "camera_settings": {"exposure_us": 2000},
            "instrument": {},
            "acquisition_settings": {},
        },
    )

    metadata = extract_path_metadata(str(frame), metadata_source="json")
    assert metadata.get("exposure_source") == "acquisition_default"
    assert float(metadata["exposure_ms"]) == pytest.approx(2.0)
    assert metadata.get("iris_source") == "campaign_default"
    assert float(metadata["iris_position"]) == 2.0


def test_none_in_higher_layer_does_not_erase_inherited_value(
    metadata_harness: _MetadataHarness,
) -> None:
    frame = metadata_harness.frame_path(campaign=True, session=True)
    campaign_root = metadata_harness.repo / "campaign"
    session_root = campaign_root / "01_sessions" / "2026-03-05__sess01"
    acquisition_root = session_root / "acquisitions" / "acq-0011__test"

    metadata_harness.write_campaign(
        campaign_root,
        campaign_defaults={"camera_settings": {"exposure_us": 1000}},
    )
    metadata_harness.write_session(
        session_root,
        session_defaults={"camera_settings": {"exposure_us": None}},
    )
    metadata_harness.write_acquisition(
        acquisition_root,
        defaults={
            "camera_settings": {},
            "instrument": {},
            "acquisition_settings": {},
        },
    )

    metadata = extract_path_metadata(str(frame), metadata_source="json")
    assert metadata.get("exposure_source") == "campaign_default"
    assert float(metadata["exposure_ms"]) == pytest.approx(1.0)


def test_metadata_boundary_root_excludes_defaults_above_loaded_subtree(
    metadata_harness: _MetadataHarness,
) -> None:
    frame = metadata_harness.frame_path(campaign=True, session=True)
    campaign_root = metadata_harness.repo / "campaign"
    session_root = campaign_root / "01_sessions" / "2026-03-05__sess01"
    acquisition_root = session_root / "acquisitions" / "acq-0011__test"

    metadata_harness.write_campaign(
        campaign_root,
        campaign_defaults={"camera_settings": {"exposure_us": 1000}},
    )
    metadata_harness.write_acquisition(
        acquisition_root,
        defaults={
            "camera_settings": {},
            "instrument": {},
            "acquisition_settings": {},
        },
    )

    metadata = extract_path_metadata(
        str(frame),
        metadata_source="json",
        metadata_boundary_root=session_root,
    )

    assert metadata.get("json_metadata_available") is True
    assert metadata.get("exposure_source") == "none"
    assert metadata.get("exposure_ms") is None


def test_matching_override_replaces_only_targeted_fields(
    metadata_harness: _MetadataHarness,
) -> None:
    frame = metadata_harness.frame_path(frame_name="f0.tiff")
    acquisition_root = metadata_harness.repo / "acquisitions" / "acq-0011__test"
    metadata_harness.write_acquisition(
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
    assert bool(metadata.get("frame_override_matched"))
    assert metadata.get("exposure_source") == "frame_override"
    assert float(metadata["exposure_ms"]) == pytest.approx(2.5)
    assert metadata.get("iris_source") == "acquisition_default"
    assert float(metadata["iris_position"]) == 4.0


def test_non_matching_override_falls_back_to_baseline(
    metadata_harness: _MetadataHarness,
) -> None:
    frame0 = metadata_harness.frame_path(frame_name="f0.tiff")
    frame1 = metadata_harness.frame_path(frame_name="f1.tiff")
    acquisition_root = metadata_harness.repo / "acquisitions" / "acq-0011__test"
    metadata_harness.write_acquisition(
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
    assert metadata0.get("frame_link_mode") == "frame_index"
    assert metadata1.get("frame_link_mode") == "frame_index_no_override"
    assert metadata1.get("exposure_source") == "acquisition_default"
    assert float(metadata1["exposure_ms"]) == pytest.approx(1.0)


def test_one_based_override_selectors_apply_for_filename_order_datasets(
    metadata_harness: _MetadataHarness,
) -> None:
    frame1 = metadata_harness.frame_path(frame_name="frame_a.tiff")
    frame2 = metadata_harness.frame_path(frame_name="frame_b.tiff")
    acquisition_root = metadata_harness.repo / "acquisitions" / "acq-0011__test"
    metadata_harness.write_acquisition(
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
    assert int(metadata1["override_index_base_detected"]) == 1
    assert metadata1.get("exposure_source") == "frame_override"
    assert metadata2.get("exposure_source") == "frame_override"


def test_json_source_can_mix_datacard_values_with_path_fallback(
    metadata_harness: _MetadataHarness,
) -> None:
    frame = metadata_harness.frame_path(frame_name="exp_7ms_iris2.tiff")
    acquisition_root = metadata_harness.repo / "acquisitions" / "acq-0011__test"
    metadata_harness.write_acquisition(
        acquisition_root,
        defaults={
            "camera_settings": {"exposure_us": 1000},
            "instrument": {},
            "acquisition_settings": {},
        },
    )

    metadata = extract_path_metadata(str(frame), metadata_source="json")
    assert metadata.get("exposure_source") == "acquisition_default"
    assert float(metadata["exposure_ms"]) == pytest.approx(1.0)
    assert metadata.get("iris_source") == "path_fallback"
    assert float(metadata["iris_position"]) == pytest.approx(2.0)


def test_json_source_uses_path_fallback_and_none_when_no_json_value_exists(
    metadata_harness: _MetadataHarness,
) -> None:
    fallback_frame = metadata_harness.frame_path(
        acquisition=False,
        frame_name="exp_12ms_iris5.tiff",
    )
    missing_frame = metadata_harness.frame_path(
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

    assert fallback_metadata.get("exposure_source") == "path_fallback"
    assert fallback_metadata.get("iris_source") == "path_fallback"
    assert float(fallback_metadata["exposure_ms"]) == pytest.approx(12.0)
    assert float(fallback_metadata["iris_position"]) == pytest.approx(5.0)
    assert missing_metadata.get("exposure_source") == "none"
    assert missing_metadata.get("iris_source") == "none"
    assert "exposure_ms" not in missing_metadata
    assert "iris_position" not in missing_metadata


def test_path_source_uses_path_provenance_even_inside_json_backed_acquisition(
    metadata_harness: _MetadataHarness,
) -> None:
    frame = metadata_harness.frame_path(frame_name="exp_7ms_iris2.tiff")
    acquisition_root = metadata_harness.repo / "acquisitions" / "acq-0011__test"
    metadata_harness.write_acquisition(
        acquisition_root,
        defaults={
            "camera_settings": {"exposure_us": 1000},
            "instrument": {"optics": {"iris": {"position": 9}}},
            "acquisition_settings": {},
        },
    )

    metadata = extract_path_metadata(str(frame), metadata_source="path")
    assert metadata.get("exposure_source") == "path"
    assert metadata.get("iris_source") == "path"
    assert float(metadata["exposure_ms"]) == pytest.approx(7.0)
    assert float(metadata["iris_position"]) == pytest.approx(2.0)


def test_session_and_campaign_defaults_apply_without_acquisition_datacard(
    metadata_harness: _MetadataHarness,
) -> None:
    frame = metadata_harness.frame_path(
        campaign=True,
        session=True,
        acquisition=True,
        acquisition_name="acq-0011__test",
    )
    campaign_root = metadata_harness.repo / "campaign"
    session_root = campaign_root / "01_sessions" / "2026-03-05__sess01"

    metadata_harness.write_campaign(
        campaign_root,
        campaign_defaults={"camera_settings": {"exposure_us": 800}},
    )
    metadata_harness.write_session(
        session_root,
        session_defaults={
            "instrument": {"optics": {"iris": {"position": 6}}},
        },
    )

    metadata = extract_path_metadata(str(frame), metadata_source="json")
    assert bool(metadata.get("json_metadata_available"))
    assert metadata.get("exposure_source") == "campaign_default"
    assert metadata.get("iris_source") == "session_default"
    assert float(metadata["exposure_ms"]) == pytest.approx(0.8)
    assert float(metadata["iris_position"]) == pytest.approx(6.0)


def test_node_metadata_applies_without_legacy_datacards(
    metadata_harness: _MetadataHarness,
) -> None:
    frame = metadata_harness.frame_path()
    acquisitions_root = metadata_harness.repo / "acquisitions"

    metadata_harness.write_node_metadata(
        acquisitions_root,
        {
            "camera_settings": {"exposure_us": 1800},
            "instrument": {"optics": {"iris": {"position": 5}}},
        },
        profile_id="calibration",
        node_type_id="session",
    )

    metadata = extract_path_metadata(str(frame), metadata_source="json")

    assert bool(metadata.get("json_metadata_available"))
    assert metadata.get("exposure_source") == "node_inherited"
    assert metadata.get("iris_source") == "node_inherited"
    assert float(metadata["exposure_ms"]) == pytest.approx(1.8)
    assert float(metadata["iris_position"]) == pytest.approx(5.0)


def test_node_metadata_overrides_legacy_session_and_campaign_defaults(
    metadata_harness: _MetadataHarness,
) -> None:
    frame = metadata_harness.frame_path(campaign=True, session=True)
    campaign_root = metadata_harness.repo / "campaign"
    session_root = campaign_root / "01_sessions" / "2026-03-05__sess01"
    acquisition_root = session_root / "acquisitions" / "acq-0011__test"

    metadata_harness.write_campaign(
        campaign_root,
        campaign_defaults={"camera_settings": {"exposure_us": 1000}},
    )
    metadata_harness.write_session(
        session_root,
        session_defaults={"camera_settings": {"exposure_us": 1500}},
    )
    metadata_harness.write_node_metadata(
        session_root,
        {
            "camera_settings": {"exposure_us": 1750},
            "instrument": {"optics": {"iris": {"position": 4}}},
        },
        profile_id="calibration",
        node_type_id="session",
    )
    metadata_harness.write_acquisition(
        acquisition_root,
        defaults={
            "camera_settings": {},
            "instrument": {},
            "acquisition_settings": {},
        },
    )

    metadata = extract_path_metadata(str(frame), metadata_source="json")

    assert metadata.get("exposure_source") == "node_inherited"
    assert metadata.get("iris_source") == "node_inherited"
    assert float(metadata["exposure_ms"]) == pytest.approx(1.75)
    assert float(metadata["iris_position"]) == pytest.approx(4.0)


def test_malformed_acquisition_datacard_falls_back_to_session_defaults(
    metadata_harness: _MetadataHarness,
) -> None:
    frame = metadata_harness.frame_path(campaign=True, session=True)
    campaign_root = metadata_harness.repo / "campaign"
    session_root = campaign_root / "01_sessions" / "2026-03-05__sess01"
    acquisition_root = session_root / "acquisitions" / "acq-0011__test"

    metadata_harness.write_campaign(campaign_root)
    metadata_harness.write_session(
        session_root,
        session_defaults={"camera_settings": {"exposure_us": 1200}},
    )
    _write_text(acquisition_root / "acquisition_datacard.json", "{ invalid json")

    metadata = extract_path_metadata(str(frame), metadata_source="json")
    assert bool(metadata.get("json_metadata_available"))
    assert metadata.get("exposure_source") == "session_default"
    assert float(metadata["exposure_ms"]) == pytest.approx(1.2)


def test_unknown_default_fields_do_not_contaminate_known_metadata(
    metadata_harness: _MetadataHarness,
) -> None:
    frame = metadata_harness.frame_path()
    acquisition_root = metadata_harness.repo / "acquisitions" / "acq-0011__test"
    metadata_harness.write_acquisition(
        acquisition_root,
        defaults={
            "camera_settings": {"exposure_us": 1000},
            "instrument": {},
            "acquisition_settings": {},
            "unknown_block": {"mystery": 123},
        },
    )

    metadata = extract_path_metadata(str(frame), metadata_source="json")
    assert metadata.get("exposure_source") == "acquisition_default"
    assert float(metadata["exposure_ms"]) == pytest.approx(1.0)
    assert "unknown_block.mystery" not in metadata


def test_frame_index_mode_reports_filename_index(
    metadata_harness: _MetadataHarness,
) -> None:
    frame = metadata_harness.frame_path(frame_name="f3.tiff")
    acquisition_root = metadata_harness.repo / "acquisitions" / "acq-0011__test"
    metadata_harness.write_acquisition(acquisition_root)

    metadata = extract_path_metadata(str(frame), metadata_source="json")
    assert metadata.get("frame_naming") == "f_index"
    assert metadata.get("frame_index_mode") == "filename_index"
    assert int(metadata["frame_index"]) == 3


def test_frame_index_mode_reports_ebus_index_and_timestamp_fields(
    metadata_harness: _MetadataHarness,
) -> None:
    frame = metadata_harness.frame_path(frame_name="7_0000002A.tiff")
    acquisition_root = metadata_harness.repo / "acquisitions" / "acq-0011__test"
    metadata_harness.write_acquisition(acquisition_root)

    metadata = extract_path_metadata(str(frame), metadata_source="json")
    assert metadata.get("frame_naming") == "ebus_index_timestamp"
    assert metadata.get("frame_index_mode") == "ebus_index"
    assert int(metadata["frame_index"]) == 7
    assert metadata.get("ebus_timestamp_hex") == "0000002A"
    assert int(metadata["ebus_timestamp_ms"]) == 42


def test_frame_index_mode_reports_ebus_timestamp_order_when_indices_repeat(
    metadata_harness: _MetadataHarness,
) -> None:
    frame_a = metadata_harness.frame_path(frame_name="0_0000000B.tiff")
    metadata_harness.frame_path(frame_name="0_0000000A.tiff")
    acquisition_root = metadata_harness.repo / "acquisitions" / "acq-0011__test"
    metadata_harness.write_acquisition(acquisition_root)

    metadata_a = extract_path_metadata(str(frame_a), metadata_source="json")
    assert metadata_a.get("frame_index_mode") == "ebus_timestamp_order"
    assert int(metadata_a["frame_index"]) == 1


def test_frame_link_mode_is_path_only_when_file_is_outside_configured_frames_dir(
    metadata_harness: _MetadataHarness,
) -> None:
    frame = metadata_harness.frame_path(frames_dir="raw_frames", frame_name="f0.tiff")
    acquisition_root = metadata_harness.repo / "acquisitions" / "acq-0011__test"
    metadata_harness.write_acquisition(
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
    assert metadata.get("frame_link_mode") == "path_only"
    assert not bool(metadata.get("frame_override_matched"))
    assert metadata.get("exposure_source") == "acquisition_default"
    assert float(metadata["exposure_ms"]) == pytest.approx(0.9)


def test_cache_requires_clear_for_datacard_changes_to_take_effect(
    metadata_harness: _MetadataHarness,
) -> None:
    frame = metadata_harness.frame_path()
    acquisition_root = metadata_harness.repo / "acquisitions" / "acq-0011__test"
    metadata_harness.write_acquisition(
        acquisition_root,
        defaults={
            "camera_settings": {"exposure_us": 1000},
            "instrument": {},
            "acquisition_settings": {},
        },
    )

    first = extract_path_metadata(str(frame), metadata_source="json")
    assert float(first["exposure_ms"]) == pytest.approx(1.0)

    metadata_harness.write_acquisition(
        acquisition_root,
        defaults={
            "camera_settings": {"exposure_us": 2500},
            "instrument": {},
            "acquisition_settings": {},
        },
    )

    stale = extract_path_metadata(str(frame), metadata_source="json")
    assert float(stale["exposure_ms"]) == pytest.approx(1.0)

    clear_metadata_cache()
    refreshed = extract_path_metadata(str(frame), metadata_source="json")
    assert float(refreshed["exposure_ms"]) == pytest.approx(2.5)


def test_incremental_invalidation_can_refresh_one_acquisition_subtree(
    metadata_harness: _MetadataHarness,
) -> None:
    frame_a = metadata_harness.frame_path(
        campaign=True,
        session=True,
        acquisition_name="acq-0011__dark",
    )
    frame_b = metadata_harness.frame_path(
        campaign=True,
        session=True,
        acquisition_name="acq-0012__bright",
    )
    campaign_root = metadata_harness.repo / "campaign"
    session_root = campaign_root / "01_sessions" / "2026-03-05__sess01"
    acquisition_a_root = session_root / "acquisitions" / "acq-0011__dark"
    acquisition_b_root = session_root / "acquisitions" / "acq-0012__bright"

    metadata_harness.write_campaign(campaign_root)
    metadata_harness.write_session(
        session_root,
        session_defaults={"camera_settings": {"exposure_us": 1000}},
    )
    metadata_harness.write_acquisition(acquisition_a_root)
    metadata_harness.write_acquisition(acquisition_b_root)

    first_a = extract_path_metadata(str(frame_a), metadata_source="json")
    first_b = extract_path_metadata(str(frame_b), metadata_source="json")
    assert float(first_a["exposure_ms"]) == pytest.approx(1.0)
    assert float(first_b["exposure_ms"]) == pytest.approx(1.0)

    metadata_harness.write_session(
        session_root,
        session_defaults={"camera_settings": {"exposure_us": 2500}},
    )

    invalidate_metadata_cache((acquisition_a_root,))
    refreshed_a = extract_path_metadata(str(frame_a), metadata_source="json")
    stale_b = extract_path_metadata(str(frame_b), metadata_source="json")
    assert float(refreshed_a["exposure_ms"]) == pytest.approx(2.5)
    assert float(stale_b["exposure_ms"]) == pytest.approx(1.0)

    invalidate_metadata_cache((session_root,))
    refreshed_b = extract_path_metadata(str(frame_b), metadata_source="json")
    assert float(refreshed_b["exposure_ms"]) == pytest.approx(2.5)


def test_incremental_invalidation_refreshes_cached_node_metadata_sources(
    metadata_harness: _MetadataHarness,
) -> None:
    frame = metadata_harness.frame_path(
        campaign=True,
        session=True,
        acquisition_name="acq-0011__nodecard",
    )
    session_root = (
        metadata_harness.repo
        / "campaign"
        / "01_sessions"
        / "2026-03-05__sess01"
    )
    acquisition_root = session_root / "acquisitions" / "acq-0011__nodecard"
    metadata_harness.write_campaign(metadata_harness.repo / "campaign")
    metadata_harness.write_session(session_root)
    metadata_harness.write_acquisition(acquisition_root)
    metadata_harness.write_node_metadata(
        session_root,
        {"camera_settings": {"exposure_us": 1000}},
        profile_id="calibration",
        node_type_id="session",
    )

    first = extract_path_metadata(str(frame), metadata_source="json")
    assert float(first["exposure_ms"]) == pytest.approx(1.0)

    metadata_harness.write_node_metadata(
        session_root,
        {"camera_settings": {"exposure_us": 2500}},
        profile_id="calibration",
        node_type_id="session",
    )

    stale = extract_path_metadata(str(frame), metadata_source="json")
    assert float(stale["exposure_ms"]) == pytest.approx(1.0)

    invalidate_metadata_cache((session_root,))
    refreshed = extract_path_metadata(str(frame), metadata_source="json")
    assert float(refreshed["exposure_ms"]) == pytest.approx(2.5)

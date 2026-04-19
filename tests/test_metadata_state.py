from __future__ import annotations

import json
from pathlib import Path

import pytest

import framelab.workflow.governance_config as governance_config
from framelab.metadata_state import MetadataStateController
from framelab.node_metadata import save_nodecard
from framelab.workflow import WorkflowStateController, workflow_profile_by_id


pytestmark = [pytest.mark.fast, pytest.mark.core]


def test_save_and_load_node_metadata_round_trip(tmp_path: Path) -> None:
    node_root = tmp_path / "workspace" / "camera-a"
    node_root.mkdir(parents=True, exist_ok=True)
    controller = MetadataStateController()

    saved_path = controller.save_node_metadata(
        node_root,
        {
            "instrument": {
                "camera": {
                    "model": "Cam-01",
                },
            },
        },
        profile_id="calibration",
        node_type_id="camera",
        extra_top_level={"notes": "calibration camera"},
    )

    loaded = controller.load_node_metadata(node_root)

    assert saved_path == node_root / ".framelab" / "nodecard.json"
    assert loaded.source_exists
    assert loaded.profile_id == "calibration"
    assert loaded.node_type_id == "camera"
    assert loaded.metadata == {
        "instrument": {
            "camera": {
                "model": "Cam-01",
            },
        },
    }
    assert loaded.extra_top_level == {"notes": "calibration camera"}


def test_resolve_path_metadata_merges_ancestor_nodecards_in_order(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    camera_root = workspace_root / "camera-a"
    session_root = camera_root / "session-01"
    acquisition_root = session_root / "acq-0001"
    acquisition_root.mkdir(parents=True, exist_ok=True)
    controller = MetadataStateController()

    save_nodecard(
        workspace_root,
        {"camera_settings": {"exposure_us": 1000}},
        profile_id="calibration",
        node_type_id="root",
    )
    save_nodecard(
        camera_root,
        {"camera_settings": {"exposure_us": 1500}},
        profile_id="calibration",
        node_type_id="camera",
    )
    save_nodecard(
        session_root,
        {"instrument": {"optics": {"iris": {"position": 3}}}},
        profile_id="calibration",
        node_type_id="session",
    )

    snapshot = controller.resolve_path_metadata(acquisition_root)

    assert snapshot.has_metadata
    assert snapshot.flat_metadata["camera_settings.exposure_us"] == 1500
    assert snapshot.flat_metadata["instrument.optics.iris.position"] == 3
    assert snapshot.field_sources["camera_settings.exposure_us"].provenance == "node_inherited"
    assert snapshot.field_sources["camera_settings.exposure_us"].source_path == camera_root.resolve()
    assert snapshot.field_sources["instrument.optics.iris.position"].source_path == session_root.resolve()
    assert [layer.source_path for layer in snapshot.layers] == [
        workspace_root.resolve(),
        camera_root.resolve(),
        session_root.resolve(),
    ]


def test_schema_marks_ad_hoc_keys_from_node_metadata(tmp_path: Path) -> None:
    node_root = tmp_path / "workspace" / "2026"
    node_root.mkdir(parents=True, exist_ok=True)
    controller = MetadataStateController()
    save_nodecard(
        node_root,
        {"custom": {"operator": "maxime"}},
        profile_id="trials",
        node_type_id="year",
    )

    snapshot = controller.resolve_path_metadata(node_root)
    schema_field = snapshot.schema.by_key()["custom.operator"]

    assert schema_field.source_kind == "ad_hoc"
    assert snapshot.field_sources["custom.operator"].schema_source_kind == "ad_hoc"
    assert snapshot.field_sources["custom.operator"].provenance == "node_local"


def test_none_node_value_keeps_inherited_effective_source(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    child = root / "session-01"
    target = child / "acq-0001"
    target.mkdir(parents=True, exist_ok=True)
    controller = MetadataStateController()

    save_nodecard(
        root,
        {"camera_settings": {"exposure_us": 1000}},
        profile_id="calibration",
        node_type_id="root",
    )
    save_nodecard(
        child,
        {"camera_settings": {"exposure_us": None}},
        profile_id="calibration",
        node_type_id="session",
    )

    snapshot = controller.resolve_path_metadata(target)

    assert snapshot.flat_metadata["camera_settings.exposure_us"] == 1000
    assert snapshot.field_sources["camera_settings.exposure_us"].source_path == root.resolve()
    assert snapshot.field_sources["camera_settings.exposure_us"].provenance == "node_inherited"


def test_active_node_metadata_respects_loaded_subtree_boundary(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    camera_root = workspace_root / "camera-a"
    campaign_root = camera_root / "campaign-1"
    session_root = campaign_root / "session-01"
    acquisition_root = session_root / "acq-0001"
    acquisition_root.mkdir(parents=True, exist_ok=True)

    save_nodecard(
        workspace_root,
        {"workflow": {"notes": "workspace"}},
        profile_id="calibration",
        node_type_id="root",
    )
    save_nodecard(
        camera_root,
        {"camera_settings": {"exposure_us": 1200}},
        profile_id="calibration",
        node_type_id="camera",
    )
    save_nodecard(
        session_root,
        {"instrument": {"optics": {"iris": {"position": 4}}}},
        profile_id="calibration",
        node_type_id="session",
    )

    workflow = WorkflowStateController()
    workflow.load_workspace(
        session_root,
        "calibration",
        anchor_type_id="session",
        active_node_id="calibration:acquisition:acq-0001",
    )
    controller = MetadataStateController(workflow)

    snapshot = controller.resolve_active_node_metadata()

    assert snapshot is not None
    assert snapshot.flat_metadata["instrument.optics.iris.position"] == 4
    assert "camera_settings.exposure_us" not in snapshot.flat_metadata
    assert "workflow.notes" not in snapshot.flat_metadata
    assert [layer.source_path for layer in snapshot.layers] == [session_root.resolve()]


def test_validation_tracks_required_fields_templates_and_relevant_groups(
    tmp_path: Path,
) -> None:
    session_root = tmp_path / "workspace" / "camera-a" / "session-01"
    session_root.mkdir(parents=True, exist_ok=True)
    controller = MetadataStateController()
    save_nodecard(
        session_root,
        {
            "instrument": {"optics": {"iris": {"position": 3}}},
            "custom": {"wind_note": "gusty"},
        },
        profile_id="calibration",
        node_type_id="session",
    )

    snapshot = controller.resolve_path_metadata(session_root, node_type_id="session")
    statuses = {status.group: status for status in snapshot.validation.group_statuses}

    assert snapshot.validation.missing_required_keys == ("workflow.operator",)
    assert snapshot.validation.template_keys == (
        "instrument.optics.iris.position",
        "workflow.notes",
        "workflow.operator",
    )
    assert statuses["Workflow"].missing_required == 1
    assert statuses["Optics"].present_fields == 1
    assert statuses["Custom"].ad_hoc_fields == 1
    assert "Camera" not in statuses


def test_apply_template_preserves_existing_values(tmp_path: Path) -> None:
    session_root = tmp_path / "workspace" / "camera-a" / "session-01"
    session_root.mkdir(parents=True, exist_ok=True)
    controller = MetadataStateController()
    save_nodecard(
        session_root,
        {"instrument": {"optics": {"iris": {"position": 5}}}},
        profile_id="calibration",
        node_type_id="session",
    )

    saved_path = controller.apply_template(
        session_root,
        profile_id="calibration",
        node_type_id="session",
        preserve_existing=True,
    )
    saved = controller.load_node_metadata(session_root)

    assert saved_path == session_root / ".framelab" / "nodecard.json"
    assert saved.metadata["instrument"]["optics"]["iris"]["position"] == 5
    assert saved.metadata["workflow"]["operator"] == ""


@pytest.mark.parametrize("profile_id", ["calibration", "trials"])
def test_demote_core_mapping_field_marks_exposure_as_ad_hoc(
    tmp_path: Path,
    monkeypatch,
    profile_id: str,
) -> None:
    config_path = tmp_path / "workflow_metadata_governance.json"
    monkeypatch.setattr(
        governance_config,
        "governance_config_path",
        lambda: config_path,
    )
    controller = MetadataStateController()

    before = controller.schema_for_profile(profile_id, node_type_id="camera")
    assert before.by_key()["camera_settings.exposure_us"].source_kind == "core"

    saved_path = controller.demote_field_from_profile(
        profile_id,
        key="camera_settings.exposure_us",
        label="Exposure (us)",
        group="Camera",
        value_type="int",
        current_source_kind="core",
    )

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    after = controller.schema_for_profile(profile_id, node_type_id="camera")

    assert saved_path == config_path
    assert payload["profiles"][profile_id]["fields"][0]["key"] == "camera_settings.exposure_us"
    assert payload["profiles"][profile_id]["fields"][0]["source_kind"] == "ad_hoc"
    assert after.by_key()["camera_settings.exposure_us"].source_kind == "ad_hoc"


def test_resolve_acquisition_metadata_includes_datacard_defaults_and_override_markers(
    tmp_path: Path,
) -> None:
    acquisition_root = tmp_path / "workspace" / "camera-a" / "session-01" / "acq-0001"
    acquisition_root.mkdir(parents=True, exist_ok=True)
    controller = MetadataStateController()
    (acquisition_root / "acquisition_datacard.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "entity": "acquisition",
                "identity": {},
                "paths": {"frames_dir": "frames"},
                "intent": {},
                "defaults": {
                    "camera_settings": {"exposure_us": 1200},
                    "instrument": {"optics": {"iris": {"position": 3.5}}},
                },
                "overrides": [
                    {
                        "selector": {"frame_range": [0, 3]},
                        "changes": {"camera_settings": {"exposure_us": 1400}},
                        "reason": "sweep",
                    },
                ],
                "quality": {},
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )

    snapshot = controller.resolve_path_metadata(
        acquisition_root,
        node_type_id="acquisition",
    )

    assert "camera_settings.exposure_us" in snapshot.flat_metadata
    assert snapshot.flat_metadata["camera_settings.exposure_us"] is None
    assert snapshot.field_sources["camera_settings.exposure_us"].provenance == (
        "acquisition_override"
    )
    assert snapshot.field_sources["camera_settings.exposure_us"].storage_kind == (
        "acquisition_datacard_override"
    )
    assert snapshot.flat_metadata["instrument.optics.iris.position"] == 3.5
    assert snapshot.field_sources["instrument.optics.iris.position"].provenance == (
        "acquisition_datacard"
    )
    assert snapshot.field_sources["instrument.optics.iris.position"].storage_kind == (
        "acquisition_datacard_defaults"
    )


def test_promote_field_to_profile_writes_override_and_updates_schema(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "workflow_metadata_governance.json"
    monkeypatch.setattr(
        governance_config,
        "governance_config_path",
        lambda: config_path,
    )
    session_root = (
        tmp_path
        / "trials"
        / "2026"
        / "campaign-07"
        / "camera-a"
        / "session-01"
    )
    session_root.mkdir(parents=True, exist_ok=True)
    controller = MetadataStateController()
    save_nodecard(
        session_root,
        {"custom": {"wind_speed": 12}},
        profile_id="trials",
        node_type_id="session",
    )

    before = controller.resolve_path_metadata(session_root, node_type_id="session")
    assert before.schema.by_key()["custom.wind_speed"].source_kind == "ad_hoc"

    saved_path = controller.promote_field_to_profile(
        "trials",
        key="custom.wind_speed",
        label="Wind Speed",
        group="Custom",
        value_type="int",
    )

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    after = controller.resolve_path_metadata(session_root, node_type_id="session")
    profile = workflow_profile_by_id("trials")

    assert saved_path == config_path
    assert payload["profiles"]["trials"]["fields"][0]["key"] == "custom.wind_speed"
    assert after.schema.by_key()["custom.wind_speed"].source_kind == "profile"
    assert profile is not None
    assert profile.metadata_governance.field_rule_index()["custom.wind_speed"].value_type == "int"


def test_demote_field_from_profile_removes_override_and_restores_ad_hoc_schema(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "workflow_metadata_governance.json"
    monkeypatch.setattr(
        governance_config,
        "governance_config_path",
        lambda: config_path,
    )
    session_root = (
        tmp_path
        / "trials"
        / "2026"
        / "campaign-07"
        / "camera-a"
        / "session-01"
    )
    session_root.mkdir(parents=True, exist_ok=True)
    controller = MetadataStateController()
    save_nodecard(
        session_root,
        {"custom": {"wind_speed": 12}},
        profile_id="trials",
        node_type_id="session",
    )
    controller.promote_field_to_profile(
        "trials",
        key="custom.wind_speed",
        label="Wind Speed",
        group="Custom",
        value_type="int",
    )

    assert controller.has_profile_field_override("trials", key="custom.wind_speed")

    saved_path = controller.demote_field_from_profile(
        "trials",
        key="custom.wind_speed",
        label="Wind Speed",
        group="Custom",
        value_type="int",
        current_source_kind="profile",
    )

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    after = controller.resolve_path_metadata(session_root, node_type_id="session")

    assert saved_path == config_path
    assert payload["profiles"] == {}
    assert not controller.has_profile_field_override("trials", key="custom.wind_speed")
    assert after.schema.by_key()["custom.wind_speed"].source_kind == "ad_hoc"

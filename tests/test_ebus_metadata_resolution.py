"""Regression tests for eBUS-backed canonical metadata resolution."""

from __future__ import annotations

import json
import os
from pathlib import Path
from collections.abc import Callable, Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6 import QtWidgets as qtw
except ModuleNotFoundError:
    qtw = None

from framelab.acquisition_datacard import normalize_override_selectors
from framelab.ebus import resolve_ebus_canonical_fields
from framelab.metadata import clear_metadata_cache, extract_path_metadata
from framelab.payload_utils import get_dot_path

if qtw is not None:
    from framelab.plugins.data.acquisition_datacard_wizard import (
        AcquisitionDatacardWizardDialog,
    )
else:
    AcquisitionDatacardWizardDialog = None


pytestmark = [pytest.mark.data, pytest.mark.core]
_WIZARD_AVAILABLE = qtw is not None and AcquisitionDatacardWizardDialog is not None


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _write_session_datacard(
    session_root: Path,
    *,
    session_defaults: dict | None = None,
) -> None:
    _write_json(
        session_root / "session_datacard.json",
        {
            "schema_version": "1.0",
            "entity": "session",
            "identity": {
                "camera_id": None,
                "campaign_id": None,
                "session_id": None,
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
        },
    )


def _write_campaign_datacard(
    campaign_root: Path,
    *,
    instrument_defaults: dict | None = None,
    campaign_defaults: dict | None = None,
) -> None:
    _write_json(
        campaign_root / "campaign_datacard.json",
        {
            "schema_version": "1.0",
            "entity": "campaign",
            "identity": {
                "camera_id": None,
                "campaign_id": None,
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
        },
    )


def _base_datacard(
    *,
    defaults: dict | None = None,
    overrides: list[dict] | None = None,
    external_sources: dict | None = None,
) -> dict:
    payload: dict = {
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
        "paths": {"frames_dir": "frames"},
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
    if external_sources is not None:
        payload["external_sources"] = external_sources
    return payload


def _write_snapshot(path: Path, parameters: dict[str, object]) -> None:
    lines = [
        '<?xml version="1.0"?>',
        '<puregevpersistencefile version="1.0">',
        '  <device name="" version="1.0">',
        "    <device>",
    ]
    for name, value in parameters.items():
        if value is None:
            lines.append(f'      <parameter name="{name}"/>')
        else:
            lines.append(f'      <parameter name="{name}">{value}</parameter>')
    lines.extend(
        [
            "    </device>",
            "  </device>",
            "</puregevpersistencefile>",
        ],
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_acquisition(
    root: Path,
    *,
    defaults: dict | None = None,
    overrides: list[dict] | None = None,
    external_sources: dict | None = None,
    snapshot_parameters: dict[str, object] | None = None,
    extra_snapshot: bool = False,
    frame_count: int = 2,
) -> list[Path]:
    frames_dir = root / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frame_paths: list[Path] = []
    for index in range(frame_count):
        frame_path = frames_dir / f"f{index}.tiff"
        frame_path.touch()
        frame_paths.append(frame_path)

    payload = _base_datacard(
        defaults=defaults,
        overrides=overrides,
        external_sources=external_sources,
    )
    _write_json(root / "acquisition_datacard.json", payload)

    if snapshot_parameters is not None:
        _write_snapshot(root / "acq_config.pvcfg", snapshot_parameters)
        if extra_snapshot:
            _write_snapshot(root / "extra_config.pvcfg", snapshot_parameters)

    return frame_paths


@pytest.fixture(autouse=True)
def metadata_cache_guard() -> Iterator[None]:
    clear_metadata_cache()
    try:
        yield
    finally:
        clear_metadata_cache()


@pytest.fixture
def acquisition_root(tmp_path: Path) -> Path:
    root = tmp_path / "acquisition"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def dialog_factory(
    qapp,
    acquisition_root: Path,
) -> Iterator[Callable[[], object]]:
    dialogs: list[object] = []

    def _build_dialog():
        dialog = AcquisitionDatacardWizardDialog(None, str(acquisition_root))
        dialogs.append(dialog)
        return dialog

    yield _build_dialog

    for dialog in reversed(dialogs):
        try:
            dialog.close()
        except Exception:
            pass
        try:
            dialog.deleteLater()
        except Exception:
            pass
    qapp.processEvents()


def test_defaults_only_without_snapshot(acquisition_root: Path) -> None:
    frames = _make_acquisition(
        acquisition_root,
        defaults={
            "camera_settings": {"exposure_us": 900},
            "instrument": {},
            "acquisition_settings": {},
        },
    )
    payload = _base_datacard(
        defaults={
            "camera_settings": {"exposure_us": 900},
            "instrument": {},
            "acquisition_settings": {},
        },
    )

    resolutions = resolve_ebus_canonical_fields(acquisition_root, payload)
    exposure = resolutions.by_key()["camera_settings.exposure_us"]
    assert not exposure.snapshot_present

    metadata = extract_path_metadata(str(frames[0]), metadata_source="json")
    assert metadata.get("exposure_source") == "acquisition_default"
    assert float(metadata["exposure_ms"]) == pytest.approx(0.9)


def test_snapshot_baseline_overrides_legacy_default(acquisition_root: Path) -> None:
    frames = _make_acquisition(
        acquisition_root,
        defaults={
            "camera_settings": {"exposure_us": 900},
            "instrument": {},
            "acquisition_settings": {},
        },
        snapshot_parameters={"Exposure": 500},
    )
    payload = _base_datacard(
        defaults={
            "camera_settings": {"exposure_us": 900},
            "instrument": {},
            "acquisition_settings": {},
        },
    )

    resolutions = resolve_ebus_canonical_fields(acquisition_root, payload)
    exposure = resolutions.by_key()["camera_settings.exposure_us"]
    assert exposure.snapshot_present
    assert exposure.snapshot_value == 500
    assert exposure.effective_value == 500
    assert exposure.provenance == "ebus_snapshot"

    metadata = extract_path_metadata(str(frames[0]), metadata_source="json")
    assert metadata.get("exposure_source") == "ebus_snapshot"
    assert float(metadata["exposure_ms"]) == pytest.approx(0.5)


def test_snapshot_missing_key_falls_back_to_default(acquisition_root: Path) -> None:
    frames = _make_acquisition(
        acquisition_root,
        defaults={
            "camera_settings": {"exposure_us": 900},
            "instrument": {},
            "acquisition_settings": {},
        },
        snapshot_parameters={"Iris": 3},
    )
    payload = _base_datacard(
        defaults={
            "camera_settings": {"exposure_us": 900},
            "instrument": {},
            "acquisition_settings": {},
        },
    )

    resolutions = resolve_ebus_canonical_fields(acquisition_root, payload)
    exposure = resolutions.by_key()["camera_settings.exposure_us"]
    assert not exposure.snapshot_present

    metadata = extract_path_metadata(str(frames[0]), metadata_source="json")
    assert metadata.get("exposure_source") == "acquisition_default"
    assert float(metadata["exposure_ms"]) == pytest.approx(0.9)


def test_snapshot_coercion_failure_falls_back_to_default(
    acquisition_root: Path,
) -> None:
    frames = _make_acquisition(
        acquisition_root,
        defaults={
            "camera_settings": {"exposure_us": 900},
            "instrument": {},
            "acquisition_settings": {},
        },
        snapshot_parameters={"Exposure": "not_an_int"},
    )
    payload = _base_datacard(
        defaults={
            "camera_settings": {"exposure_us": 900},
            "instrument": {},
            "acquisition_settings": {},
        },
    )

    resolutions = resolve_ebus_canonical_fields(acquisition_root, payload)
    exposure = resolutions.by_key()["camera_settings.exposure_us"]
    assert not exposure.snapshot_present

    metadata = extract_path_metadata(str(frames[0]), metadata_source="json")
    assert metadata.get("exposure_source") == "acquisition_default"
    assert float(metadata["exposure_ms"]) == pytest.approx(0.9)


def test_acquisition_wide_ebus_override_beats_snapshot(acquisition_root: Path) -> None:
    frames = _make_acquisition(
        acquisition_root,
        snapshot_parameters={"Iris": 2},
        external_sources={
            "ebus": {
                "overrides": {"device.Iris": 5},
            },
        },
    )
    payload = _base_datacard(
        external_sources={
            "ebus": {
                "overrides": {"device.Iris": 5},
            },
        },
    )

    resolutions = resolve_ebus_canonical_fields(acquisition_root, payload)
    iris = resolutions.by_key()["instrument.optics.iris.position"]
    assert iris.snapshot_present
    assert iris.snapshot_value == 2
    assert iris.effective_value == 5
    assert iris.provenance == "ebus_override"

    metadata = extract_path_metadata(str(frames[0]), metadata_source="json")
    assert metadata.get("iris_source") == "ebus_override"
    assert metadata.get("iris_position") == 5.0


def test_overridable_acquisition_default_beats_snapshot_value(
    acquisition_root: Path,
) -> None:
    frames = _make_acquisition(
        acquisition_root,
        defaults={
            "camera_settings": {},
            "instrument": {
                "optics": {"iris": {"position": 4}},
            },
            "acquisition_settings": {},
        },
        snapshot_parameters={"Iris": 0},
    )
    payload = _base_datacard(
        defaults={
            "camera_settings": {},
            "instrument": {
                "optics": {"iris": {"position": 4}},
            },
            "acquisition_settings": {},
        },
    )

    resolutions = resolve_ebus_canonical_fields(acquisition_root, payload)
    iris = resolutions.by_key()["instrument.optics.iris.position"]
    assert iris.snapshot_present
    assert iris.snapshot_value == 0
    assert iris.effective_value == 4
    assert iris.provenance == "acquisition_default"

    metadata = extract_path_metadata(str(frames[0]), metadata_source="json")
    assert metadata.get("iris_source") == "acquisition_default"
    assert metadata.get("iris_position") == 4.0


def test_frame_override_beats_snapshot(acquisition_root: Path) -> None:
    frames = _make_acquisition(
        acquisition_root,
        snapshot_parameters={"Exposure": 500},
        overrides=[
            {
                "selector": {"frame_range": [0, 0]},
                "changes": {"camera_settings": {"exposure_us": 2000}},
                "reason": "frame override",
            },
        ],
    )

    metadata = extract_path_metadata(str(frames[0]), metadata_source="json")
    assert metadata.get("exposure_source") == "frame_override"
    assert float(metadata["exposure_ms"]) == pytest.approx(2.0)

    metadata_other = extract_path_metadata(str(frames[1]), metadata_source="json")
    assert metadata_other.get("exposure_source") == "ebus_snapshot"
    assert float(metadata_other["exposure_ms"]) == pytest.approx(0.5)


def test_frame_override_beats_acquisition_wide_ebus_override(
    acquisition_root: Path,
) -> None:
    frames = _make_acquisition(
        acquisition_root,
        snapshot_parameters={"Iris": 2},
        external_sources={
            "ebus": {
                "overrides": {"device.Iris": 5},
            },
        },
        overrides=[
            {
                "selector": {"frame_range": [0, 0]},
                "changes": {
                    "instrument": {
                        "optics": {"iris": {"position": 7}},
                    },
                },
                "reason": "frame override",
            },
        ],
    )

    metadata = extract_path_metadata(str(frames[0]), metadata_source="json")
    assert metadata.get("iris_source") == "frame_override"
    assert metadata.get("iris_position") == 7.0

    metadata_other = extract_path_metadata(str(frames[1]), metadata_source="json")
    assert metadata_other.get("iris_source") == "ebus_override"
    assert metadata_other.get("iris_position") == 5.0


def test_normalize_override_selectors_detects_zero_and_one_based_ranges() -> None:
    zero_based, zero_base = normalize_override_selectors(
        [{"selector": {"frame_range": [0, 1]}}],
        [0, 1],
    )
    one_based, one_base = normalize_override_selectors(
        [{"selector": {"frame_range": [1, 2]}}],
        [0, 1],
    )

    assert zero_base == 0
    assert zero_based[0]["selector"]["frame_range"] == [0, 1]
    assert one_base == 1
    assert one_based[0]["selector"]["frame_range"] == [0, 1]


def test_ambiguous_snapshot_discovery_falls_back_to_datacard(
    acquisition_root: Path,
) -> None:
    frames = _make_acquisition(
        acquisition_root,
        defaults={
            "camera_settings": {"exposure_us": 900},
            "instrument": {},
            "acquisition_settings": {},
        },
        snapshot_parameters={"Exposure": 500},
        extra_snapshot=True,
    )
    payload = _base_datacard(
        defaults={
            "camera_settings": {"exposure_us": 900},
            "instrument": {},
            "acquisition_settings": {},
        },
    )

    resolutions = resolve_ebus_canonical_fields(acquisition_root, payload)
    assert not resolutions.snapshot_loaded
    assert not resolutions.by_key()["camera_settings.exposure_us"].snapshot_present

    metadata = extract_path_metadata(str(frames[0]), metadata_source="json")
    assert metadata.get("exposure_source") == "acquisition_default"
    assert float(metadata["exposure_ms"]) == pytest.approx(0.9)


def test_session_default_applies_when_acquisition_omits_field(
    acquisition_root: Path,
) -> None:
    campaign_root = acquisition_root / "campaign"
    session_root = campaign_root / "01_sessions" / "2026-03-05__sess01"
    nested_root = session_root / "acquisitions" / "acq-0011__session_default"
    nested_root.mkdir(parents=True, exist_ok=True)
    _write_campaign_datacard(campaign_root)
    _write_session_datacard(
        session_root,
        session_defaults={
            "instrument": {
                "optics": {
                    "iris": {"position": 4},
                },
            },
        },
    )
    frames = _make_acquisition(
        nested_root,
        defaults={
            "camera_settings": {},
            "instrument": {},
            "acquisition_settings": {},
        },
    )

    metadata = extract_path_metadata(str(frames[0]), metadata_source="json")
    assert bool(metadata.get("json_metadata_available"))
    assert metadata.get("iris_source") == "session_default"
    assert metadata.get("iris_position") == 4.0


def test_campaign_default_applies_when_higher_layers_are_missing(
    acquisition_root: Path,
) -> None:
    campaign_root = acquisition_root / "campaign"
    session_root = campaign_root / "01_sessions" / "2026-03-05__sess01"
    nested_root = session_root / "acquisitions" / "acq-0011__campaign_default"
    nested_root.mkdir(parents=True, exist_ok=True)
    _write_campaign_datacard(
        campaign_root,
        campaign_defaults={
            "camera_settings": {"exposure_us": 1500},
        },
    )
    _write_session_datacard(session_root)
    frames = _make_acquisition(
        nested_root,
        defaults={
            "camera_settings": {},
            "instrument": {},
            "acquisition_settings": {},
        },
    )

    metadata = extract_path_metadata(str(frames[0]), metadata_source="json")
    assert metadata.get("exposure_source") == "campaign_default"
    assert float(metadata["exposure_ms"]) == pytest.approx(1.5)


def test_acquisition_default_beats_session_and_campaign_defaults(
    acquisition_root: Path,
) -> None:
    campaign_root = acquisition_root / "campaign"
    session_root = campaign_root / "01_sessions" / "2026-03-05__sess01"
    nested_root = session_root / "acquisitions" / "acq-0011__acquisition_default"
    nested_root.mkdir(parents=True, exist_ok=True)
    _write_campaign_datacard(
        campaign_root,
        campaign_defaults={
            "camera_settings": {"exposure_us": 1500},
        },
    )
    _write_session_datacard(
        session_root,
        session_defaults={
            "camera_settings": {"exposure_us": 2000},
        },
    )
    frames = _make_acquisition(
        nested_root,
        defaults={
            "camera_settings": {"exposure_us": 2500},
            "instrument": {},
            "acquisition_settings": {},
        },
    )

    metadata = extract_path_metadata(str(frames[0]), metadata_source="json")
    assert metadata.get("exposure_source") == "acquisition_default"
    assert float(metadata["exposure_ms"]) == pytest.approx(2.5)


def test_ebus_disabled_falls_back_to_json_defaults(acquisition_root: Path) -> None:
    frames = _make_acquisition(
        acquisition_root,
        defaults={
            "camera_settings": {"exposure_us": 900},
            "instrument": {
                "optics": {"iris": {"position": 3}},
            },
            "acquisition_settings": {},
        },
        external_sources={
            "ebus": {
                "enabled": False,
                "overrides": {"device.Iris": 5},
            },
        },
        snapshot_parameters={"Exposure": 500, "Iris": 2},
    )
    payload = _base_datacard(
        defaults={
            "camera_settings": {"exposure_us": 900},
            "instrument": {
                "optics": {"iris": {"position": 3}},
            },
            "acquisition_settings": {},
        },
        external_sources={
            "ebus": {
                "enabled": False,
                "overrides": {"device.Iris": 5},
            },
        },
    )

    resolutions = resolve_ebus_canonical_fields(acquisition_root, payload)
    assert not resolutions.snapshot_loaded
    metadata = extract_path_metadata(str(frames[0]), metadata_source="json")
    assert metadata.get("exposure_source") == "acquisition_default"
    assert float(metadata["exposure_ms"]) == pytest.approx(0.9)
    assert metadata.get("iris_source") == "acquisition_default"
    assert metadata.get("iris_position") == 3.0


@pytest.mark.ui
@pytest.mark.skipif(
    not _WIZARD_AVAILABLE,
    reason="PySide6 is not available in this environment.",
)
def test_non_overridable_snapshot_field_stays_out_of_defaults(
    acquisition_root: Path,
    dialog_factory,
) -> None:
    _make_acquisition(
        acquisition_root,
        snapshot_parameters={"Exposure": 500},
    )
    dialog = dialog_factory()

    editor = dialog._defaults_editors["camera_settings.exposure_us"]
    assert not editor.isEnabled()

    model = dialog._build_model_from_ui()
    assert model is not None
    assert get_dot_path(model.defaults, "camera_settings.exposure_us") is None
    assert "ebus" not in model.external_sources


@pytest.mark.ui
@pytest.mark.skipif(
    not _WIZARD_AVAILABLE,
    reason="PySide6 is not available in this environment.",
)
def test_overridable_snapshot_field_persists_to_canonical_defaults(
    acquisition_root: Path,
    dialog_factory,
) -> None:
    _make_acquisition(
        acquisition_root,
        snapshot_parameters={"Iris": 2},
    )
    dialog = dialog_factory()

    key = "instrument.optics.iris.position"
    spec = dialog._spec_for_key(key)
    assert spec is not None
    editor = dialog._defaults_editors[key]
    assert editor.isEnabled()
    dialog._set_editor_value(editor, spec, 5)

    model = dialog._build_model_from_ui()
    assert model is not None
    assert get_dot_path(model.defaults, key) == 5
    assert not (
        isinstance(model.external_sources.get("ebus"), dict)
        and bool(model.external_sources["ebus"].get("overrides"))
    )


@pytest.mark.ui
@pytest.mark.skipif(
    not _WIZARD_AVAILABLE,
    reason="PySide6 is not available in this environment.",
)
def test_existing_overridable_default_beats_snapshot_in_editor_and_preview(
    acquisition_root: Path,
    dialog_factory,
) -> None:
    _make_acquisition(
        acquisition_root,
        snapshot_parameters={"Iris": 0},
        defaults={
            "instrument": {
                "optics": {
                    "iris": {
                        "position": 1,
                    },
                },
            },
        },
    )
    dialog = dialog_factory()

    key = "instrument.optics.iris.position"
    spec = dialog._spec_for_key(key)
    assert spec is not None
    editor = dialog._defaults_editors[key]
    assert editor.isEnabled()
    assert dialog._get_editor_value(editor, spec) == 1

    model = dialog._build_model_from_ui()
    assert model is not None
    assert get_dot_path(model.defaults, key) == 1


@pytest.mark.ui
@pytest.mark.skipif(
    not _WIZARD_AVAILABLE,
    reason="PySide6 is not available in this environment.",
)
def test_existing_frame_override_for_snapshot_field_survives_round_trip(
    acquisition_root: Path,
    dialog_factory,
) -> None:
    _make_acquisition(
        acquisition_root,
        snapshot_parameters={"Exposure": 500},
        overrides=[
            {
                "selector": {"frame_range": [0, 0]},
                "changes": {"camera_settings": {"exposure_us": 2000}},
                "reason": "frame override",
            },
        ],
    )
    dialog = dialog_factory()

    assert len(dialog._existing_rows) == 1
    model = dialog._build_model_from_ui()
    assert model is not None
    assert any(
        row.changes.get("camera_settings.exposure_us") == 2000
        for row in model.overrides
    )


@pytest.mark.ui
@pytest.mark.skipif(
    not _WIZARD_AVAILABLE,
    reason="PySide6 is not available in this environment.",
)
def test_snapshot_backed_fields_remain_available_in_frame_mapping(
    acquisition_root: Path,
    dialog_factory,
) -> None:
    _make_acquisition(
        acquisition_root,
        snapshot_parameters={"Exposure": 500, "Iris": 2},
    )
    dialog = dialog_factory()

    override_keys = {spec.key for spec in dialog._override_specs()}
    assert "camera_settings.exposure_us" in override_keys
    assert "instrument.optics.iris.position" in override_keys

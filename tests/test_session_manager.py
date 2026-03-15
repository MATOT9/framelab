"""Tests for session-level acquisition management helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from framelab.acquisition_datacard import format_acquisition_folder_name
from framelab.payload_utils import read_json_dict
from framelab.plugins.data.session_manager_ui_state import (
    build_session_manager_action_state,
)
from framelab.session_manager import (
    add_acquisition,
    create_session,
    create_acquisition_batch,
    delete_session,
    copy_acquisition_datacard,
    delete_acquisition,
    inspect_session,
    paste_acquisition_datacard,
    preview_acquisition_batch,
    reindex_acquisitions,
    rename_acquisition_label,
    resolve_campaign_sessions_root,
    set_acquisition_ebus_enabled,
)


pytestmark = [pytest.mark.data, pytest.mark.core]


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
            "identity": {"label": "session"},
            "paths": {
                "session_root_rel": None,
                "acquisitions_root_rel": None,
                "notes_rel": None,
            },
            "session_defaults": {},
            "notes": "",
        },
    )


def _write_snapshot(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                '<?xml version="1.0"?>',
                '<puregevpersistencefile version="1.0">',
                '  <device name="" version="1.0">',
                "    <device>",
                '      <parameter name="Exposure">500</parameter>',
                "    </device>",
                "  </device>",
                "</puregevpersistencefile>",
            ],
        )
        + "\n",
        encoding="utf-8",
    )


def _acquisition_payload(folder_name: str, label: str | None = None) -> dict:
    return {
        "schema_version": "1.0",
        "entity": "acquisition",
        "identity": {
            "camera_id": None,
            "campaign_id": None,
            "session_id": None,
            "acquisition_id": folder_name,
            "label": label,
            "created_at_local": None,
            "finalized_at_local": None,
            "timezone": None,
        },
        "paths": {
            "frames_dir": "frames",
            "acquisition_root_rel": f"acquisitions/{folder_name}",
        },
        "intent": {
            "capture_type": "calibration",
            "subtype": "",
            "scene": "",
            "tags": [],
        },
        "defaults": {},
        "overrides": [],
        "quality": {
            "anomalies": [],
            "dropped_frames": [],
            "saturation_expected": False,
        },
        "external_sources": {},
    }


class _SessionHarness:
    def __init__(self, tmp_path: Path) -> None:
        self.session_root = tmp_path / "2026-03-05__sess01"
        self.acquisitions_root = self.session_root / "acquisitions"
        self.acquisitions_root.mkdir(parents=True, exist_ok=True)
        _write_session_datacard(self.session_root)

    def make_acquisition(
        self,
        number: int,
        *,
        label: str | None = None,
        with_datacard: bool = True,
        with_snapshot: bool = False,
        extra_payload: dict | None = None,
    ) -> Path:
        folder_name = format_acquisition_folder_name(number, label, width=4)
        root = self.acquisitions_root / folder_name
        (root / "frames").mkdir(parents=True, exist_ok=True)
        (root / "notes").mkdir(parents=True, exist_ok=True)
        (root / "thumbs").mkdir(parents=True, exist_ok=True)
        (root / "frames" / "f0.tiff").touch()
        if with_datacard:
            payload = _acquisition_payload(folder_name, label)
            if extra_payload:
                payload.update(extra_payload)
            _write_json(root / "acquisition_datacard.json", payload)
        if with_snapshot:
            _write_snapshot(root / "acq_config.pvcfg")
        return root


class _UiStateHarness:
    def __init__(self, tmp_path: Path) -> None:
        self.session_root = tmp_path / "2026-03-05__sess01"
        self.acquisitions_root = self.session_root / "acquisitions"
        self.acquisitions_root.mkdir(parents=True, exist_ok=True)
        _write_session_datacard(self.session_root)

    def make_acquisition(
        self,
        number: int,
        *,
        label: str | None = None,
        with_datacard: bool = True,
        ebus_enabled: bool = True,
    ) -> Path:
        folder_name = format_acquisition_folder_name(number, label, width=4)
        root = self.acquisitions_root / folder_name
        (root / "frames").mkdir(parents=True, exist_ok=True)
        if with_datacard:
            payload = _acquisition_payload(folder_name, label)
            payload["external_sources"] = {"ebus": {"enabled": ebus_enabled}}
            _write_json(root / "acquisition_datacard.json", payload)
        return root


@pytest.fixture
def session_harness(tmp_path: Path) -> _SessionHarness:
    return _SessionHarness(tmp_path)


@pytest.fixture
def ui_state_harness(tmp_path: Path) -> _UiStateHarness:
    return _UiStateHarness(tmp_path)


def test_detects_non_one_starting_number(session_harness: _SessionHarness) -> None:
    session_harness.make_acquisition(11, label="one")
    session_harness.make_acquisition(12, label="two")

    index = inspect_session(session_harness.session_root)
    assert index.starting_number == 11
    assert index.numbering_valid


def test_create_session_uses_nested_session_container_when_present(tmp_path: Path) -> None:
    campaign_root = tmp_path / "campaign-2026"
    sessions_root = campaign_root / "01_sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)

    result = create_session(campaign_root, "2026-03-06__sess02")

    created = sessions_root / "2026-03-06__sess02"
    assert resolve_campaign_sessions_root(campaign_root) == sessions_root.resolve()
    assert result.created_path == created
    assert created.joinpath("session_datacard.json").is_file()
    assert created.joinpath("acquisitions").is_dir()


def test_create_session_falls_back_to_campaign_root_when_no_session_container_exists(
    tmp_path: Path,
) -> None:
    campaign_root = tmp_path / "campaign-2026"
    campaign_root.mkdir(parents=True, exist_ok=True)

    result = create_session(campaign_root, "2026-03-06__sess02")

    created = campaign_root / "2026-03-06__sess02"
    assert resolve_campaign_sessions_root(campaign_root) == campaign_root.resolve()
    assert result.created_path == created
    assert created.joinpath("session_datacard.json").is_file()
    assert created.joinpath("acquisitions").is_dir()


def test_delete_session_removes_session_folder(tmp_path: Path) -> None:
    campaign_root = tmp_path / "campaign-2026"
    created = create_session(campaign_root, "2026-03-06__sess02").created_path
    assert created is not None

    result = delete_session(created)

    assert result.deleted_paths == (created,)
    assert not created.exists()


def test_add_acquisition_preserves_detected_base(
    session_harness: _SessionHarness,
) -> None:
    session_harness.make_acquisition(11, label="one")
    session_harness.make_acquisition(12, label="two")

    result = add_acquisition(session_harness.session_root, label="three")

    assert result.created_path is not None
    assert result.created_path.name == "acq-0013__three"
    index = inspect_session(session_harness.session_root)
    assert index.starting_number == 11
    assert [entry.folder_name for entry in index.entries] == [
        "acq-0011__one",
        "acq-0012__two",
        "acq-0013__three",
    ]


def test_preview_acquisition_batch_reports_labels_and_collisions(
    session_harness: _SessionHarness,
) -> None:
    session_harness.make_acquisition(11, label="one")
    session_harness.make_acquisition(12, label="taken")

    preview = preview_acquisition_batch(
        session_harness.session_root,
        count=3,
        starting_number=12,
        labels=("taken", "new-dark", None),
    )

    assert [entry.folder_name for entry in preview] == [
        "acq-0012__taken",
        "acq-0013__new-dark",
        "acq-0014",
    ]
    assert preview[0].collision_exists
    assert not preview[1].collision_exists
    assert not preview[2].collision_exists


def test_create_acquisition_batch_creates_multiple_folders(
    session_harness: _SessionHarness,
) -> None:
    session_harness.make_acquisition(11, label="one")

    result = create_acquisition_batch(
        session_harness.session_root,
        count=2,
        labels=("dark", "bright"),
    )

    assert [path.name for path in result.created_paths] == [
        "acq-0012__dark",
        "acq-0013__bright",
    ]
    for created_path in result.created_paths:
        assert created_path.joinpath("frames").is_dir()
        assert created_path.joinpath("notes").is_dir()
        assert created_path.joinpath("thumbs").is_dir()
    assert [entry.folder_name for entry in inspect_session(session_harness.session_root).entries] == [
        "acq-0011__one",
        "acq-0012__dark",
        "acq-0013__bright",
    ]


def test_delete_closes_gap_and_rewrites_identity_and_paths(
    session_harness: _SessionHarness,
) -> None:
    session_harness.make_acquisition(11, label="one")
    target = session_harness.make_acquisition(12, label="two")
    trailing = session_harness.make_acquisition(
        13,
        label="three",
        extra_payload={
            "identity": {
                "acquisition_id": "acq-0013__three",
                "label": "three",
            },
            "paths": {
                "frames_dir": "frames",
                "acquisition_root_rel": "acquisitions/acq-0013__three",
            },
        },
    )

    result = delete_acquisition(session_harness.session_root, target)

    assert result.deleted_paths == (target,)
    renamed = dict(result.renamed_paths)
    expected_new_root = session_harness.acquisitions_root / "acq-0012__three"
    assert renamed[trailing] == expected_new_root
    payload = read_json_dict(expected_new_root / "acquisition_datacard.json")
    assert payload is not None
    assert payload["identity"]["acquisition_id"] == "acq-0012__three"
    assert payload["identity"]["label"] == "three"
    assert payload["paths"]["acquisition_root_rel"] == "acquisitions/acq-0012__three"


def test_reindex_from_explicit_starting_number(
    session_harness: _SessionHarness,
) -> None:
    first = session_harness.make_acquisition(11, label="one")
    second = session_harness.make_acquisition(12, label="two")

    result = reindex_acquisitions(session_harness.session_root, starting_number=21)

    renamed = dict(result.renamed_paths)
    assert renamed[first] == session_harness.acquisitions_root / "acq-0021__one"
    assert renamed[second] == session_harness.acquisitions_root / "acq-0022__two"
    index = inspect_session(session_harness.session_root)
    assert index.starting_number == 21
    assert index.numbering_valid


def test_non_contiguous_numbering_warns_and_blocks_structural_edits(
    session_harness: _SessionHarness,
) -> None:
    session_harness.make_acquisition(11, label="one")
    gap_target = session_harness.make_acquisition(13, label="three")

    index = inspect_session(session_harness.session_root)
    assert not index.numbering_valid
    assert "not contiguous" in index.warning_text.lower()
    with pytest.raises(ValueError):
        add_acquisition(session_harness.session_root, label="blocked")
    with pytest.raises(ValueError):
        delete_acquisition(session_harness.session_root, gap_target)

    result = reindex_acquisitions(session_harness.session_root, starting_number=11)
    assert dict(result.renamed_paths)[gap_target] == (
        session_harness.acquisitions_root / "acq-0012__three"
    )


def test_copy_paste_normalizes_target_fields_and_strips_ebus_bookkeeping(
    session_harness: _SessionHarness,
) -> None:
    source = session_harness.make_acquisition(
        11,
        label="source",
        extra_payload={
            "identity": {
                "acquisition_id": "acq-0011__source",
                "label": "source",
            },
            "paths": {
                "frames_dir": "frames",
                "acquisition_root_rel": "acquisitions/acq-0011__source",
            },
            "external_sources": {
                "ebus": {
                    "enabled": False,
                    "overrides": {"device.Iris": 5},
                    "attached_file": "acq_config.pvcfg",
                    "source_hash_sha256": "deadbeef",
                    "attached_at_local": "2026-03-05T12:00:00",
                },
            },
        },
    )
    target = session_harness.make_acquisition(12, label="target", with_datacard=False)

    clipboard = copy_acquisition_datacard(source)
    assert clipboard is not None
    paste_acquisition_datacard(target, clipboard)

    payload = read_json_dict(target / "acquisition_datacard.json")
    assert payload is not None
    assert payload["identity"]["acquisition_id"] == "acq-0012__target"
    assert payload["identity"]["label"] == "target"
    assert payload["paths"]["acquisition_root_rel"] == "acquisitions/acq-0012__target"
    assert not payload["external_sources"]["ebus"]["enabled"]
    assert payload["external_sources"]["ebus"]["overrides"]["device.Iris"] == 5
    assert "attached_file" not in payload["external_sources"]["ebus"]
    assert "source_hash_sha256" not in payload["external_sources"]["ebus"]
    assert "attached_at_local" not in payload["external_sources"]["ebus"]


def test_toggle_ebus_enabled_persists_even_without_existing_datacard(
    session_harness: _SessionHarness,
) -> None:
    target = session_harness.make_acquisition(11, label="toggle", with_datacard=False)

    set_acquisition_ebus_enabled(target, False)
    payload = read_json_dict(target / "acquisition_datacard.json")
    assert payload is not None
    assert not payload["external_sources"]["ebus"]["enabled"]

    set_acquisition_ebus_enabled(target, True)
    payload = read_json_dict(target / "acquisition_datacard.json")
    assert payload is not None
    assert payload["external_sources"]["ebus"]["enabled"]


def test_rename_acquisition_label_removes_suffix_when_blank(
    session_harness: _SessionHarness,
) -> None:
    target = session_harness.make_acquisition(11, label="rename")

    result = rename_acquisition_label(target, None)

    assert result.renamed_paths[0][1] == session_harness.acquisitions_root / "acq-0011"
    payload = read_json_dict(
        session_harness.acquisitions_root / "acq-0011" / "acquisition_datacard.json",
    )
    assert payload is not None
    assert payload["identity"]["acquisition_id"] == "acq-0011"
    assert payload["identity"]["label"] is None


def test_action_state_for_valid_session_with_selected_entry(
    ui_state_harness: _UiStateHarness,
) -> None:
    ui_state_harness.make_acquisition(
        11,
        label="one",
        with_datacard=True,
        ebus_enabled=True,
    )
    index = inspect_session(ui_state_harness.session_root)
    entry = index.entries[0]

    state = build_session_manager_action_state(
        index,
        entry,
        clipboard_ready=True,
        has_ebus_tools=True,
    )

    assert state.load_selected_enabled
    assert state.add_enabled
    assert state.rename_enabled
    assert state.delete_enabled
    assert state.edit_datacard_enabled
    assert state.copy_datacard_enabled
    assert state.paste_datacard_enabled
    assert state.toggle_ebus_enabled
    assert state.reindex_enabled
    assert state.toggle_ebus_text == "Disable eBUS Snapshot"


def test_action_state_blocks_structural_edits_for_invalid_numbering(
    ui_state_harness: _UiStateHarness,
) -> None:
    ui_state_harness.make_acquisition(11, label="one")
    ui_state_harness.make_acquisition(13, label="three", with_datacard=False)
    index = inspect_session(ui_state_harness.session_root)
    entry = index.entries[1]

    state = build_session_manager_action_state(
        index,
        entry,
        clipboard_ready=False,
        has_ebus_tools=False,
    )

    assert state.load_selected_enabled
    assert not state.add_enabled
    assert state.rename_enabled
    assert not state.delete_enabled
    assert state.edit_datacard_enabled
    assert not state.copy_datacard_enabled
    assert not state.paste_datacard_enabled
    assert not state.toggle_ebus_enabled
    assert state.reindex_enabled
    assert state.toggle_ebus_text == "Disable eBUS Snapshot"


def test_action_state_for_no_selection_keeps_session_level_actions_only(
    ui_state_harness: _UiStateHarness,
) -> None:
    ui_state_harness.make_acquisition(11, label="one")
    index = inspect_session(ui_state_harness.session_root)

    state = build_session_manager_action_state(
        index,
        None,
        clipboard_ready=True,
        has_ebus_tools=True,
    )

    assert not state.load_selected_enabled
    assert state.add_enabled
    assert not state.rename_enabled
    assert not state.delete_enabled
    assert not state.edit_datacard_enabled
    assert not state.copy_datacard_enabled
    assert not state.paste_datacard_enabled
    assert not state.toggle_ebus_enabled
    assert state.reindex_enabled
    assert state.toggle_ebus_text == "Toggle eBUS Snapshot"

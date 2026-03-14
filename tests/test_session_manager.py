"""Tests for session-level acquisition management helpers."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from framelab.acquisition_datacard import format_acquisition_folder_name
from framelab.payload_utils import read_json_dict
from framelab.plugins.data.session_manager_ui_state import (
    build_session_manager_action_state,
)
from framelab.session_manager import (
    add_acquisition,
    copy_acquisition_datacard,
    delete_acquisition,
    inspect_session,
    paste_acquisition_datacard,
    reindex_acquisitions,
    rename_acquisition_label,
    set_acquisition_ebus_enabled,
)


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


class SessionManagerServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.session_root = Path(self._tmpdir.name) / "2026-03-05__sess01"
        self.acquisitions_root = self.session_root / "acquisitions"
        self.acquisitions_root.mkdir(parents=True, exist_ok=True)
        _write_session_datacard(self.session_root)

    def _make_acquisition(
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

    def test_detects_non_one_starting_number(self) -> None:
        self._make_acquisition(11, label="one")
        self._make_acquisition(12, label="two")

        index = inspect_session(self.session_root)
        self.assertEqual(index.starting_number, 11)
        self.assertTrue(index.numbering_valid)

    def test_add_acquisition_preserves_detected_base(self) -> None:
        self._make_acquisition(11, label="one")
        self._make_acquisition(12, label="two")

        result = add_acquisition(self.session_root, label="three")

        self.assertIsNotNone(result.created_path)
        assert result.created_path is not None
        self.assertEqual(result.created_path.name, "acq-0013__three")
        index = inspect_session(self.session_root)
        self.assertEqual(index.starting_number, 11)
        self.assertEqual(
            [entry.folder_name for entry in index.entries],
            [
                "acq-0011__one",
                "acq-0012__two",
                "acq-0013__three",
            ],
        )

    def test_delete_closes_gap_and_rewrites_identity_and_paths(self) -> None:
        self._make_acquisition(11, label="one")
        target = self._make_acquisition(12, label="two")
        trailing = self._make_acquisition(
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

        result = delete_acquisition(self.session_root, target)

        self.assertEqual(result.deleted_paths, (target,))
        renamed = dict(result.renamed_paths)
        expected_new_root = self.acquisitions_root / "acq-0012__three"
        self.assertEqual(renamed[trailing], expected_new_root)
        payload = read_json_dict(expected_new_root / "acquisition_datacard.json")
        assert payload is not None
        self.assertEqual(payload["identity"]["acquisition_id"], "acq-0012__three")
        self.assertEqual(payload["identity"]["label"], "three")
        self.assertEqual(
            payload["paths"]["acquisition_root_rel"],
            "acquisitions/acq-0012__three",
        )

    def test_reindex_from_explicit_starting_number(self) -> None:
        first = self._make_acquisition(11, label="one")
        second = self._make_acquisition(12, label="two")

        result = reindex_acquisitions(self.session_root, starting_number=21)

        renamed = dict(result.renamed_paths)
        self.assertEqual(
            renamed[first],
            self.acquisitions_root / "acq-0021__one",
        )
        self.assertEqual(
            renamed[second],
            self.acquisitions_root / "acq-0022__two",
        )
        index = inspect_session(self.session_root)
        self.assertEqual(index.starting_number, 21)
        self.assertTrue(index.numbering_valid)

    def test_non_contiguous_numbering_warns_and_blocks_structural_edits(self) -> None:
        self._make_acquisition(11, label="one")
        gap_target = self._make_acquisition(13, label="three")

        index = inspect_session(self.session_root)
        self.assertFalse(index.numbering_valid)
        self.assertIn("not contiguous", index.warning_text.lower())
        with self.assertRaises(ValueError):
            add_acquisition(self.session_root, label="blocked")
        with self.assertRaises(ValueError):
            delete_acquisition(self.session_root, gap_target)

        result = reindex_acquisitions(self.session_root, starting_number=11)
        self.assertEqual(
            dict(result.renamed_paths)[gap_target],
            self.acquisitions_root / "acq-0012__three",
        )

    def test_copy_paste_normalizes_target_fields_and_strips_ebus_bookkeeping(self) -> None:
        source = self._make_acquisition(
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
        target = self._make_acquisition(12, label="target", with_datacard=False)

        clipboard = copy_acquisition_datacard(source)
        self.assertIsNotNone(clipboard)
        assert clipboard is not None
        paste_acquisition_datacard(target, clipboard)

        payload = read_json_dict(target / "acquisition_datacard.json")
        assert payload is not None
        self.assertEqual(payload["identity"]["acquisition_id"], "acq-0012__target")
        self.assertEqual(payload["identity"]["label"], "target")
        self.assertEqual(
            payload["paths"]["acquisition_root_rel"],
            "acquisitions/acq-0012__target",
        )
        self.assertFalse(payload["external_sources"]["ebus"]["enabled"])
        self.assertEqual(
            payload["external_sources"]["ebus"]["overrides"]["device.Iris"],
            5,
        )
        self.assertNotIn("attached_file", payload["external_sources"]["ebus"])
        self.assertNotIn("source_hash_sha256", payload["external_sources"]["ebus"])
        self.assertNotIn("attached_at_local", payload["external_sources"]["ebus"])

    def test_toggle_ebus_enabled_persists_even_without_existing_datacard(self) -> None:
        target = self._make_acquisition(11, label="toggle", with_datacard=False)

        set_acquisition_ebus_enabled(target, False)
        payload = read_json_dict(target / "acquisition_datacard.json")
        assert payload is not None
        self.assertFalse(payload["external_sources"]["ebus"]["enabled"])

        set_acquisition_ebus_enabled(target, True)
        payload = read_json_dict(target / "acquisition_datacard.json")
        assert payload is not None
        self.assertTrue(payload["external_sources"]["ebus"]["enabled"])

    def test_rename_acquisition_label_removes_suffix_when_blank(self) -> None:
        target = self._make_acquisition(11, label="rename")

        result = rename_acquisition_label(target, None)

        self.assertEqual(
            result.renamed_paths[0][1],
            self.acquisitions_root / "acq-0011",
        )
        payload = read_json_dict(
            self.acquisitions_root / "acq-0011" / "acquisition_datacard.json",
        )
        assert payload is not None
        self.assertEqual(payload["identity"]["acquisition_id"], "acq-0011")
        self.assertIsNone(payload["identity"]["label"])


class SessionManagerUiStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.session_root = Path(self._tmpdir.name) / "2026-03-05__sess01"
        self.acquisitions_root = self.session_root / "acquisitions"
        self.acquisitions_root.mkdir(parents=True, exist_ok=True)
        _write_session_datacard(self.session_root)

    def _make_acquisition(
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

    def test_action_state_for_valid_session_with_selected_entry(self) -> None:
        self._make_acquisition(11, label="one", with_datacard=True, ebus_enabled=True)
        index = inspect_session(self.session_root)
        entry = index.entries[0]

        state = build_session_manager_action_state(
            index,
            entry,
            clipboard_ready=True,
            has_ebus_tools=True,
        )

        self.assertTrue(state.load_selected_enabled)
        self.assertTrue(state.add_enabled)
        self.assertTrue(state.rename_enabled)
        self.assertTrue(state.delete_enabled)
        self.assertTrue(state.edit_datacard_enabled)
        self.assertTrue(state.copy_datacard_enabled)
        self.assertTrue(state.paste_datacard_enabled)
        self.assertTrue(state.toggle_ebus_enabled)
        self.assertTrue(state.reindex_enabled)
        self.assertEqual(state.toggle_ebus_text, "Disable eBUS Snapshot")

    def test_action_state_blocks_structural_edits_for_invalid_numbering(self) -> None:
        self._make_acquisition(11, label="one")
        self._make_acquisition(13, label="three", with_datacard=False)
        index = inspect_session(self.session_root)
        entry = index.entries[1]

        state = build_session_manager_action_state(
            index,
            entry,
            clipboard_ready=False,
            has_ebus_tools=False,
        )

        self.assertTrue(state.load_selected_enabled)
        self.assertFalse(state.add_enabled)
        self.assertTrue(state.rename_enabled)
        self.assertFalse(state.delete_enabled)
        self.assertTrue(state.edit_datacard_enabled)
        self.assertFalse(state.copy_datacard_enabled)
        self.assertFalse(state.paste_datacard_enabled)
        self.assertFalse(state.toggle_ebus_enabled)
        self.assertTrue(state.reindex_enabled)
        self.assertEqual(state.toggle_ebus_text, "Disable eBUS Snapshot")

    def test_action_state_for_no_selection_keeps_session_level_actions_only(self) -> None:
        self._make_acquisition(11, label="one")
        index = inspect_session(self.session_root)

        state = build_session_manager_action_state(
            index,
            None,
            clipboard_ready=True,
            has_ebus_tools=True,
        )

        self.assertFalse(state.load_selected_enabled)
        self.assertTrue(state.add_enabled)
        self.assertFalse(state.rename_enabled)
        self.assertFalse(state.delete_enabled)
        self.assertFalse(state.edit_datacard_enabled)
        self.assertFalse(state.copy_datacard_enabled)
        self.assertFalse(state.paste_datacard_enabled)
        self.assertFalse(state.toggle_ebus_enabled)
        self.assertTrue(state.reindex_enabled)
        self.assertEqual(state.toggle_ebus_text, "Toggle eBUS Snapshot")


if __name__ == "__main__":
    unittest.main()

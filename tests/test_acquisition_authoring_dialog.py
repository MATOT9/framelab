"""Tests for workflow-native acquisition authoring dialog polish."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6 import QtWidgets as qtw

from framelab.acquisition_authoring_dialog import AcquisitionAuthoringDialog


pytestmark = [pytest.mark.ui, pytest.mark.data]


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
            "identity": {"label": session_root.name},
            "paths": {
                "session_root_rel": None,
                "acquisitions_root_rel": "acquisitions",
                "notes_rel": None,
            },
            "session_defaults": {},
            "notes": "",
        },
    )


def test_acquisition_authoring_dialog_uses_stable_preview_resize_modes(
    tmp_path: Path,
    qapp,
) -> None:
    session_root = tmp_path / "2026-03-05__sess01"
    acquisitions_root = session_root / "acquisitions"
    acquisitions_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)

    dialog = AcquisitionAuthoringDialog(session_root)
    try:
        header = dialog._preview_table.horizontalHeader()

        assert dialog._labels_edit.minimumHeight() >= 92
        assert header.sectionResizeMode(0) == qtw.QHeaderView.ResizeToContents
        assert header.sectionResizeMode(1) == qtw.QHeaderView.Stretch
        assert header.sectionResizeMode(2) == qtw.QHeaderView.Stretch
        assert header.sectionResizeMode(3) == qtw.QHeaderView.ResizeToContents
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()

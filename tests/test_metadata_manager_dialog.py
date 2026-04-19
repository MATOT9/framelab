from __future__ import annotations

import json
from pathlib import Path

import pytest

from framelab.metadata_manager_dialog import MetadataManagerDialog
from framelab.node_metadata import load_nodecard, save_nodecard


pytestmark = [pytest.mark.ui, pytest.mark.core]


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _make_workspace_with_metadata(
    tmp_path: Path,
) -> tuple[Path, Path, Path, str]:
    workspace_root = tmp_path / "calibration"
    camera_root = workspace_root / "camera-a"
    session_root = camera_root / "campaign-2026" / "2026-03-05__sess01"
    acquisitions_root = session_root / "acquisitions"
    acquisitions_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)

    save_nodecard(
        camera_root,
        {"camera_settings": {"exposure_us": 1200}},
        profile_id="calibration",
        node_type_id="camera",
    )
    save_nodecard(
        session_root,
        {"instrument": {"optics": {"iris": {"position": 5}}}},
        profile_id="calibration",
        node_type_id="session",
    )

    session_node_id = (
        "calibration:session:"
        "camera-a/campaign-2026/2026-03-05__sess01"
    )
    return workspace_root, camera_root, session_root, session_node_id


def _make_trials_workspace_with_metadata(
    tmp_path: Path,
) -> tuple[Path, Path, str]:
    workspace_root = tmp_path / "trials"
    session_root = (
        workspace_root
        / "2026"
        / "campaign-07"
        / "camera-a"
        / "2026-03-05__sess01"
    )
    acquisitions_root = session_root / "acquisitions"
    acquisitions_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)

    save_nodecard(
        session_root,
        {"workflow": {"conditions": "dry"}},
        profile_id="trials",
        node_type_id="session",
    )

    session_node_id = "trials:session:2026/campaign-07/camera-a/2026-03-05__sess01"
    return workspace_root, session_root, session_node_id


def _row_for_key(table, key: str) -> int:
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        if item is not None and item.toolTip() == key:
            return row
    raise AssertionError(f"could not find row for metadata key {key!r}")


def test_metadata_manager_displays_effective_and_local_metadata(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, _camera_root, _session_root, session_node_id = (
        _make_workspace_with_metadata(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )

    window._open_metadata_manager_dialog()
    dialog = window._metadata_manager_dialog
    assert isinstance(dialog, MetadataManagerDialog)
    assert dialog.windowTitle() == "Advanced Metadata Tools"
    assert dialog._advanced_button.isHidden()
    assert not dialog._add_field_button.isHidden()
    assert not dialog._demote_field_button.isHidden()
    assert dialog._add_field_button.toolTip()
    assert dialog._add_group_button.toolTip()
    assert dialog._apply_template_button.toolTip()
    assert dialog._promote_field_button.toolTip()
    assert dialog._demote_field_button.toolTip()
    assert dialog._save_button.toolTip()

    exposure_row = _row_for_key(dialog._effective_table, "camera_settings.exposure_us")
    iris_row = _row_for_key(dialog._effective_table, "instrument.optics.iris.position")

    exposure_source = dialog._effective_table.cellWidget(exposure_row, 2)
    iris_source = dialog._effective_table.cellWidget(iris_row, 2)

    assert exposure_source.text() == "Inherited"
    assert iris_source.text() == "Local"
    assert dialog._local_table.rowCount() == 1


def test_metadata_manager_saves_local_metadata_and_refreshes_host_scope(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, session_root, session_node_id = (
        _make_trials_workspace_with_metadata(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "trials",
        active_node_id=session_node_id,
    )

    dialog = MetadataManagerDialog(window)
    dialog._add_local_row()
    new_row = dialog._local_table.rowCount() - 1
    dialog._local_table.item(new_row, 0).setText("custom.operator")
    dialog._local_table.item(new_row, 1).setText("maxime")
    dialog._save_local_metadata()

    saved = load_nodecard(session_root)
    assert saved.metadata["workflow"]["conditions"] == "dry"
    assert saved.metadata["custom"]["operator"] == "maxime"
    assert window.dataset_state.scope_effective_metadata["custom.operator"] == "maxime"

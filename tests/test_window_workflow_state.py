"""Window-level tests for persisted workflow controller state."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PySide6 import QtGui, QtWidgets as qtw
from tifffile import imwrite

import framelab.main_window.chrome as chrome_module
import framelab.main_window.data_page as data_page_module
import framelab.window as window_module
from framelab.ui_primitives import StatusChip
from framelab.ui_settings import DensityMode, UiPreferences, UiStateSnapshot, UiStateStore


pytestmark = [pytest.mark.ui, pytest.mark.core]


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


def _write_acquisition_datacard(acquisition_root: Path) -> None:
    _write_json(
        acquisition_root / "acquisition_datacard.json",
        {
            "schema_version": "1.0",
            "entity": "acquisition",
            "identity": {"acquisition_id": acquisition_root.name},
            "paths": {"frames_dir": "frames"},
            "defaults": {},
            "overrides": [],
            "quality": {},
            "external_sources": {},
        },
    )


def _write_frame(path: Path, value: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    imwrite(path, np.full((4, 4), value, dtype=np.uint16))


def _make_calibration_workspace(tmp_path: Path) -> tuple[Path, str]:
    workspace_root = tmp_path / "calibration"
    session_root = (
        workspace_root
        / "camera-a"
        / "campaign-2026"
        / "2026-03-05__sess01"
    )
    acquisitions_root = session_root / "acquisitions"
    acquisitions_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)

    first = acquisitions_root / "acq-0011__dark"
    (first / "frames").mkdir(parents=True, exist_ok=True)
    _write_acquisition_datacard(first)

    second = acquisitions_root / "acq-0012__bright"
    (second / "frames").mkdir(parents=True, exist_ok=True)
    _write_acquisition_datacard(second)

    return (
        workspace_root,
        (
            "calibration:acquisition:"
            "camera-a/campaign-2026/2026-03-05__sess01/acquisitions/acq-0012__bright"
        ),
    )


def _make_calibration_workspace_with_frames(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, str, str]:
    workspace_root = tmp_path / "calibration"
    session_root = (
        workspace_root
        / "camera-a"
        / "campaign-2026"
        / "2026-03-05__sess01"
    )
    acquisitions_root = session_root / "acquisitions"
    acquisitions_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)

    first = acquisitions_root / "acq-0011__dark"
    first.mkdir(parents=True, exist_ok=True)
    _write_acquisition_datacard(first)
    _write_frame(first / "frames" / "f0.tiff", 10)

    second = acquisitions_root / "acq-0012__bright"
    second.mkdir(parents=True, exist_ok=True)
    _write_acquisition_datacard(second)
    _write_frame(second / "frames" / "f0.tiff", 20)

    session_node_id = (
        "calibration:session:"
        "camera-a/campaign-2026/2026-03-05__sess01"
    )
    acquisition_node_id = (
        "calibration:acquisition:"
        "camera-a/campaign-2026/2026-03-05__sess01/acquisitions/acq-0011__dark"
    )
    return (
        workspace_root,
        session_root,
        first,
        second,
        session_node_id,
        acquisition_node_id,
    )


def _make_trials_workspace_with_frames(
    tmp_path: Path,
) -> tuple[Path, Path, Path, str]:
    workspace_root = tmp_path / "trials"
    session_root = workspace_root / "2026" / "campaign-alpha" / "camera-a" / "session-1"
    acquisitions_root = session_root / "acquisitions"
    acquisitions_root.mkdir(parents=True, exist_ok=True)
    _write_session_datacard(session_root)

    acquisition_root = acquisitions_root / "acq-0011__scene"
    acquisition_root.mkdir(parents=True, exist_ok=True)
    _write_acquisition_datacard(acquisition_root)
    _write_frame(acquisition_root / "frames" / "f0.tiff", 25)

    acquisition_node_id = (
        "trials:acquisition:"
        "2026/campaign-alpha/camera-a/session-1/acquisitions/acq-0011__scene"
    )
    return (
        workspace_root,
        session_root,
        acquisition_root,
        acquisition_node_id,
    )


def test_window_does_not_restore_workflow_context_from_preferences_cache(
    tmp_path: Path,
    monkeypatch,
    qapp,
) -> None:
    config_path = tmp_path / "preferences.ini"
    workspace_root, active_node_id = _make_calibration_workspace(tmp_path)
    config_path.write_text(
        "\n".join(
            [
                "[workspace]",
                f"workflow_root = {workspace_root}",
                "workflow_profile_id = calibration",
                "workflow_anchor_type_id = root",
                f"workflow_active_node_id = {active_node_id}",
            ],
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        window_module,
        "UiStateStore",
        lambda: UiStateStore(config_path),
    )

    window = window_module.FrameLabWindow(enabled_plugin_ids=())
    try:
        assert window.workflow_state_controller.profile_id is None
        assert window.workflow_state_controller.active_node_id is None
        assert window.metadata_state_controller.resolve_active_node_metadata() is None
        assert window.folder_edit.text() == ""
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_window_persists_preferences_without_restoring_cached_workflow_state(
    tmp_path: Path,
    monkeypatch,
    qapp,
) -> None:
    config_path = tmp_path / "preferences.ini"
    store = UiStateStore(config_path)
    store.save(
        UiStateSnapshot(
            preferences=UiPreferences(
                theme_mode="light",
                density_mode=DensityMode.COMPACT,
                show_image_preview=False,
                show_histogram_preview=True,
                restore_last_tab=False,
            ),
        ),
    )

    monkeypatch.setattr(
        window_module,
        "UiStateStore",
        lambda: UiStateStore(config_path),
    )

    window = window_module.FrameLabWindow(enabled_plugin_ids=())
    try:
        assert window.workflow_state_controller.profile_id is None
        assert window.workflow_state_controller.active_node_id is None
        assert window.ui_preferences.theme_mode == "light"
        assert window.ui_preferences.density_mode == DensityMode.COMPACT
        assert window.show_image_preview is False
        assert window.show_histogram_preview is True

        window._save_ui_state()
        reloaded = store.load()

        assert reloaded.preferences.theme_mode == "light"
        assert reloaded.preferences.density_mode == DensityMode.COMPACT
        assert reloaded.preferences.show_image_preview is False
        assert reloaded.preferences.show_histogram_preview is True
        assert reloaded.workflow_workspace_root is None
        assert reloaded.workflow_profile_id is None
        assert reloaded.workflow_anchor_type_id is None
        assert reloaded.workflow_active_node_id is None
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_window_starts_with_no_skip_rules_even_if_legacy_cache_exists(
    tmp_path: Path,
    monkeypatch,
    qapp,
) -> None:
    config_path = tmp_path / "preferences.ini"
    config_path.write_text(
        "\n".join(
            [
                "[scan]",
                "skip_patterns = *.bak",
                "  notes",
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        window_module,
        "UiStateStore",
        lambda: UiStateStore(config_path),
    )

    window = window_module.FrameLabWindow(enabled_plugin_ids=())
    try:
        assert window.skip_patterns == []
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_set_workflow_context_syncs_folder_edit_and_scope_snapshot(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, session_root, _first, _second, session_node_id, _acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())

    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )

    assert window.folder_edit.text() == str(session_root.resolve())
    assert window.dataset_state.scope_snapshot.source == "workflow"
    assert window.dataset_state.scope_snapshot.kind == "session"
    assert window.dataset_state.scope_snapshot.workflow_profile_id == "calibration"
    assert window.dataset_state.scope_snapshot.workflow_anchor_type_id == "root"
    assert not window.dataset_state.scope_snapshot.workflow_is_partial
    assert window.dataset_state.scope_snapshot.active_node_id == session_node_id
    assert [node.type_id for node in window.dataset_state.scope_snapshot.ancestor_chain] == [
        "root",
        "camera",
        "campaign",
        "session",
    ]
    assert window.recent_workflow_entries()[0].workspace_root == str(workspace_root.resolve())
    assert window.recent_workflow_entries()[0].profile_id == "calibration"
    assert window.recent_workflow_entries()[0].anchor_type_id == "root"
    assert window.recent_workflow_entries()[0].active_node_id == session_node_id


def test_workflow_shell_breadcrumb_reflects_active_context(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
) -> None:
    workspace_root, session_root, _first, _second, session_node_id, _acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    config_path = tmp_path / "preferences.ini"
    monkeypatch.setattr(
        window_module,
        "UiStateStore",
        lambda: UiStateStore(config_path),
    )
    window = framelab_window_factory(enabled_plugin_ids=())

    empty_chips = [
        chip.text()
        for chip in window._workflow_context_breadcrumb.findChildren(StatusChip)
    ]
    assert empty_chips == ["No workflow selected"]

    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )

    texts = [
        chip.text()
        for chip in window._workflow_context_breadcrumb.findChildren(StatusChip)
    ]
    assert texts[0] == "Calibration"
    assert texts[-1] == session_root.name


def test_partial_workflow_shell_breadcrumb_shows_anchor_scope(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    (
        _workspace_root,
        session_root,
        _first,
        _second,
        _session_node_id,
        acquisition_node_id,
    ) = _make_calibration_workspace_with_frames(tmp_path)
    window = framelab_window_factory(enabled_plugin_ids=())

    window.set_workflow_context(
        str(session_root),
        "calibration",
        anchor_type_id="session",
        active_node_id="calibration:acquisition:acquisitions/acq-0011__dark",
    )

    texts = [
        chip.text()
        for chip in window._workflow_context_breadcrumb.findChildren(StatusChip)
    ]
    assert texts[:3] == ["Calibration", "Session subtree", session_root.name]
    assert texts[-1] == "acq-0011__dark"
    assert window.dataset_state.scope_summary_value() == (
        "Acquisition: acq-0011__dark (Session subtree)"
    )


def test_workflow_explorer_toggle_action_controls_fallback_breadcrumb(
    framelab_window_factory,
    process_events,
) -> None:
    window = framelab_window_factory(enabled_plugin_ids=())

    assert not hasattr(window, "_workflow_context_select_button")
    assert window.view_workflow_explorer_action is window.toolbar_workflow_explorer_action
    assert (
        window.view_workflow_explorer_action.shortcut().toString()
        == QtGui.QKeySequence("Ctrl+Shift+W").toString()
    )
    assert window.view_workflow_explorer_action in window._main_toolbar.actions()
    assert not window._workflow_explorer_dock.isHidden()
    assert window._workflow_context_row.isHidden()

    window.view_workflow_explorer_action.trigger()
    process_events()

    assert window._workflow_explorer_dock.isHidden()
    assert not window._workflow_context_row.isHidden()

    window.view_workflow_explorer_action.trigger()
    process_events()


def test_window_disables_animated_docks_on_windows(
    framelab_window_factory,
    monkeypatch,
) -> None:
    monkeypatch.setattr(chrome_module.sys, "platform", "win32")

    window = framelab_window_factory(enabled_plugin_ids=())

    assert not bool(window.dockOptions() & qtw.QMainWindow.AnimatedDocks)


def test_window_keeps_animated_docks_on_non_windows(
    framelab_window_factory,
    monkeypatch,
) -> None:
    monkeypatch.setattr(chrome_module.sys, "platform", "linux")

    window = framelab_window_factory(enabled_plugin_ids=())

    assert bool(window.dockOptions() & qtw.QMainWindow.AnimatedDocks)


def test_datacard_wizard_registers_window_shortcut(
    framelab_window_factory,
) -> None:
    window = framelab_window_factory(
        enabled_plugin_ids=("acquisition_datacard_wizard",),
    )

    action = getattr(window, "_acquisition_datacard_wizard_shortcut_action", None)

    assert isinstance(action, QtGui.QAction)
    assert (
        action.shortcut().toString()
        == QtGui.QKeySequence("Ctrl+Shift+D").toString()
    )

    assert window._workflow_explorer_dock.isHidden() != window._workflow_context_row.isHidden()


def test_load_folder_uses_active_workflow_scope_and_resolves_entered_child_node(
    tmp_path: Path,
    framelab_window_factory,
    wait_for_dataset_load,
) -> None:
    workspace_root, session_root, first, _second, session_node_id, acquisition_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )

    window.load_folder()
    wait_for_dataset_load(window)
    assert window.dataset_state.dataset_root == session_root.resolve()
    assert window.dataset_state.path_count() == 2
    assert window.dataset_state.scope_snapshot.active_node_id == session_node_id

    window.folder_edit.setText(str(first / "frames"))
    window.load_folder()
    wait_for_dataset_load(window)

    assert window.workflow_state_controller.active_node_id == acquisition_node_id
    assert window.dataset_state.dataset_root == first.resolve()
    assert window.dataset_state.path_count() == 1
    assert window.folder_edit.text() == str(first.resolve())


def test_unstructured_workflow_loads_as_custom_and_still_scans_tiffs(
    tmp_path: Path,
    framelab_window_factory,
    wait_for_dataset_load,
) -> None:
    folder = tmp_path / "custom-scope"
    folder.mkdir()
    imwrite(folder / "sample.tiff", np.full((4, 4), 21, dtype=np.uint16))
    window = framelab_window_factory(enabled_plugin_ids=())

    window.set_workflow_context(str(folder), "calibration")

    assert window.workflow_state_controller.profile_id == "custom"
    assert window.workflow_state_controller.is_custom_workspace()
    assert window.folder_edit.text() == str(folder.resolve())
    assert window.dataset_state.scope_snapshot.kind == "custom"

    window.load_folder()
    wait_for_dataset_load(window)

    assert window.dataset_state.dataset_root == folder.resolve()
    assert window.dataset_state.path_count() == 1


def test_loading_structured_calibration_folder_from_custom_switches_workflow(
    tmp_path: Path,
    framelab_window_factory,
    wait_for_dataset_load,
) -> None:
    custom_root = tmp_path / "custom-root"
    custom_root.mkdir()
    imwrite(custom_root / "sample.tiff", np.full((4, 4), 9, dtype=np.uint16))
    (
        _workspace_root,
        _session_root,
        first,
        _second,
        _session_node_id,
        _acquisition_node_id,
    ) = _make_calibration_workspace_with_frames(tmp_path)
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(str(custom_root), "calibration")

    window.folder_edit.setText(str(first / "frames"))
    window.load_folder()
    wait_for_dataset_load(window)

    assert window.workflow_state_controller.profile_id == "calibration"
    assert window.workflow_state_controller.anchor_type_id == "acquisition"
    assert window.workflow_state_controller.active_node_id == "calibration:acquisition"
    assert window.dataset_state.dataset_root == first.resolve()
    assert "Detected Calibration workflow" in window.statusBar().currentMessage()


def test_loading_structured_trials_folder_from_custom_switches_workflow(
    tmp_path: Path,
    framelab_window_factory,
    wait_for_dataset_load,
) -> None:
    custom_root = tmp_path / "custom-root"
    custom_root.mkdir()
    imwrite(custom_root / "sample.tiff", np.full((4, 4), 9, dtype=np.uint16))
    _workspace_root, _session_root, acquisition_root, _acquisition_node_id = (
        _make_trials_workspace_with_frames(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(str(custom_root), "calibration")

    window.folder_edit.setText(str(acquisition_root / "frames"))
    window.load_folder()
    wait_for_dataset_load(window)

    assert window.workflow_state_controller.profile_id == "trials"
    assert window.workflow_state_controller.anchor_type_id == "acquisition"
    assert window.workflow_state_controller.active_node_id == "trials:acquisition"
    assert window.dataset_state.dataset_root == acquisition_root.resolve()
    assert "Detected Trials workflow" in window.statusBar().currentMessage()


def test_custom_workflow_can_scan_plain_tiff_subfolder_without_reverting_to_root(
    tmp_path: Path,
    framelab_window_factory,
    wait_for_dataset_load,
) -> None:
    custom_root = tmp_path / "custom-root"
    custom_root.mkdir()
    imwrite(custom_root / "sample.tiff", np.full((4, 4), 9, dtype=np.uint16))
    plain_child = custom_root / "nested"
    plain_child.mkdir()
    imwrite(plain_child / "nested.tiff", np.full((4, 4), 12, dtype=np.uint16))

    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(str(custom_root), "calibration")

    window.folder_edit.setText(str(plain_child))
    window.load_folder()
    wait_for_dataset_load(window)

    assert window.workflow_state_controller.profile_id == "custom"
    assert window.dataset_state.dataset_root == plain_child.resolve()
    assert window.dataset_state.scope_snapshot.source == "manual"


def test_workflow_scope_click_does_not_unload_mismatched_loaded_dataset(
    tmp_path: Path,
    framelab_window_factory,
    wait_for_dataset_load,
    wait_until,
) -> None:
    workspace_root, _session_root, first, second, session_node_id, _acquisition_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    second_node_id = (
        "calibration:acquisition:"
        "camera-a/campaign-2026/2026-03-05__sess01/acquisitions/acq-0012__bright"
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )
    window.folder_edit.setText(str(first))
    window.load_folder()
    wait_for_dataset_load(window)

    dock = window._workflow_explorer_dock
    dock._tree.setCurrentItem(dock._item_by_node_id[second_node_id])
    wait_until(
        lambda: window.workflow_state_controller.active_node_id == second_node_id,
        timeout_ms=1000,
    )

    assert window.dataset_state.has_loaded_data()
    assert window.dataset_state.dataset_root == first.resolve()
    assert window.folder_edit.text() == str(second.resolve())


def test_hidden_metadata_inspector_is_marked_dirty_instead_of_refreshing_inline(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
    wait_until,
) -> None:
    workspace_root, _session_root, _first, second, session_node_id, _acquisition_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    second_node_id = (
        "calibration:acquisition:"
        "camera-a/campaign-2026/2026-03-05__sess01/acquisitions/acq-0012__bright"
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )
    wait_until(
        lambda: not window._workflow_scope_refresh_timer.isActive(),
        timeout_ms=1000,
    )

    dock = window._metadata_inspector_dock
    assert dock.isHidden()
    sync_calls = 0
    dirty_calls = 0
    original_mark_dirty = dock.mark_dirty

    monkeypatch.setattr(
        dock,
        "sync_from_host",
        lambda: (_ for _ in ()).throw(AssertionError("hidden dock should not sync")),
    )

    def _wrapped_mark_dirty() -> None:
        nonlocal dirty_calls
        dirty_calls += 1
        original_mark_dirty()

    monkeypatch.setattr(dock, "mark_dirty", _wrapped_mark_dirty)

    explorer = window._workflow_explorer_dock
    explorer._tree.setCurrentItem(explorer._item_by_node_id[second_node_id])

    assert dirty_calls == 0
    assert sync_calls == 0
    wait_until(lambda: dirty_calls == 1, timeout_ms=1000)
    assert sync_calls == 0


def test_scaffolded_empty_calibration_root_enables_root_create_actions(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root = tmp_path / "empty-calibration"
    window = framelab_window_factory(enabled_plugin_ids=())
    window._scaffold_structured_workflow_root(workspace_root, "calibration")
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        anchor_type_id="root",
    )

    state = window._workflow_structure_action_state("calibration:root")

    assert window.workflow_state_controller.profile_id == "calibration"
    assert window.workflow_state_controller.root_node_id == "calibration:root"
    assert state["can_create_child"]
    assert state["create_child_type_id"] == "camera"
    assert state["create_action_text"] == "New Camera..."


def test_metadata_context_change_refreshes_only_affected_loaded_subtree(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
    wait_for_dataset_load,
) -> None:
    workspace_root, _session_root, first, second, session_node_id, _acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )
    window.load_folder()
    wait_for_dataset_load(window)

    original_by_path = {
        path: dict(window.dataset_state.metadata_for_path(path))
        for path in window.dataset_state.paths
    }
    refreshed_paths: list[str] = []

    def _fake_extract_path_metadata(
        path: str,
        metadata_source: str = "path",
        *,
        metadata_boundary_root=None,
    ) -> dict[str, object]:
        refreshed_paths.append(path)
        updated = dict(original_by_path[path])
        updated["refresh_marker"] = Path(path).parent.parent.name
        updated["metadata_source_selected"] = metadata_source
        updated["metadata_boundary_root"] = (
            str(metadata_boundary_root)
            if metadata_boundary_root is not None
            else None
        )
        return updated

    monkeypatch.setattr(
        data_page_module,
        "extract_path_metadata",
        _fake_extract_path_metadata,
    )

    window._notify_metadata_context_changed(changed_root=first)

    assert refreshed_paths == [window.dataset_state.paths[0]]
    assert window.dataset_state.metadata_for_path(window.dataset_state.paths[0])[
        "refresh_marker"
    ] == first.name
    assert "refresh_marker" not in window.dataset_state.metadata_for_path(
        window.dataset_state.paths[1],
    )


def test_workflow_context_reframes_folder_actions_as_scope_actions(
    tmp_path: Path,
    framelab_window_factory,
) -> None:
    workspace_root, session_root, _first, _second, session_node_id, _acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=(), show=True)

    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )

    assert window.file_open_folder_action.text() == "Browse Scope Folder..."
    assert window.file_scan_scope_action.text() == "Scan Selected Scope"
    assert window.toolbar_open_action.text() == "Browse Scope Folder..."
    assert window.toolbar_scan_action.text() == "Scan Selected Scope"
    assert window._data_scope_label.text() == "Scope"
    assert window._data_browse_button.text() == "Browse Scope..."
    assert window._data_load_button.text() == "Scan Selected Scope"
    assert window.folder_edit.text() == str(session_root.resolve())


def test_scope_scan_controls_invoke_load_folder_without_lambda_slots(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
) -> None:
    workspace_root, _session_root, _first, _second, session_node_id, _acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    load_calls: list[str] = []

    def _fake_load_folder(self, *args, **kwargs) -> None:
        load_calls.append(type(self).__name__)

    monkeypatch.setattr(window_module.FrameLabWindow, "load_folder", _fake_load_folder)
    window = framelab_window_factory(enabled_plugin_ids=(), show=True)
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )

    window.file_scan_scope_action.trigger()
    window.toolbar_scan_action.trigger()
    window._data_load_button.click()

    assert load_calls == [
        "FrameLabWindow",
        "FrameLabWindow",
        "FrameLabWindow",
    ]


def test_workflow_tab_changes_coalesce_visibility_refresh_until_settled(
    framelab_window_factory,
    monkeypatch,
    wait_until,
) -> None:
    window = framelab_window_factory(enabled_plugin_ids=())
    refresh_calls: list[int] = []

    monkeypatch.setattr(
        window,
        "_apply_dynamic_visibility_policy",
        lambda: refresh_calls.append(window.workflow_tabs.currentIndex()),
    )

    window.workflow_tabs.setCurrentIndex(1)
    window.workflow_tabs.setCurrentIndex(0)
    window.workflow_tabs.setCurrentIndex(1)

    assert refresh_calls == []
    wait_until(lambda: refresh_calls == [1], timeout_ms=1000)


def test_workflow_tab_changes_do_not_start_compute_or_invalidate(
    framelab_window_factory,
    monkeypatch,
    wait_until,
) -> None:
    window = framelab_window_factory(enabled_plugin_ids=())
    calls: list[str] = []

    monkeypatch.setattr(window, "load_folder", lambda *args, **kwargs: calls.append("load"))
    monkeypatch.setattr(
        window,
        "_start_dynamic_stats_job",
        lambda **kwargs: calls.append("dynamic"),
    )
    monkeypatch.setattr(window, "_clear_image_cache", lambda: calls.append("cache"))
    monkeypatch.setattr(
        window,
        "_invalidate_analysis_context",
        lambda **kwargs: calls.append("analysis"),
    )

    window.workflow_tabs.setCurrentIndex(1)

    wait_until(lambda: not window._workflow_tab_settle_timer.isActive(), timeout_ms=1000)
    assert calls == []


def test_same_workflow_scope_revisit_does_not_invalidate_analysis_context(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
    wait_until,
) -> None:
    workspace_root, _session_root, _first, _second, _session_node_id, acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=acq_node_id,
    )
    wait_until(lambda: not window._workflow_scope_refresh_timer.isActive(), timeout_ms=1000)

    invalidations: list[dict[str, object]] = []
    monkeypatch.setattr(
        window,
        "_invalidate_analysis_context",
        lambda **kwargs: invalidations.append(dict(kwargs)),
    )

    window.set_active_workflow_node(acq_node_id)

    wait_until(lambda: not window._workflow_scope_refresh_timer.isActive(), timeout_ms=1000)
    assert invalidations == []


def test_window_can_rename_acquisition_from_workflow_structure_tools(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
) -> None:
    workspace_root, _session_root, _first, second, _session_node_id, _acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    second_node_id = (
        "calibration:acquisition:"
        "camera-a/campaign-2026/2026-03-05__sess01/acquisitions/acq-0012__bright"
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=second_node_id,
    )
    monkeypatch.setattr(
        qtw.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("renamed", True),
    )

    window._rename_workflow_acquisition(second_node_id)

    renamed_root = second.with_name("acq-0012__renamed")
    renamed_node_id = (
        "calibration:acquisition:"
        "camera-a/campaign-2026/2026-03-05__sess01/acquisitions/acq-0012__renamed"
    )
    assert renamed_root.is_dir()
    assert not second.exists()
    assert window.workflow_state_controller.active_node_id == renamed_node_id
    assert window.folder_edit.text() == str(renamed_root.resolve())


def test_loaded_acquisition_rename_remaps_dataset_without_rescan(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
    wait_for_dataset_load,
) -> None:
    workspace_root, _session_root, _first, second, _session_node_id, _acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    second_node_id = (
        "calibration:acquisition:"
        "camera-a/campaign-2026/2026-03-05__sess01/acquisitions/acq-0012__bright"
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=second_node_id,
    )
    window.load_folder()
    wait_for_dataset_load(window)
    load_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        window,
        "load_folder",
        lambda *args, **kwargs: load_calls.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        qtw.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("renamed", True),
    )

    window._rename_workflow_acquisition(second_node_id)

    renamed_root = second.with_name("acq-0012__renamed")
    assert load_calls == []
    assert window.dataset_state.dataset_root == renamed_root.resolve()
    assert window.dataset_state.path_count() == 1
    assert Path(window.dataset_state.paths[0]).resolve().is_relative_to(
        renamed_root.resolve(),
    )
    assert window.folder_edit.text() == str(renamed_root.resolve())


def test_empty_acquisition_rename_does_not_scan_or_show_no_files(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
) -> None:
    workspace_root, second_node_id = _make_calibration_workspace(tmp_path)
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=second_node_id,
    )
    load_calls: list[dict[str, object]] = []
    info_messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        window,
        "load_folder",
        lambda *args, **kwargs: load_calls.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        window,
        "_show_info",
        lambda title, message: info_messages.append((str(title), str(message))),
    )
    monkeypatch.setattr(
        qtw.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("renamed", True),
    )

    window._rename_workflow_acquisition(second_node_id)

    assert load_calls == []
    assert not any("No supported image files" in message for _title, message in info_messages)


def test_window_can_rename_session_from_workflow_explorer_context_tools(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
) -> None:
    workspace_root, session_root, _first, _second, session_node_id, _acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )
    monkeypatch.setattr(
        qtw.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("2026-03-05__sess02", True),
    )

    window._rename_workflow_node(session_node_id)

    renamed_root = session_root.with_name("2026-03-05__sess02")
    renamed_node_id = (
        "calibration:session:"
        "camera-a/campaign-2026/2026-03-05__sess02"
    )
    assert renamed_root.is_dir()
    assert not session_root.exists()
    assert window.workflow_state_controller.active_node_id == renamed_node_id
    assert window.folder_edit.text() == str(renamed_root.resolve())


def test_window_can_delete_acquisition_from_workflow_structure_tools(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
    wait_for_dataset_load,
) -> None:
    workspace_root, session_root, _first, second, session_node_id, _acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    second_node_id = (
        "calibration:acquisition:"
        "camera-a/campaign-2026/2026-03-05__sess01/acquisitions/acq-0012__bright"
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=second_node_id,
    )
    window.load_folder()
    wait_for_dataset_load(window)
    monkeypatch.setattr(
        qtw.QMessageBox,
        "question",
        lambda *args, **kwargs: qtw.QMessageBox.Yes,
    )

    window._delete_workflow_acquisition(second_node_id)

    assert not second.exists()
    assert window.workflow_state_controller.active_node_id == session_node_id
    assert window.folder_edit.text() == str(session_root.resolve())
    assert not window.dataset_state.has_loaded_data()


def test_window_workflow_session_delete_defaults_confirmation_to_no(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
) -> None:
    workspace_root, session_root, _first, _second, session_node_id, _acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )
    captured: dict[str, object] = {}

    def _fake_question(*args, **kwargs):
        captured["default"] = args[4] if len(args) > 4 else kwargs.get("defaultButton")
        return qtw.QMessageBox.No

    monkeypatch.setattr(qtw.QMessageBox, "question", _fake_question)

    window._delete_workflow_session(session_node_id)

    assert captured["default"] == qtw.QMessageBox.No
    assert session_root.exists()
    assert window.workflow_state_controller.active_node_id == session_node_id


def test_window_can_create_and_delete_session_from_workflow_structure_tools(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
) -> None:
    workspace_root, session_root, _first, _second, _session_node_id, _acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    campaign_node_id = "calibration:campaign:camera-a/campaign-2026"
    created_node_id = "calibration:session:camera-a/campaign-2026/2026-03-06__sess02"
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=campaign_node_id,
    )
    load_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        window,
        "load_folder",
        lambda *args, **kwargs: load_calls.append(dict(kwargs)),
    )

    created_root = window._create_workflow_session(campaign_node_id, "2026-03-06__sess02")

    assert load_calls == []
    assert created_root == session_root.parent / "2026-03-06__sess02"
    assert created_root is not None and created_root.is_dir()
    assert window.workflow_state_controller.active_node_id == created_node_id
    assert window.folder_edit.text() == str(created_root.resolve())

    monkeypatch.setattr(
        qtw.QMessageBox,
        "question",
        lambda *args, **kwargs: qtw.QMessageBox.Yes,
    )

    window._delete_workflow_session(created_node_id)

    assert created_root is not None and not created_root.exists()
    assert window.workflow_state_controller.active_node_id == campaign_node_id


def test_window_can_reindex_session_from_workflow_structure_tools(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
) -> None:
    workspace_root, session_root, first, second, session_node_id, _acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )
    monkeypatch.setattr(
        qtw.QInputDialog,
        "getInt",
        lambda *args, **kwargs: (21, True),
    )
    monkeypatch.setattr(
        qtw.QMessageBox,
        "question",
        lambda *args, **kwargs: qtw.QMessageBox.Yes,
    )

    window._reindex_workflow_session(session_node_id)

    assert not first.exists()
    assert not second.exists()
    assert (session_root / "acquisitions" / "acq-0021__dark").is_dir()
    assert (session_root / "acquisitions" / "acq-0022__bright").is_dir()
    assert window.workflow_state_controller.active_node_id == session_node_id


def test_loaded_session_reindex_remaps_dataset_without_rescan(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
    wait_for_dataset_load,
) -> None:
    workspace_root, session_root, first, second, session_node_id, _acq_node_id = (
        _make_calibration_workspace_with_frames(tmp_path)
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.set_workflow_context(
        str(workspace_root),
        "calibration",
        active_node_id=session_node_id,
    )
    window.load_folder()
    wait_for_dataset_load(window)
    load_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        window,
        "load_folder",
        lambda *args, **kwargs: load_calls.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        qtw.QInputDialog,
        "getInt",
        lambda *args, **kwargs: (21, True),
    )
    monkeypatch.setattr(
        qtw.QMessageBox,
        "question",
        lambda *args, **kwargs: qtw.QMessageBox.Yes,
    )

    window._reindex_workflow_session(session_node_id)

    first_new = session_root / "acquisitions" / "acq-0021__dark" / "frames" / "f0.tiff"
    second_new = session_root / "acquisitions" / "acq-0022__bright" / "frames" / "f0.tiff"
    assert load_calls == []
    assert not first.exists()
    assert not second.exists()
    assert window.dataset_state.dataset_root == session_root.resolve()
    assert {Path(path).resolve() for path in window.dataset_state.paths} == {
        first_new.resolve(),
        second_new.resolve(),
    }

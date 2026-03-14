"""Pure UI-state helpers for the Session Manager dialog."""

from __future__ import annotations

from dataclasses import dataclass

from ...session_manager import AcquisitionEntry, SessionIndex


@dataclass(frozen=True, slots=True)
class SessionManagerActionState:
    """Enablement state for Session Manager actions."""

    load_selected_enabled: bool
    add_enabled: bool
    rename_enabled: bool
    delete_enabled: bool
    edit_datacard_enabled: bool
    copy_datacard_enabled: bool
    paste_datacard_enabled: bool
    toggle_ebus_enabled: bool
    reindex_enabled: bool
    toggle_ebus_text: str = "Toggle eBUS Snapshot"


def build_session_manager_action_state(
    session_index: SessionIndex | None,
    selected_entry: AcquisitionEntry | None,
    *,
    clipboard_ready: bool,
    has_ebus_tools: bool,
) -> SessionManagerActionState:
    """Return the current Session Manager action state from pure inputs."""
    has_session = session_index is not None
    numbering_valid = session_index.numbering_valid if session_index is not None else False
    has_entries = bool(session_index.entries) if session_index is not None else False
    has_entry = selected_entry is not None
    datacard_present = (
        bool(selected_entry.datacard_present)
        if selected_entry is not None
        else False
    )
    if selected_entry is None:
        toggle_ebus_text = "Toggle eBUS Snapshot"
    elif selected_entry.ebus_enabled:
        toggle_ebus_text = "Disable eBUS Snapshot"
    else:
        toggle_ebus_text = "Enable eBUS Snapshot"

    return SessionManagerActionState(
        load_selected_enabled=has_entry,
        add_enabled=has_session and numbering_valid,
        rename_enabled=has_entry,
        delete_enabled=has_entry and numbering_valid,
        edit_datacard_enabled=has_entry,
        copy_datacard_enabled=has_entry and datacard_present,
        paste_datacard_enabled=has_entry and bool(clipboard_ready),
        toggle_ebus_enabled=has_entry and has_ebus_tools,
        reindex_enabled=has_session and has_entries,
        toggle_ebus_text=toggle_ebus_text,
    )

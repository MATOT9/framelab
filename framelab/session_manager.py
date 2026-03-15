"""Session-level acquisition management helpers."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import shutil
import uuid
from typing import Any

from .acquisition_datacard import (
    format_acquisition_folder_name,
    parse_acquisition_folder_name,
    resolve_acquisition_datacard_path,
    resolve_session_datacard_path,
)
from .ebus import discover_ebus_snapshot_path, ebus_enabled_for_acquisition
from .frame_indexing import resolve_frame_index_map
from .payload_utils import read_json_dict, write_json_dict


@dataclass(frozen=True, slots=True)
class AcquisitionEntry:
    """One acquisition row discovered under a session."""

    number: int
    label: str | None
    width: int
    folder_name: str
    path: Path
    datacard_present: bool
    ebus_snapshot_present: bool
    ebus_enabled: bool
    frame_count: int | None


@dataclass(frozen=True, slots=True)
class SessionIndex:
    """Resolved acquisition list and numbering state for one session."""

    session_root: Path
    acquisitions_root: Path
    entries: tuple[AcquisitionEntry, ...]
    starting_number: int
    number_width: int
    numbering_valid: bool
    warning_text: str = ""


@dataclass(frozen=True, slots=True)
class SessionMutationResult:
    """Filesystem mutation summary returned by session operations."""

    created_path: Path | None = None
    created_paths: tuple[Path, ...] = ()
    deleted_paths: tuple[Path, ...] = ()
    renamed_paths: tuple[tuple[Path, Path], ...] = ()


@dataclass(frozen=True, slots=True)
class AcquisitionCreationPreviewEntry:
    """One proposed acquisition folder before filesystem mutation."""

    number: int
    label: str | None
    width: int
    folder_name: str
    path: Path
    collision_exists: bool


@dataclass(frozen=True, slots=True)
class AcquisitionDatacardClipboard:
    """In-memory copied acquisition datacard payload."""

    payload: dict[str, Any]
    source_folder_name: str


_EBUS_ATTACHMENT_KEYS = (
    "attached_file",
    "source_hash_sha256",
    "source_mtime_ns",
    "source_size_bytes",
    "parse_version",
    "attached_at_local",
)
_SESSION_CONTAINER_NAMES = ("01_sessions", "sessions")


def resolve_acquisitions_root(session_root: str | Path) -> Path:
    """Return the acquisitions root for one session."""
    root = Path(session_root)
    payload = read_json_dict(resolve_session_datacard_path(root))
    if isinstance(payload, dict):
        paths_block = payload.get("paths")
        if isinstance(paths_block, dict):
            raw_rel = paths_block.get("acquisitions_root_rel")
            if isinstance(raw_rel, str) and raw_rel.strip():
                return root.joinpath(raw_rel).resolve()
    return root.joinpath("acquisitions")


def resolve_campaign_sessions_root(campaign_root: str | Path) -> Path:
    """Return the preferred directory used to hold session folders for one campaign."""

    root = Path(campaign_root).resolve()
    if root.name.lower() in _SESSION_CONTAINER_NAMES:
        return root
    for child_name in _SESSION_CONTAINER_NAMES:
        candidate = root.joinpath(child_name)
        if candidate.is_dir():
            return candidate.resolve()
    return root


def _default_session_payload(folder_name: str) -> dict[str, Any]:
    """Return a stable default session datacard payload."""

    return {
        "schema_version": "1.0",
        "entity": "session",
        "identity": {
            "label": folder_name,
        },
        "paths": {
            "session_root_rel": None,
            "acquisitions_root_rel": "acquisitions",
            "notes_rel": None,
        },
        "session_defaults": {},
        "notes": "",
    }


def _frame_count_for_acquisition(acquisition_root: Path) -> int | None:
    """Return discovered frame count for one acquisition folder."""
    payload = read_json_dict(resolve_acquisition_datacard_path(acquisition_root))
    frames_dir_name = "frames"
    if isinstance(payload, dict):
        paths_block = payload.get("paths")
        if isinstance(paths_block, dict):
            raw_frames_dir = paths_block.get("frames_dir")
            if isinstance(raw_frames_dir, str) and raw_frames_dir.strip():
                frames_dir_name = raw_frames_dir
    resolution = resolve_frame_index_map(acquisition_root.joinpath(frames_dir_name))
    if resolution.mode == "none":
        return None
    return len(resolution.indices)


def inspect_session(session_root: str | Path) -> SessionIndex:
    """Inspect one session and return acquisition numbering state."""
    root = Path(session_root).resolve()
    acquisitions_root = resolve_acquisitions_root(root)
    entries: list[AcquisitionEntry] = []
    if acquisitions_root.is_dir():
        for child in sorted(acquisitions_root.iterdir(), key=lambda item: item.name.lower()):
            if not child.is_dir():
                continue
            parsed = parse_acquisition_folder_name(child.name)
            if parsed is None:
                continue
            number, label, width = parsed
            datacard_present = resolve_acquisition_datacard_path(child).is_file()
            entries.append(
                AcquisitionEntry(
                    number=number,
                    label=label,
                    width=width,
                    folder_name=child.name,
                    path=child,
                    datacard_present=datacard_present,
                    ebus_snapshot_present=discover_ebus_snapshot_path(child) is not None,
                    ebus_enabled=ebus_enabled_for_acquisition(child),
                    frame_count=_frame_count_for_acquisition(child),
                ),
            )
    entries.sort(key=lambda item: (item.number, item.folder_name.lower()))
    if entries:
        starting_number = entries[0].number
        number_width = max(max(entry.width for entry in entries), 4)
        expected = list(range(starting_number, starting_number + len(entries)))
        actual = [entry.number for entry in entries]
        numbering_valid = actual == expected
        warning_text = ""
        if not numbering_valid:
            warning_text = (
                "Acquisition numbering is not contiguous. "
                "Use Normalize/Reindex before structural edits."
            )
    else:
        starting_number = 1
        number_width = 4
        numbering_valid = True
        warning_text = ""
    return SessionIndex(
        session_root=root,
        acquisitions_root=acquisitions_root,
        entries=tuple(entries),
        starting_number=starting_number,
        number_width=number_width,
        numbering_valid=numbering_valid,
        warning_text=warning_text,
    )


def create_session(
    campaign_root: str | Path,
    folder_label: str,
) -> SessionMutationResult:
    """Create one new session folder under the preferred campaign session root."""

    clean_label = str(folder_label).strip()
    if not clean_label:
        raise ValueError("Session folder label cannot be empty.")
    if clean_label in {".", ".."} or "/" in clean_label or "\\" in clean_label:
        raise ValueError("Session folder label cannot contain path separators.")

    sessions_root = resolve_campaign_sessions_root(campaign_root)
    session_root = sessions_root.joinpath(clean_label)
    if session_root.exists():
        raise FileExistsError(
            f"Session folder already exists: {session_root.name}",
        )

    session_root.mkdir(parents=True, exist_ok=False)
    write_json_dict(
        resolve_session_datacard_path(session_root),
        _default_session_payload(session_root.name),
    )
    resolve_acquisitions_root(session_root).mkdir(parents=True, exist_ok=True)
    return SessionMutationResult(
        created_path=session_root,
        created_paths=(session_root,),
    )


def delete_session(session_root: str | Path) -> SessionMutationResult:
    """Delete one session folder from disk."""

    root = Path(session_root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"session folder does not exist: {root}")
    shutil.rmtree(root)
    return SessionMutationResult(
        deleted_paths=(root,),
    )


def _default_acquisition_payload(
    folder_name: str,
    label: str | None,
) -> dict[str, Any]:
    """Return a stable default acquisition datacard payload."""
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


def _replace_folder_name_in_payload(value: Any, old_name: str, new_name: str) -> Any:
    """Replace acquisition-folder references inside nested payload strings."""
    if isinstance(value, dict):
        return {
            key: _replace_folder_name_in_payload(item, old_name, new_name)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _replace_folder_name_in_payload(item, old_name, new_name)
            for item in value
        ]
    if isinstance(value, str) and old_name and old_name in value:
        return value.replace(old_name, new_name)
    return deepcopy(value)


def _normalize_acquisition_payload(
    payload: Any,
    *,
    target_folder_name: str,
    target_label: str | None,
    source_folder_name: str | None = None,
    strip_ebus_attachment: bool = False,
) -> dict[str, Any]:
    """Normalize an acquisition datacard payload for one destination folder."""
    normalized = (
        deepcopy(payload)
        if isinstance(payload, dict)
        else _default_acquisition_payload(target_folder_name, target_label)
    )
    normalized["schema_version"] = str(normalized.get("schema_version", "1.0"))
    normalized["entity"] = "acquisition"

    identity = normalized.get("identity")
    if not isinstance(identity, dict):
        identity = {}
    identity["acquisition_id"] = target_folder_name
    identity["label"] = target_label
    normalized["identity"] = identity

    paths = normalized.get("paths")
    if not isinstance(paths, dict):
        paths = {}
    if source_folder_name:
        paths = _replace_folder_name_in_payload(
            paths,
            source_folder_name,
            target_folder_name,
        )
    frames_dir = paths.get("frames_dir")
    if not isinstance(frames_dir, str) or not frames_dir.strip():
        paths["frames_dir"] = "frames"
    normalized["paths"] = paths

    if not isinstance(normalized.get("intent"), dict):
        normalized["intent"] = {
            "capture_type": "calibration",
            "subtype": "",
            "scene": "",
            "tags": [],
        }
    if not isinstance(normalized.get("defaults"), dict):
        normalized["defaults"] = {}
    if not isinstance(normalized.get("overrides"), list):
        normalized["overrides"] = []
    if not isinstance(normalized.get("quality"), dict):
        normalized["quality"] = {
            "anomalies": [],
            "dropped_frames": [],
            "saturation_expected": False,
        }

    external_sources = normalized.get("external_sources")
    if not isinstance(external_sources, dict):
        external_sources = {}
    ebus_block = external_sources.get("ebus")
    if isinstance(ebus_block, dict) and strip_ebus_attachment:
        ebus_block = deepcopy(ebus_block)
        for key in _EBUS_ATTACHMENT_KEYS:
            ebus_block.pop(key, None)
        external_sources["ebus"] = ebus_block
    normalized["external_sources"] = external_sources
    return normalized


def _write_normalized_datacard(
    acquisition_root: Path,
    payload: Any,
    *,
    source_folder_name: str | None = None,
    strip_ebus_attachment: bool = False,
) -> None:
    """Normalize and write one acquisition datacard."""
    parsed = parse_acquisition_folder_name(acquisition_root.name)
    label = parsed[1] if parsed is not None else None
    normalized = _normalize_acquisition_payload(
        payload,
        target_folder_name=acquisition_root.name,
        target_label=label,
        source_folder_name=source_folder_name,
        strip_ebus_attachment=strip_ebus_attachment,
    )
    write_json_dict(resolve_acquisition_datacard_path(acquisition_root), normalized)


def _apply_rename_plan(
    rename_plan: list[tuple[Path, Path]],
) -> tuple[tuple[Path, Path], ...]:
    """Apply a multi-folder rename plan through temporary names."""
    if not rename_plan:
        return ()
    staged: list[tuple[Path, Path, Path]] = []
    for old_path, new_path in rename_plan:
        if old_path == new_path:
            continue
        temp_path = old_path.with_name(
            f".__tv_tmp_{uuid.uuid4().hex}__{old_path.name}",
        )
        old_path.rename(temp_path)
        staged.append((temp_path, old_path, new_path))
    applied: list[tuple[Path, Path]] = []
    for temp_path, old_path, new_path in staged:
        temp_path.rename(new_path)
        if resolve_acquisition_datacard_path(new_path).is_file():
            _write_normalized_datacard(
                new_path,
                read_json_dict(resolve_acquisition_datacard_path(new_path)),
                source_folder_name=old_path.name,
                strip_ebus_attachment=False,
            )
        applied.append((old_path, new_path))
    return tuple(applied)


def add_acquisition(
    session_root: str | Path,
    *,
    label: str | None = None,
    starting_number: int | None = None,
) -> SessionMutationResult:
    """Create a new acquisition folder at the end of the session list."""
    index = inspect_session(session_root)
    if index.entries and starting_number is not None and int(starting_number) != index.starting_number:
        raise ValueError("Change the starting number through reindexing first.")
    return create_acquisition_batch(
        session_root,
        count=1,
        starting_number=None if index.entries else starting_number,
        labels=((str(label).strip() or None) if label is not None else None,),
    )


def preview_acquisition_batch(
    session_root: str | Path,
    *,
    count: int = 1,
    starting_number: int | None = None,
    labels: tuple[str | None, ...] = (),
) -> tuple[AcquisitionCreationPreviewEntry, ...]:
    """Return a preview of proposed acquisition folders for one session."""

    index = inspect_session(session_root)
    requested_count = max(1, int(count))
    width = index.number_width
    if starting_number is None:
        base_number = index.entries[-1].number + 1 if index.entries else index.starting_number
    else:
        base_number = int(starting_number)

    previews: list[AcquisitionCreationPreviewEntry] = []
    for offset in range(requested_count):
        label = None
        if offset < len(labels):
            clean = str(labels[offset]).strip() if labels[offset] is not None else ""
            label = clean or None
        number = base_number + offset
        folder_name = format_acquisition_folder_name(number, label, width=width)
        path = index.acquisitions_root.joinpath(folder_name)
        previews.append(
            AcquisitionCreationPreviewEntry(
                number=number,
                label=label,
                width=width,
                folder_name=folder_name,
                path=path,
                collision_exists=path.exists(),
            ),
        )
    return tuple(previews)


def create_acquisition_batch(
    session_root: str | Path,
    *,
    count: int = 1,
    starting_number: int | None = None,
    labels: tuple[str | None, ...] = (),
) -> SessionMutationResult:
    """Create one or more acquisition folders from an explicit preview plan."""

    index = inspect_session(session_root)
    if not index.numbering_valid:
        raise ValueError(index.warning_text or "Session numbering is not contiguous.")
    previews = preview_acquisition_batch(
        session_root,
        count=count,
        starting_number=starting_number,
        labels=labels,
    )
    collisions = [entry.folder_name for entry in previews if entry.collision_exists]
    if collisions:
        joined = ", ".join(collisions[:3])
        suffix = f" (+{len(collisions) - 3} more)" if len(collisions) > 3 else ""
        raise FileExistsError(f"Acquisition folder already exists: {joined}{suffix}")

    created_paths: list[Path] = []
    for preview in previews:
        preview.path.mkdir(parents=True, exist_ok=False)
        for child_name in ("frames", "notes", "thumbs"):
            preview.path.joinpath(child_name).mkdir(parents=True, exist_ok=True)
        created_paths.append(preview.path)
    return SessionMutationResult(
        created_path=created_paths[0] if created_paths else None,
        created_paths=tuple(created_paths),
    )


def rename_acquisition_label(
    acquisition_root: str | Path,
    label: str | None,
) -> SessionMutationResult:
    """Rename one acquisition folder label while preserving its number."""
    current_root = Path(acquisition_root).resolve()
    parsed = parse_acquisition_folder_name(current_root.name)
    if parsed is None:
        raise ValueError("Selected folder is not a valid acquisition folder.")
    number, _old_label, width = parsed
    new_name = format_acquisition_folder_name(number, label, width=width)
    new_root = current_root.with_name(new_name)
    if new_root != current_root:
        current_root.rename(new_root)
    if resolve_acquisition_datacard_path(new_root).is_file():
        _write_normalized_datacard(
            new_root,
            read_json_dict(resolve_acquisition_datacard_path(new_root)),
            source_folder_name=current_root.name,
            strip_ebus_attachment=False,
        )
    return SessionMutationResult(
        renamed_paths=((current_root, new_root),) if new_root != current_root else (),
    )


def reindex_acquisitions(
    session_root: str | Path,
    *,
    starting_number: int,
) -> SessionMutationResult:
    """Renumber acquisition folders contiguously from the requested base."""
    index = inspect_session(session_root)
    if not index.entries:
        return SessionMutationResult()
    rename_plan: list[tuple[Path, Path]] = []
    for offset, entry in enumerate(index.entries):
        new_number = int(starting_number) + offset
        new_name = format_acquisition_folder_name(
            new_number,
            entry.label,
            width=index.number_width,
        )
        new_path = entry.path.with_name(new_name)
        if new_path != entry.path:
            rename_plan.append((entry.path, new_path))
    return SessionMutationResult(
        renamed_paths=_apply_rename_plan(rename_plan),
    )


def delete_acquisition(
    session_root: str | Path,
    acquisition_root: str | Path,
) -> SessionMutationResult:
    """Delete one acquisition and close numbering gaps after it."""
    index = inspect_session(session_root)
    if not index.numbering_valid:
        raise ValueError(index.warning_text or "Session numbering is not contiguous.")
    target = Path(acquisition_root).resolve()
    target_entry = next((entry for entry in index.entries if entry.path == target), None)
    if target_entry is None:
        raise ValueError("Selected acquisition does not belong to the session.")
    shutil.rmtree(target)
    remaining = [entry for entry in index.entries if entry.path != target]
    rename_plan: list[tuple[Path, Path]] = []
    for offset, entry in enumerate(remaining):
        expected_number = index.starting_number + offset
        new_name = format_acquisition_folder_name(
            expected_number,
            entry.label,
            width=index.number_width,
        )
        new_path = entry.path.with_name(new_name)
        if new_path != entry.path:
            rename_plan.append((entry.path, new_path))
    return SessionMutationResult(
        deleted_paths=(target,),
        renamed_paths=_apply_rename_plan(rename_plan),
    )


def copy_acquisition_datacard(
    acquisition_root: str | Path,
) -> AcquisitionDatacardClipboard | None:
    """Copy one acquisition datacard payload into an in-memory clipboard."""
    root = Path(acquisition_root).resolve()
    payload = read_json_dict(resolve_acquisition_datacard_path(root))
    if payload is None:
        return None
    return AcquisitionDatacardClipboard(
        payload=deepcopy(payload),
        source_folder_name=root.name,
    )


def paste_acquisition_datacard(
    acquisition_root: str | Path,
    clipboard: AcquisitionDatacardClipboard,
) -> Path:
    """Paste a copied acquisition datacard onto a destination acquisition."""
    root = Path(acquisition_root).resolve()
    _write_normalized_datacard(
        root,
        clipboard.payload,
        source_folder_name=clipboard.source_folder_name,
        strip_ebus_attachment=True,
    )
    return resolve_acquisition_datacard_path(root)


def set_acquisition_ebus_enabled(
    acquisition_root: str | Path,
    enabled: bool,
) -> Path:
    """Persist acquisition-local eBUS enabled state."""
    root = Path(acquisition_root).resolve()
    payload = read_json_dict(resolve_acquisition_datacard_path(root))
    if payload is None:
        parsed = parse_acquisition_folder_name(root.name)
        payload = _default_acquisition_payload(
            root.name,
            parsed[1] if parsed is not None else None,
        )
    external_sources = payload.get("external_sources")
    if not isinstance(external_sources, dict):
        external_sources = {}
    ebus_block = external_sources.get("ebus")
    if not isinstance(ebus_block, dict):
        ebus_block = {}
    ebus_block["enabled"] = bool(enabled)
    external_sources["ebus"] = ebus_block
    payload["external_sources"] = external_sources
    _write_normalized_datacard(
        root,
        payload,
        source_folder_name=root.name,
        strip_ebus_attachment=False,
    )
    return resolve_acquisition_datacard_path(root)

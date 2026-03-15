"""Generic workflow-node metadata storage above acquisition datacards."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .payload_utils import read_json_dict, write_json_dict


NODECARD_DIR_NAME = ".framelab"
NODECARD_FILE_NAME = "nodecard.json"


@dataclass(slots=True)
class NodeMetadataCard:
    """Generic node-local metadata payload stored beside workflow folders."""

    schema_version: str = "1.0"
    entity: str = "workflow_node"
    profile_id: str | None = None
    node_type_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None
    source_exists: bool = False
    extra_top_level: dict[str, Any] = field(default_factory=dict)


def resolve_nodecard_path(path: str | Path) -> Path:
    """Return the canonical nodecard path for one folder or explicit file."""

    raw_path = Path(path)
    if raw_path.name.lower() == NODECARD_FILE_NAME and raw_path.parent.name == NODECARD_DIR_NAME:
        return raw_path
    if raw_path.is_dir():
        return raw_path / NODECARD_DIR_NAME / NODECARD_FILE_NAME
    return raw_path.parent / NODECARD_DIR_NAME / NODECARD_FILE_NAME


def path_has_nodecard(path: str | Path) -> bool:
    """Return whether the path or any ancestor carries a nodecard file."""

    candidate = Path(path)
    search_root = candidate if candidate.is_dir() else candidate.parent
    for current in (search_root, *search_root.parents):
        if resolve_nodecard_path(current).is_file():
            return True
    return False


def discover_nodecard_roots(
    path: str | Path,
    *,
    exclude_paths: tuple[str | Path, ...] = (),
) -> tuple[Path, ...]:
    """Return ancestor directories carrying nodecards from root to leaf."""

    candidate = Path(path)
    search_root = candidate if candidate.is_dir() else candidate.parent
    excluded = {Path(item).resolve() for item in exclude_paths}
    discovered: list[Path] = []
    for current in (search_root, *search_root.parents):
        resolved = current.resolve()
        if resolved in excluded:
            continue
        if resolve_nodecard_path(resolved).is_file():
            discovered.append(resolved)
    discovered.reverse()
    return tuple(discovered)


def load_nodecard(path: str | Path) -> NodeMetadataCard:
    """Load one nodecard payload or return a stable empty model."""

    nodecard_path = resolve_nodecard_path(path)
    payload = read_json_dict(nodecard_path)
    model = NodeMetadataCard(
        source_path=nodecard_path,
        source_exists=bool(payload is not None and nodecard_path.is_file()),
    )
    if payload is None:
        return model

    known = {
        "schema_version",
        "entity",
        "profile_id",
        "node_type_id",
        "metadata",
    }
    model.schema_version = str(payload.get("schema_version", "1.0"))
    model.entity = str(payload.get("entity", "workflow_node"))
    raw_profile_id = payload.get("profile_id")
    model.profile_id = (
        str(raw_profile_id).strip() if isinstance(raw_profile_id, str) and raw_profile_id.strip() else None
    )
    raw_node_type = payload.get("node_type_id")
    model.node_type_id = (
        str(raw_node_type).strip() if isinstance(raw_node_type, str) and raw_node_type.strip() else None
    )
    raw_metadata = payload.get("metadata")
    model.metadata = deepcopy(raw_metadata) if isinstance(raw_metadata, dict) else {}
    model.extra_top_level = {
        key: deepcopy(value)
        for key, value in payload.items()
        if key not in known
    }
    return model


def save_nodecard(
    path: str | Path,
    metadata: dict[str, Any],
    *,
    profile_id: str | None = None,
    node_type_id: str | None = None,
    extra_top_level: dict[str, Any] | None = None,
) -> Path:
    """Write one nodecard payload for a workflow folder."""

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "entity": "workflow_node",
        "profile_id": str(profile_id).strip() if profile_id else None,
        "node_type_id": str(node_type_id).strip() if node_type_id else None,
        "metadata": deepcopy(metadata) if isinstance(metadata, dict) else {},
    }
    if isinstance(extra_top_level, dict):
        for key, value in extra_top_level.items():
            if str(key).strip() in payload:
                continue
            payload[str(key)] = deepcopy(value)
    nodecard_path = resolve_nodecard_path(path)
    write_json_dict(nodecard_path, payload)
    return nodecard_path

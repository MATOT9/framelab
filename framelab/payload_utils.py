"""Helpers for JSON-backed payloads and dot-path access.

These helpers intentionally stay small and generic so metadata extraction,
datacard services, and UI code can share the same low-level behavior without
pulling business logic into a common module.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json_dict(path: Path) -> dict[str, Any] | None:
    """Read a JSON file and return a dictionary payload.

    Parameters
    ----------
    path : Path
        JSON file path to load.

    Returns
    -------
    dict[str, Any] | None
        Parsed dictionary payload, or ``None`` when the file is missing,
        invalid, or does not contain a top-level JSON object.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def write_json_dict(path: Path, payload: dict[str, Any]) -> None:
    """Write a dictionary payload as pretty-printed JSON.

    Parameters
    ----------
    path : Path
        Output JSON file path.
    payload : dict[str, Any]
        Dictionary payload to serialize.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def get_dot_path(source: Any, dot_path: str) -> Any:
    """Return a nested value from a dictionary-like payload.

    Parameters
    ----------
    source : Any
        Root payload object.
    dot_path : str
        Dot-separated key path.

    Returns
    -------
    Any
        Nested value when present, otherwise ``None``.
    """
    current = source
    for part in dot_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def set_dot_path(target: dict[str, Any], dot_path: str, value: Any) -> None:
    """Set a nested dictionary value using a dot-separated key path.

    Parameters
    ----------
    target : dict[str, Any]
        Dictionary payload to mutate.
    dot_path : str
        Dot-separated key path.
    value : Any
        Value to write at the target path.
    """
    current = target
    parts = dot_path.split(".")
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


def delete_dot_path(target: dict[str, Any], dot_path: str) -> None:
    """Delete a nested dictionary key and prune empty parent dictionaries.

    Parameters
    ----------
    target : dict[str, Any]
        Dictionary payload to mutate.
    dot_path : str
        Dot-separated key path.
    """
    current = target
    parents: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
    parts = dot_path.split(".")
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            return
        parents.append((current, part, child))
        current = child
    current.pop(parts[-1], None)
    for parent, part, child in reversed(parents):
        if child:
            break
        parent.pop(part, None)


def flatten_payload_dict(
    source: dict[str, Any],
    prefix: str = "",
) -> dict[str, Any]:
    """Flatten nested dictionaries into a dot-path dictionary.

    Parameters
    ----------
    source : dict[str, Any]
        Nested dictionary payload to flatten.
    prefix : str, default=""
        Optional leading key prefix.

    Returns
    -------
    dict[str, Any]
        Flattened dot-path payload.
    """
    out: dict[str, Any] = {}
    for key, value in source.items():
        if not isinstance(key, str):
            continue
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(flatten_payload_dict(value, full_key))
        else:
            out[full_key] = value
    return out


def unflatten_payload_dict(
    changes: dict[str, Any],
) -> dict[str, Any]:
    """Build a nested dictionary from dot-path keys.

    Parameters
    ----------
    changes : dict[str, Any]
        Flat dot-path payload.

    Returns
    -------
    dict[str, Any]
        Nested dictionary payload.
    """
    out: dict[str, Any] = {}
    for key, value in changes.items():
        if not isinstance(key, str) or not key.strip():
            continue
        if "." not in key:
            out[key] = value
            continue
        set_dot_path(out, key, value)
    return out

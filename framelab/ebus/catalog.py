"""Catalog loading for eBUS parameter classification."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..datacard_authoring import load_field_mapping
from .models import EbusCatalogEntry
from ..payload_utils import read_json_dict, write_json_dict
from ..scan_settings import app_config_path


DEFAULT_CATALOG_FILE = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "ebus_parameter_catalog.default.json"
)


def ebus_catalog_config_path() -> Path:
    """Return the editable eBUS parameter catalog path."""
    return app_config_path(
        "ebus_parameter_catalog.json",
        legacy_names=("ebus_parameter_catalog.json",),
    )


def _normalize_bool(value: Any, default: bool) -> bool:
    """Convert loose boolean-like values to bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"1", "true", "yes", "on"}:
            return True
        if token in {"0", "false", "no", "off"}:
            return False
    return default


def _parse_entry(item: dict[str, Any]) -> EbusCatalogEntry | None:
    """Parse one eBUS catalog entry."""
    qualified_key = str(item.get("qualified_key", "")).strip()
    section = str(item.get("section", "")).strip()
    label = str(item.get("label", "")).strip()
    if not qualified_key or not section or not label:
        return None
    relevance = str(item.get("relevance", "operational")).strip().lower()
    if relevance not in {"scientific", "operational", "ui_noise"}:
        relevance = "operational"
    return EbusCatalogEntry(
        qualified_key=qualified_key,
        section=section,
        label=label,
        description=str(item.get("description", "")).strip(),
        unit=str(item.get("unit", "")).strip(),
        relevance=relevance,
        show_in_compare=_normalize_bool(item.get("show_in_compare"), True),
        show_in_summary=_normalize_bool(item.get("show_in_summary"), False),
        overridable=_normalize_bool(item.get("overridable"), False),
        editable_in_ebus=_normalize_bool(item.get("editable_in_ebus"), True),
        value_type_hint=str(item.get("value_type_hint", "")).strip(),
    )


def _entries_from_payload(payload: dict[str, Any]) -> tuple[EbusCatalogEntry, ...]:
    """Parse all valid catalog entries from a JSON payload."""
    raw = payload.get("fields")
    if not isinstance(raw, list):
        return ()
    entries: list[EbusCatalogEntry] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        entry = _parse_entry(item)
        if entry is None or entry.qualified_key in seen:
            continue
        seen.add(entry.qualified_key)
        entries.append(entry)
    return tuple(entries)


def _write_default_catalog(target_path: Path) -> None:
    """Create editable catalog from bundled default when missing."""
    if target_path.exists() or not DEFAULT_CATALOG_FILE.exists():
        return
    payload = read_json_dict(DEFAULT_CATALOG_FILE)
    if payload is None:
        return
    write_json_dict(target_path, payload)


def load_ebus_catalog() -> tuple[EbusCatalogEntry, ...]:
    """Load the editable eBUS parameter catalog with bundled fallback."""
    user_path = ebus_catalog_config_path()
    _write_default_catalog(user_path)
    payload = read_json_dict(user_path)
    entries = _entries_from_payload(payload or {})
    if entries:
        return entries
    default_payload = read_json_dict(DEFAULT_CATALOG_FILE)
    return _entries_from_payload(default_payload or {})


def ebus_catalog_index() -> dict[str, EbusCatalogEntry]:
    """Return the eBUS catalog indexed by qualified key."""
    return {
        entry.qualified_key: entry
        for entry in load_ebus_catalog()
    }


def ebus_to_canonical_index() -> dict[str, str]:
    """Return eBUS-key to canonical-field mappings from the acquisition mapping."""
    return {
        field.ebus_label: field.key
        for field in load_field_mapping().fields
        if field.ebus_label
    }


def mapped_datacard_key_for_ebus(qualified_key: str) -> str:
    """Return canonical field key mapped from one eBUS qualified key."""
    return ebus_to_canonical_index().get(str(qualified_key).strip(), "")

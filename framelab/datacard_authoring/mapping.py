"""Field mapping loader for datacard authoring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import FieldMapping, FieldSpec
from ..payload_utils import read_json_dict, write_json_dict
from ..scan_settings import app_config_path


DEFAULT_MAPPING_FILE = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "acquisition_field_mapping.default.json"
)


def mapping_config_path() -> Path:
    """Return user-editable mapping file path."""
    return app_config_path(
        "acquisition_field_mapping.json",
        legacy_names=("acquisition_field_mapping.json",),
    )


def _default_fields() -> tuple[FieldSpec, ...]:
    """Return built-in fallback mapping fields."""
    payload = read_json_dict(DEFAULT_MAPPING_FILE)
    if payload is None:
        return ()
    return _fields_from_payload(payload)


def _coerce_float(value: Any) -> float | None:
    """Convert numeric-like value to float or None."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except Exception:
        return None
    return number


def _coerce_optional_bound(item: dict[str, Any], key: str) -> float | None:
    """Return optional numeric bound from mapping entry.

    Missing keys, ``null`` values, and blank strings are all treated as
    "no bound".
    """
    if key not in item:
        return None
    value = item.get(key)
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return _coerce_float(value)


def _parse_field(item: dict[str, Any]) -> FieldSpec | None:
    """Parse one mapping JSON field definition."""
    key = str(item.get("key", "")).strip()
    label = str(item.get("label", "")).strip()
    group = str(item.get("group", "General")).strip() or "General"
    value_type = str(item.get("type", "")).strip().lower()
    if not key or not label or value_type not in {
        "int",
        "float",
        "bool",
        "enum",
        "string",
    }:
        return None

    options_raw = item.get("options")
    options: tuple[str, ...]
    if isinstance(options_raw, list):
        cleaned = [
            str(value).strip()
            for value in options_raw
            if str(value).strip()
        ]
        options = tuple(cleaned)
    else:
        options = ()
    if value_type == "enum" and not options:
        return None

    return FieldSpec(
        key=key,
        label=label,
        group=group,
        value_type=value_type,
        tooltip=str(item.get("tooltip", "")).strip(),
        ebus_label=str(item.get("ebus_label", "")).strip(),
        ebus_managed=bool(item.get("ebus_managed", False)),
        unit=str(item.get("unit", "")).strip(),
        minimum=_coerce_optional_bound(item, "min"),
        maximum=_coerce_optional_bound(item, "max"),
        step=_coerce_float(item.get("step")),
        options=options,
        show_in_defaults=bool(item.get("show_in_defaults", True)),
        show_in_overrides=bool(item.get("show_in_overrides", True)),
    )


def _fields_from_payload(payload: dict[str, Any]) -> tuple[FieldSpec, ...]:
    """Parse field specs from mapping payload."""
    raw = payload.get("fields")
    if not isinstance(raw, list):
        return ()

    fields: list[FieldSpec] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        parsed = _parse_field(entry)
        if parsed is None or parsed.key in seen:
            continue
        seen.add(parsed.key)
        fields.append(parsed)
    return tuple(fields)


def _ensure_mapping_metadata_fields(path: Path) -> None:
    """Seed missing built-in metadata keys in editable mapping JSON."""
    payload = read_json_dict(path)
    default_payload = read_json_dict(DEFAULT_MAPPING_FILE)
    if payload is None or default_payload is None:
        return

    raw_fields = payload.get("fields")
    default_fields = default_payload.get("fields")
    if not isinstance(raw_fields, list) or not isinstance(default_fields, list):
        return

    defaults_by_key: dict[str, dict[str, Any]] = {}
    for entry in default_fields:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key", "")).strip()
        if not key:
            continue
        defaults_by_key[key] = entry

    changed = False
    for entry in raw_fields:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key", "")).strip()
        if not key:
            continue
        default_entry = defaults_by_key.get(key, {})
        for field_name in ("tooltip", "ebus_label", "ebus_managed"):
            if field_name in entry:
                continue
            if field_name == "ebus_managed":
                entry[field_name] = bool(default_entry.get(field_name, False))
            else:
                entry[field_name] = str(default_entry.get(field_name, "")).strip()
            changed = True

    if changed:
        write_json_dict(path, payload)


def _write_default_mapping(target_path: Path) -> None:
    """Create user mapping file from bundled default when missing."""
    if target_path.exists():
        return
    if not DEFAULT_MAPPING_FILE.exists():
        return
    payload = read_json_dict(DEFAULT_MAPPING_FILE)
    if payload is None:
        return
    write_json_dict(target_path, payload)


def load_field_mapping() -> FieldMapping:
    """Load mapping from user config path with fallback defaults."""
    warnings: list[str] = []
    user_path = mapping_config_path()
    _write_default_mapping(user_path)
    _ensure_mapping_metadata_fields(user_path)

    payload = read_json_dict(user_path)
    fields = _fields_from_payload(payload or {})
    if not fields:
        if payload is None:
            warnings.append(
                f"Could not load mapping file: {user_path}. Using built-in defaults.",
            )
        else:
            warnings.append(
                f"Mapping file has no valid fields: {user_path}. Using built-in defaults.",
            )
        fields = _default_fields()

    return FieldMapping(path=user_path, fields=fields, warnings=tuple(warnings))

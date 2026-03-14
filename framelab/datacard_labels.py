"""Label helpers for datacard keys and derived metadata fields."""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from .datacard_authoring.mapping import load_field_mapping


METADATA_FIELD_LABELS: dict[str, str] = {
    "path": "Image Path",
    "parent_folder": "Parent",
    "grandparent_folder": "Grandparent",
    "iris_position": "Iris Position",
    "exposure_ms": "Exposure [ms]",
    "exposure_source": "Exposure Source",
    "group_index": "Group #",
}


def _prettify_identifier(token: str) -> str:
    """Return readable text from underscore/dot identifiers.

    Parameters
    ----------
    token : str
        Raw identifier token.

    Returns
    -------
    str
        Human-readable label.
    """
    clean = token.strip().replace(".", " ").replace("_", " ")
    parts = [part for part in clean.split() if part]
    if not parts:
        return token
    return " ".join(parts).capitalize()


@lru_cache(maxsize=1)
def _camera_setting_labels() -> dict[str, str]:
    """Load camera-setting labels from the field-mapping JSON.

    Returns
    -------
    dict[str, str]
        Mapping from dot-path keys to display labels.
    """
    try:
        mapping = load_field_mapping()
    except Exception:
        return {}
    return {
        field.key: field.label
        for field in mapping.fields
        if field.key.startswith("camera_settings.")
        and field.label.strip()
    }


def label_for_camera_setting_key(key: str) -> str:
    """Return human-readable label for a datacard camera setting key.

    Parameters
    ----------
    key : str
        Dot-path key from the datacard payload.

    Returns
    -------
    str
        Human-readable field label.
    """
    label = _camera_setting_labels().get(key)
    if label is not None:
        return label
    if key.startswith("camera_settings."):
        return _prettify_identifier(key[len("camera_settings."):])
    return _prettify_identifier(key)


def label_for_metadata_field(field: str, fallback: Optional[str] = None) -> str:
    """Return display label for derived metadata field names.

    Parameters
    ----------
    field : str
        Metadata field key.
    fallback : Optional[str], default=None
        Fallback label when the key is unknown.

    Returns
    -------
    str
        Display label for the field.
    """
    if field in METADATA_FIELD_LABELS:
        return METADATA_FIELD_LABELS[field]
    if fallback is not None:
        return fallback
    return _prettify_identifier(field)

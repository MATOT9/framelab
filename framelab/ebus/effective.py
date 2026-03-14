"""Effective eBUS config synthesis and acquisition-source helpers."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .catalog import ebus_catalog_index
from .models import EbusEffectiveParameter, EbusSnapshot, EbusSourceDescriptor
from .parser import parse_ebus_config
from .sidecar import discover_ebus_snapshot_path
from ..acquisition_datacard import (
    find_acquisition_root,
    resolve_acquisition_datacard_path,
)
from ..payload_utils import read_json_dict


def _normalize_override_key_map(overrides: Any) -> dict[str, Any]:
    """Normalize an override map keyed by eBUS qualified key."""
    if not isinstance(overrides, dict):
        return {}
    cleaned: dict[str, Any] = {}
    for key, value in overrides.items():
        qualified_key = str(key).strip()
        if qualified_key:
            cleaned[qualified_key] = deepcopy(value)
    return cleaned


def _ebus_block(payload: Any) -> dict[str, Any] | None:
    """Return the acquisition-local ``external_sources.ebus`` block."""
    if not isinstance(payload, dict):
        return None
    external_sources = payload.get("external_sources")
    if not isinstance(external_sources, dict):
        return None
    ebus_block = external_sources.get("ebus")
    if not isinstance(ebus_block, dict):
        return None
    return ebus_block


def ebus_enabled(payload: Any) -> bool:
    """Return whether acquisition-local eBUS snapshot use is enabled."""
    ebus_block = _ebus_block(payload)
    if ebus_block is None:
        return True
    raw_enabled = ebus_block.get("enabled")
    if raw_enabled is None:
        return True
    return bool(raw_enabled)


def ebus_enabled_for_acquisition(acquisition_root: str | Path) -> bool:
    """Return whether one acquisition allows eBUS snapshot-backed behavior."""
    payload = read_json_dict(resolve_acquisition_datacard_path(acquisition_root))
    return ebus_enabled(payload)


def discover_effective_ebus_snapshot_path(
    acquisition_root: str | Path,
    payload: Any | None = None,
) -> Path | None:
    """Return the acquisition snapshot path only when eBUS is enabled."""
    if payload is None:
        payload = read_json_dict(resolve_acquisition_datacard_path(acquisition_root))
    if not ebus_enabled(payload):
        return None
    return discover_ebus_snapshot_path(acquisition_root)


def load_ebus_override_map(
    payload: Any,
    *,
    honor_enabled: bool = True,
) -> dict[str, Any]:
    """Extract acquisition-wide eBUS overrides from a datacard payload block."""
    ebus_block = _ebus_block(payload)
    if ebus_block is None:
        return {}
    if honor_enabled and not ebus_enabled(payload):
        return {}
    return _normalize_override_key_map(ebus_block.get("overrides"))


def load_ebus_override_map_from_acquisition(
    acquisition_root: str | Path,
    *,
    honor_enabled: bool = True,
) -> dict[str, Any]:
    """Load acquisition-wide eBUS overrides from a datacard file."""
    payload = read_json_dict(resolve_acquisition_datacard_path(acquisition_root))
    if payload is None:
        return {}
    return load_ebus_override_map(payload, honor_enabled=honor_enabled)


def effective_ebus_parameters(
    snapshot: EbusSnapshot,
    overrides: dict[str, Any] | None = None,
) -> dict[str, EbusEffectiveParameter]:
    """Overlay app-side overrides on an immutable eBUS snapshot baseline."""
    catalog = ebus_catalog_index()
    override_map = _normalize_override_key_map(overrides)
    baseline = snapshot.by_key()
    keys = sorted(baseline)
    resolved: dict[str, EbusEffectiveParameter] = {}
    for qualified_key in keys:
        entry = catalog.get(qualified_key)
        base = baseline.get(qualified_key)
        name = qualified_key.rsplit(".", 1)[-1]
        section = qualified_key.rsplit(".", 1)[0] if "." in qualified_key else ""
        if base is not None:
            name = base.name
            section = base.section
        elif entry is not None:
            section = entry.section
            name = qualified_key.rsplit(".", 1)[-1]

        baseline_raw = base.raw_value if base is not None else None
        baseline_normalized_value = (
            base.normalized_value if base is not None else None
        )
        baseline_normalized_type = (
            base.normalized_type if base is not None else "missing"
        )

        effective_raw = baseline_raw or ""
        effective_normalized_value = baseline_normalized_value
        effective_normalized_type = baseline_normalized_type
        provenance = "raw snapshot" if base is not None else "missing"

        if entry is not None and entry.overridable and qualified_key in override_map:
            override_value = deepcopy(override_map[qualified_key])
            effective_normalized_value = override_value
            effective_normalized_type = type(override_value).__name__
            effective_raw = "" if override_value is None else str(override_value)
            provenance = "app override"

        resolved[qualified_key] = EbusEffectiveParameter(
            qualified_key=qualified_key,
            section=section,
            name=name,
            baseline_raw_value=baseline_raw,
            baseline_normalized_value=baseline_normalized_value,
            baseline_normalized_type=baseline_normalized_type,
            effective_raw_value=effective_raw,
            effective_normalized_value=effective_normalized_value,
            effective_normalized_type=effective_normalized_type,
            provenance=provenance,
            catalog_entry=entry if entry is not None else (base.catalog_entry if base is not None else None),
        )
    return resolved


def describe_ebus_source(path: str | Path) -> EbusSourceDescriptor | None:
    """Describe a ``.pvcfg`` file or acquisition root for inspect/compare flows."""
    candidate = Path(path)
    if candidate.is_file() and candidate.suffix.lower() == ".pvcfg":
        snapshot = parse_ebus_config(candidate)
        return EbusSourceDescriptor(
            path=candidate,
            source_kind="standalone_file",
            snapshot=snapshot,
            overrides={},
            display_name=candidate.name,
        )

    acquisition_root = find_acquisition_root(candidate)
    if candidate.is_dir():
        acquisition_root = candidate
    if acquisition_root is None:
        return None
    payload = read_json_dict(resolve_acquisition_datacard_path(acquisition_root))
    snapshot_path = discover_effective_ebus_snapshot_path(
        acquisition_root,
        payload,
    )
    if snapshot_path is None:
        return None
    snapshot = parse_ebus_config(snapshot_path)
    overrides = load_ebus_override_map(payload, honor_enabled=True)
    return EbusSourceDescriptor(
        path=acquisition_root,
        source_kind="acquisition_file",
        snapshot=snapshot,
        overrides=overrides,
        display_name=acquisition_root.name,
    )

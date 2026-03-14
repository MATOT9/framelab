"""Resolution helpers for canonical fields backed by eBUS snapshots."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..datacard_authoring import FieldMapping, FieldSpec, load_field_mapping
from ..payload_utils import flatten_payload_dict, set_dot_path
from .catalog import ebus_catalog_index
from .effective import (
    discover_effective_ebus_snapshot_path,
    effective_ebus_parameters,
    load_ebus_override_map,
)
from .parser import parse_ebus_config


@dataclass(frozen=True, slots=True)
class EbusCanonicalFieldResolution:
    """Resolved acquisition-wide state for one canonical eBUS-backed field."""

    key: str
    ebus_label: str
    snapshot_present: bool = False
    snapshot_value: Any = None
    effective_value: Any = None
    defaults_locked: bool = False
    provenance: str = "none"


@dataclass(frozen=True, slots=True)
class EbusCanonicalResolutionSet:
    """Resolved acquisition-wide eBUS state for canonical mapped fields."""

    acquisition_root: Path
    snapshot_path: Path | None
    snapshot_loaded: bool
    fields: tuple[EbusCanonicalFieldResolution, ...]

    def by_key(self) -> dict[str, EbusCanonicalFieldResolution]:
        """Return field resolutions indexed by canonical key."""
        return {
            field.key: field
            for field in self.fields
        }


def coerce_ebus_value_for_spec(raw_value: Any, spec: FieldSpec) -> Any:
    """Coerce one eBUS value into the canonical field type."""
    if raw_value is None:
        return None
    if spec.value_type == "int":
        try:
            return int(raw_value)
        except Exception:
            return None
    if spec.value_type == "float":
        try:
            return float(raw_value)
        except Exception:
            return None
    if spec.value_type == "bool":
        if isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, str):
            lowered = raw_value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
        return None
    if spec.value_type in {"string", "enum"}:
        return str(raw_value)
    return raw_value


def resolve_ebus_canonical_fields(
    acquisition_root: str | Path,
    payload: Any,
    mapping: FieldMapping | None = None,
) -> EbusCanonicalResolutionSet:
    """Resolve acquisition-wide canonical field values backed by eBUS."""
    root = Path(acquisition_root)
    mapping_obj = mapping or load_field_mapping()
    specs = tuple(
        field
        for field in mapping_obj.fields
        if field.ebus_managed and field.ebus_label
    )
    snapshot_path = discover_effective_ebus_snapshot_path(root, payload)
    if snapshot_path is None or not snapshot_path.is_file():
        return EbusCanonicalResolutionSet(
            acquisition_root=root,
            snapshot_path=snapshot_path,
            snapshot_loaded=False,
            fields=tuple(
                EbusCanonicalFieldResolution(
                    key=spec.key,
                    ebus_label=spec.ebus_label,
                )
                for spec in specs
            ),
        )

    try:
        snapshot = parse_ebus_config(snapshot_path)
    except Exception:
        return EbusCanonicalResolutionSet(
            acquisition_root=root,
            snapshot_path=snapshot_path,
            snapshot_loaded=False,
            fields=tuple(
                EbusCanonicalFieldResolution(
                    key=spec.key,
                    ebus_label=spec.ebus_label,
                )
                for spec in specs
            ),
        )

    catalog = ebus_catalog_index()
    overrides = load_ebus_override_map(payload)
    defaults_flat = {}
    if isinstance(payload, dict):
        raw_defaults = payload.get("defaults")
        if isinstance(raw_defaults, dict):
            defaults_flat = flatten_payload_dict(raw_defaults)
    effective_by_key = effective_ebus_parameters(snapshot, overrides)
    snapshot_by_key = snapshot.by_key()
    resolved: list[EbusCanonicalFieldResolution] = []

    for spec in specs:
        base = snapshot_by_key.get(spec.ebus_label)
        if base is None:
            resolved.append(
                EbusCanonicalFieldResolution(
                    key=spec.key,
                    ebus_label=spec.ebus_label,
                ),
            )
            continue

        snapshot_value = coerce_ebus_value_for_spec(
            base.normalized_value,
            spec,
        )
        if snapshot_value is None:
            resolved.append(
                EbusCanonicalFieldResolution(
                    key=spec.key,
                    ebus_label=spec.ebus_label,
                ),
            )
            continue

        entry = catalog.get(spec.ebus_label)
        effective_value = snapshot_value
        provenance = "ebus_snapshot"
        if (
            entry is not None
            and entry.overridable
            and spec.key in defaults_flat
            and defaults_flat.get(spec.key) is not None
        ):
            acquisition_default = coerce_ebus_value_for_spec(
                defaults_flat.get(spec.key),
                spec,
            )
            if acquisition_default is not None:
                effective_value = acquisition_default
                provenance = "acquisition_default"
        effective = effective_by_key.get(spec.ebus_label)
        if effective is not None and effective.provenance == "app override":
            override_value = coerce_ebus_value_for_spec(
                effective.effective_normalized_value,
                spec,
            )
            if override_value is not None:
                effective_value = override_value
                provenance = "ebus_override"

        resolved.append(
            EbusCanonicalFieldResolution(
                key=spec.key,
                ebus_label=spec.ebus_label,
                snapshot_present=True,
                snapshot_value=snapshot_value,
                effective_value=effective_value,
                defaults_locked=not bool(entry is not None and entry.overridable),
                provenance=provenance,
            ),
        )

    return EbusCanonicalResolutionSet(
        acquisition_root=root,
        snapshot_path=snapshot_path,
        snapshot_loaded=True,
        fields=tuple(resolved),
    )


def apply_ebus_canonical_baseline(
    base_context: dict[str, Any],
    resolutions: EbusCanonicalResolutionSet,
) -> dict[str, Any]:
    """Overlay effective acquisition-wide eBUS values on canonical defaults."""
    context = deepcopy(base_context)
    for field in resolutions.fields:
        if not field.snapshot_present:
            continue
        set_dot_path(context, field.key, deepcopy(field.effective_value))
    return context

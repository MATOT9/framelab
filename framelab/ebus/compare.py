"""Comparison helpers for raw and effective eBUS sources."""

from __future__ import annotations

from typing import Any, Mapping

from .effective import effective_ebus_parameters
from .models import (
    EbusCatalogEntry,
    EbusCompareEntry,
    EbusEffectiveParameter,
    EbusParameter,
    EbusSnapshot,
)
from .catalog import ebus_catalog_index
from .catalog import mapped_datacard_key_for_ebus


def _display_value(value: Any) -> str:
    """Return a compact display string for compare tables."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _status_for(left_value: Any, right_value: Any) -> str:
    """Return compare status for two values."""
    if left_value is None and right_value is None:
        return "identical"
    if left_value is None:
        return "right_only"
    if right_value is None:
        return "left_only"
    return "identical" if left_value == right_value else "changed"


def _compare_maps(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    raw_mode: bool,
) -> list[EbusCompareEntry]:
    """Compare two normalized raw/effective parameter maps."""
    catalog = ebus_catalog_index()
    entries: list[EbusCompareEntry] = []
    keys = sorted(set(left).union(set(right)))
    for qualified_key in keys:
        left_item = left.get(qualified_key)
        right_item = right.get(qualified_key)
        catalog_entry: EbusCatalogEntry | None = catalog.get(qualified_key)
        if catalog_entry is None:
            if isinstance(left_item, EbusParameter):
                catalog_entry = left_item.catalog_entry
            elif isinstance(left_item, EbusEffectiveParameter):
                catalog_entry = left_item.catalog_entry
            elif isinstance(right_item, EbusParameter):
                catalog_entry = right_item.catalog_entry
            elif isinstance(right_item, EbusEffectiveParameter):
                catalog_entry = right_item.catalog_entry

        if raw_mode:
            left_value = (
                left_item.normalized_value
                if isinstance(left_item, EbusParameter)
                else None
            )
            right_value = (
                right_item.normalized_value
                if isinstance(right_item, EbusParameter)
                else None
            )
            left_display = (
                left_item.raw_value if isinstance(left_item, EbusParameter) else ""
            )
            right_display = (
                right_item.raw_value if isinstance(right_item, EbusParameter) else ""
            )
            left_provenance = "raw snapshot" if left_item is not None else ""
            right_provenance = "raw snapshot" if right_item is not None else ""
        else:
            left_value = (
                left_item.effective_normalized_value
                if isinstance(left_item, EbusEffectiveParameter)
                else None
            )
            right_value = (
                right_item.effective_normalized_value
                if isinstance(right_item, EbusEffectiveParameter)
                else None
            )
            left_display = (
                left_item.effective_raw_value
                if isinstance(left_item, EbusEffectiveParameter)
                else ""
            )
            right_display = (
                right_item.effective_raw_value
                if isinstance(right_item, EbusEffectiveParameter)
                else ""
            )
            left_provenance = (
                left_item.provenance
                if isinstance(left_item, EbusEffectiveParameter)
                else ""
            )
            right_provenance = (
                right_item.provenance
                if isinstance(right_item, EbusEffectiveParameter)
                else ""
            )

        label = qualified_key.rsplit(".", 1)[-1]
        section = qualified_key.rsplit(".", 1)[0] if "." in qualified_key else ""
        mapped_datacard_key = ""
        relevance = "operational"
        overridable = False
        if catalog_entry is not None:
            label = catalog_entry.label or label
            section = catalog_entry.section or section
            relevance = catalog_entry.relevance
            overridable = catalog_entry.overridable
        mapped_datacard_key = mapped_datacard_key_for_ebus(qualified_key)

        entries.append(
            EbusCompareEntry(
                qualified_key=qualified_key,
                section=section,
                label=label,
                left_value=left_value,
                right_value=right_value,
                left_display=left_display or _display_value(left_value),
                right_display=right_display or _display_value(right_value),
                left_provenance=left_provenance,
                right_provenance=right_provenance,
                status=_status_for(left_value, right_value),
                overridable=overridable,
                mapped_datacard_key=mapped_datacard_key,
                relevance=relevance,
            ),
        )
    return entries


def compare_raw_snapshots(
    left: EbusSnapshot,
    right: EbusSnapshot,
) -> list[EbusCompareEntry]:
    """Compare two raw immutable eBUS snapshots."""
    return _compare_maps(left.by_key(), right.by_key(), raw_mode=True)


def compare_effective_configs(
    left_snapshot: EbusSnapshot,
    left_overrides: dict[str, Any],
    right_snapshot: EbusSnapshot,
    right_overrides: dict[str, Any],
) -> list[EbusCompareEntry]:
    """Compare two effective eBUS configs after overlaying app overrides."""
    left = effective_ebus_parameters(left_snapshot, left_overrides)
    right = effective_ebus_parameters(right_snapshot, right_overrides)
    return _compare_maps(left, right, raw_mode=False)

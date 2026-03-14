"""Typed models for eBUS snapshot parsing and comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True, slots=True)
class EbusCatalogEntry:
    """One catalogued eBUS parameter definition."""

    qualified_key: str
    section: str
    label: str
    description: str = ""
    unit: str = ""
    relevance: str = "operational"
    show_in_compare: bool = True
    show_in_summary: bool = False
    overridable: bool = False
    editable_in_ebus: bool = True
    value_type_hint: str = ""


@dataclass(frozen=True, slots=True)
class EbusParameter:
    """One normalized eBUS parameter record."""

    qualified_key: str
    section: str
    name: str
    raw_value: str
    normalized_value: Any
    normalized_type: str
    catalog_entry: Optional[EbusCatalogEntry] = None

    @property
    def label(self) -> str:
        """Return display label from catalog when available."""
        if self.catalog_entry is not None and self.catalog_entry.label:
            return self.catalog_entry.label
        return self.name

    @property
    def mapped_datacard_key(self) -> str:
        """Return mapped canonical datacard key when configured."""
        if self.catalog_entry is None:
            return ""
        from .catalog import mapped_datacard_key_for_ebus

        return mapped_datacard_key_for_ebus(self.qualified_key)


@dataclass(frozen=True, slots=True)
class EbusSnapshot:
    """Parsed immutable eBUS snapshot."""

    source_path: Path
    format_version: str
    parameters: tuple[EbusParameter, ...]
    sections: tuple[str, ...] = ()

    def by_key(self) -> dict[str, EbusParameter]:
        """Return parameters indexed by qualified key."""
        return {
            parameter.qualified_key: parameter
            for parameter in self.parameters
        }


@dataclass(frozen=True, slots=True)
class EbusEffectiveParameter:
    """Effective eBUS parameter after overlaying app-side overrides."""

    qualified_key: str
    section: str
    name: str
    baseline_raw_value: Optional[str]
    baseline_normalized_value: Any
    baseline_normalized_type: str
    effective_raw_value: str
    effective_normalized_value: Any
    effective_normalized_type: str
    provenance: str
    catalog_entry: Optional[EbusCatalogEntry] = None

    @property
    def label(self) -> str:
        """Return display label from catalog when available."""
        if self.catalog_entry is not None and self.catalog_entry.label:
            return self.catalog_entry.label
        return self.name

    @property
    def mapped_datacard_key(self) -> str:
        """Return mapped canonical datacard key when configured."""
        if self.catalog_entry is None:
            return ""
        from .catalog import mapped_datacard_key_for_ebus

        return mapped_datacard_key_for_ebus(self.qualified_key)


@dataclass(frozen=True, slots=True)
class EbusCompareEntry:
    """One compare-table entry for raw or effective eBUS comparison."""

    qualified_key: str
    section: str
    label: str
    left_value: Any
    right_value: Any
    left_display: str
    right_display: str
    left_provenance: str = ""
    right_provenance: str = ""
    status: str = "identical"
    overridable: bool = False
    mapped_datacard_key: str = ""
    relevance: str = "operational"


@dataclass(slots=True)
class EbusSourceDescriptor:
    """Parsed source descriptor for compare/inspect operations."""

    path: Path
    source_kind: str
    snapshot: Optional[EbusSnapshot] = None
    overrides: dict[str, Any] = field(default_factory=dict)
    display_name: str = ""

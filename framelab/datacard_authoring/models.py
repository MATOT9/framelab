"""Core types for acquisition datacard authoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass(slots=True)
class FieldSpec:
    """Single editable datacard field definition."""

    key: str
    label: str
    group: str
    value_type: str
    tooltip: str = ""
    ebus_label: str = ""
    ebus_managed: bool = False
    unit: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    step: Optional[float] = None
    options: tuple[str, ...] = ()
    show_in_defaults: bool = True
    show_in_overrides: bool = True


@dataclass(slots=True)
class FieldMapping:
    """Resolved field mapping used by the wizard/editor."""

    path: Path
    fields: tuple[FieldSpec, ...]
    warnings: tuple[str, ...] = ()

    def by_key(self) -> dict[str, FieldSpec]:
        """Return mapping indexed by dot-path key."""
        return {field.key: field for field in self.fields}


@dataclass(slots=True)
class OverrideRow:
    """Canonical override-row representation for authoring operations."""

    frame_start: int
    frame_end: int
    changes: dict[str, Any]
    reason: str = ""


@dataclass(slots=True)
class AcquisitionDatacardModel:
    """Editable acquisition datacard model."""

    schema_version: str = "1.0"
    entity: str = "acquisition"
    identity: dict[str, Any] = field(default_factory=dict)
    paths: dict[str, Any] = field(default_factory=dict)
    intent: dict[str, Any] = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)
    overrides: list[OverrideRow] = field(default_factory=list)
    quality: dict[str, Any] = field(default_factory=dict)
    external_sources: dict[str, Any] = field(default_factory=dict)
    source_path: Optional[Path] = None
    source_exists: bool = False
    index_base: int = 0
    frame_indices: list[int] = field(default_factory=list)
    frame_index_mode: str = "none"
    extra_top_level: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ValidationReport:
    """Validation output for datacard models."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Return True when no blocking validation errors were found."""
        return not self.errors


@dataclass(slots=True)
class FramePlan:
    """Frame selection configuration for override generation."""

    index_base: int = 0
    start_frame: Optional[int] = None
    end_frame: Optional[int] = None
    frame_indices: list[int] = field(default_factory=list)


@dataclass(slots=True)
class FieldPlan:
    """Field/value generation configuration for override generation."""

    key: str
    values: list[Any] = field(default_factory=list)
    start_value: Optional[float] = None
    stop_value: Optional[float] = None
    step_value: Optional[float] = None
    constant_value: Any = None
    reason: str = ""
    additional_changes: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MergeResult:
    """Override merge result for append/update flows."""

    rows: list[OverrideRow]
    warnings: list[str] = field(default_factory=list)

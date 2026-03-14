"""Core load/save/validate/generate services for acquisition datacards."""

from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
from typing import Any, Optional

from ..acquisition_datacard import (
    detect_override_index_base,
    resolve_acquisition_datacard_path,
    selector_frame_range,
)
from .mapping import load_field_mapping
from .models import (
    AcquisitionDatacardModel,
    FieldMapping,
    FieldPlan,
    FramePlan,
    MergeResult,
    OverrideRow,
    ValidationReport,
)
from ..frame_indexing import resolve_frame_index_map
from ..payload_utils import (
    flatten_payload_dict,
    read_json_dict,
    set_dot_path,
    unflatten_payload_dict,
    write_json_dict,
)


def _default_model() -> AcquisitionDatacardModel:
    """Return default empty acquisition datacard model."""
    return AcquisitionDatacardModel(
        schema_version="1.0",
        entity="acquisition",
        identity={
            "camera_id": None,
            "campaign_id": None,
            "session_id": None,
            "acquisition_id": None,
            "label": None,
            "created_at_local": None,
            "finalized_at_local": None,
            "timezone": None,
        },
        paths={
            "frames_dir": "frames",
        },
        intent={
            "capture_type": "calibration",
            "subtype": "",
            "scene": "",
            "tags": [],
        },
        defaults={
            "camera_settings": {},
            "instrument": {},
            "acquisition_settings": {},
        },
        overrides=[],
        quality={
            "anomalies": [],
            "dropped_frames": [],
            "saturation_expected": False,
        },
        external_sources={},
    )


def _discover_frame_indices(
    acq_root: Path,
    frames_dir_name: str,
) -> tuple[list[int], str]:
    """Discover frame indices and report discovery mode."""
    frames_dir = acq_root.joinpath(frames_dir_name)
    resolution = resolve_frame_index_map(frames_dir)
    return (resolution.indices, resolution.mode)


def _rows_from_overrides(
    overrides: list[dict[str, Any]],
) -> list[OverrideRow]:
    """Convert payload overrides to canonical rows."""
    rows: list[OverrideRow] = []
    for item in overrides:
        frame_range = selector_frame_range(item)
        if frame_range is None:
            continue
        start, end = frame_range
        changes_raw = item.get("changes")
        changes = (
            flatten_payload_dict(changes_raw)
            if isinstance(changes_raw, dict)
            else {}
        )
        rows.append(
            OverrideRow(
                frame_start=start,
                frame_end=end,
                changes=changes,
                reason=str(item.get("reason", "")).strip(),
            ),
        )
    return rows


def _top_level_sections(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split payload into known and extra top-level sections."""
    known = {
        "schema_version",
        "entity",
        "identity",
        "paths",
        "intent",
        "defaults",
        "overrides",
        "quality",
        "external_sources",
    }
    extra = {
        key: deepcopy(value)
        for key, value in payload.items()
        if key not in known
    }
    return (payload, extra)


def _sanitize_paths_dict(paths: Any) -> dict[str, Any]:
    """Keep only supported path keys in a paths payload dictionary."""
    if not isinstance(paths, dict):
        return {}
    cleaned: dict[str, Any] = {}
    frames_dir = paths.get("frames_dir")
    if frames_dir is not None:
        cleaned["frames_dir"] = deepcopy(frames_dir)
    return cleaned


def _sanitize_defaults_dict(
    defaults: Any,
    allowed_keys: Optional[set[str]] = None,
) -> dict[str, Any]:
    """Keep only mapping-backed defaults in a defaults payload dictionary."""
    if not isinstance(defaults, dict):
        return {}
    keys = allowed_keys or set(load_field_mapping().by_key())
    cleaned: dict[str, Any] = {}
    for key, value in flatten_payload_dict(defaults).items():
        if key in keys:
            set_dot_path(cleaned, key, deepcopy(value))
    return cleaned


def _sanitize_override_rows(
    rows: list[OverrideRow],
    allowed_keys: Optional[set[str]] = None,
) -> list[OverrideRow]:
    """Keep only mapping-backed override keys and remove empty rows."""
    keys = allowed_keys or set(load_field_mapping().by_key())
    sanitized_rows: list[OverrideRow] = []
    for row in rows:
        cleaned_changes = dict(row.changes) if isinstance(row.changes, dict) else {}
        cleaned_changes = {
            key: value
            for key, value in cleaned_changes.items()
            if key in keys
        }
        if not cleaned_changes:
            continue
        sanitized_rows.append(
            OverrideRow(
                frame_start=row.frame_start,
                frame_end=row.frame_end,
                changes=cleaned_changes,
                reason=row.reason,
            ),
        )
    return sanitized_rows


def _sanitize_external_sources_dict(external_sources: Any) -> dict[str, Any]:
    """Keep external source metadata in a stable dictionary shape."""
    if not isinstance(external_sources, dict):
        return {}
    cleaned = deepcopy(external_sources)
    ebus = cleaned.get("ebus")
    if not isinstance(ebus, dict):
        return cleaned
    sanitized_ebus: dict[str, Any] = {}
    if "enabled" in ebus:
        sanitized_ebus["enabled"] = bool(ebus.get("enabled"))
    for key in (
        "attached_file",
        "source_hash_sha256",
        "source_mtime_ns",
        "source_size_bytes",
        "parse_version",
        "attached_at_local",
        "notes",
    ):
        if key in ebus:
            sanitized_ebus[key] = deepcopy(ebus[key])
    overrides = ebus.get("overrides")
    if isinstance(overrides, dict):
        sanitized_ebus["overrides"] = {
            str(key).strip(): deepcopy(value)
            for key, value in overrides.items()
            if str(key).strip()
        }
    else:
        sanitized_ebus["overrides"] = {}
    cleaned["ebus"] = sanitized_ebus
    return cleaned


def load_acquisition_datacard(path: str | Path) -> AcquisitionDatacardModel:
    """Load existing datacard or initialize a new model.

    Parameters
    ----------
    path : str | Path
        Acquisition folder path or explicit datacard path.
    """
    datacard_path = resolve_acquisition_datacard_path(path)
    acq_root = datacard_path.parent
    payload = read_json_dict(datacard_path)

    model = _default_model()
    model.source_path = datacard_path
    model.source_exists = bool(payload is not None and datacard_path.is_file())
    allowed_keys = set(load_field_mapping().by_key())

    if payload is not None:
        payload, extra = _top_level_sections(payload)
        model.schema_version = str(payload.get("schema_version", "1.0"))
        model.entity = str(payload.get("entity", "acquisition"))
        model.identity = (
            deepcopy(payload.get("identity"))
            if isinstance(payload.get("identity"), dict)
            else {}
        )
        model.paths = _sanitize_paths_dict(payload.get("paths"))
        model.intent = (
            deepcopy(payload.get("intent"))
            if isinstance(payload.get("intent"), dict)
            else {}
        )
        model.defaults = _sanitize_defaults_dict(payload.get("defaults"), allowed_keys)
        model.quality = (
            deepcopy(payload.get("quality"))
            if isinstance(payload.get("quality"), dict)
            else {}
        )
        model.external_sources = _sanitize_external_sources_dict(
            payload.get("external_sources"),
        )
        model.extra_top_level = extra

    frames_dir = str(model.paths.get("frames_dir", "frames") or "frames")
    frame_indices, frame_mode = _discover_frame_indices(acq_root, frames_dir)
    model.frame_indices = frame_indices
    model.frame_index_mode = frame_mode

    raw_overrides = []
    if payload is not None and isinstance(payload.get("overrides"), list):
        raw_overrides = list(payload.get("overrides", []))
    model.index_base = detect_override_index_base(raw_overrides, frame_indices)
    model.overrides = _sanitize_override_rows(
        _rows_from_overrides(raw_overrides),
        allowed_keys,
    )
    return model


def _validate_row(
    row: OverrideRow,
    row_index: int,
    mapping_by_key: dict[str, Any],
    report: ValidationReport,
) -> None:
    """Validate one override row."""
    if not isinstance(row.frame_start, int) or not isinstance(row.frame_end, int):
        report.errors.append(
            f"Override row #{row_index}: frame range must contain integers.",
        )
        return
    if row.frame_start > row.frame_end:
        report.errors.append(
            f"Override row #{row_index}: frame_start must be <= frame_end.",
        )
    if not row.changes:
        report.warnings.append(
            f"Override row #{row_index}: no change fields defined.",
        )
    for key, value in row.changes.items():
        if not isinstance(key, str) or not key.strip():
            report.errors.append(
                f"Override row #{row_index}: empty/invalid field key.",
            )
            continue
        spec = mapping_by_key.get(key)
        if spec is None:
            report.warnings.append(
                f"Override row #{row_index}: unknown field '{key}'.",
            )
            continue
        if spec.value_type == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                report.errors.append(
                    f"Override row #{row_index}: field '{key}' expects int.",
                )
        elif spec.value_type == "float":
            if isinstance(value, bool):
                report.errors.append(
                    f"Override row #{row_index}: field '{key}' expects float.",
                )
            else:
                try:
                    number = float(value)
                except Exception:
                    report.errors.append(
                        f"Override row #{row_index}: field '{key}' expects float.",
                    )
                else:
                    if not math.isfinite(number):
                        report.errors.append(
                            f"Override row #{row_index}: field '{key}' must be finite.",
                        )
        elif spec.value_type == "bool":
            if not isinstance(value, bool):
                report.errors.append(
                    f"Override row #{row_index}: field '{key}' expects bool.",
                )
        elif spec.value_type == "enum":
            if str(value) not in set(spec.options):
                report.errors.append(
                    f"Override row #{row_index}: field '{key}' invalid option '{value}'.",
                )
        elif spec.value_type == "string":
            if not isinstance(value, str):
                report.errors.append(
                    f"Override row #{row_index}: field '{key}' expects string.",
                )


def validate_datacard(
    model: AcquisitionDatacardModel,
    mapping: Optional[FieldMapping] = None,
) -> ValidationReport:
    """Validate model consistency and field typing."""
    report = ValidationReport()
    mapping_obj = mapping or load_field_mapping()
    mapping_by_key = mapping_obj.by_key()

    if model.entity != "acquisition":
        report.errors.append("Top-level 'entity' must be 'acquisition'.")

    for section_name in ("identity", "paths", "intent", "defaults", "quality"):
        section = getattr(model, section_name, None)
        if not isinstance(section, dict):
            report.errors.append(f"Top-level '{section_name}' must be an object.")
    if not isinstance(model.external_sources, dict):
        report.errors.append("Top-level 'external_sources' must be an object.")

    if model.index_base not in (0, 1):
        report.errors.append("Frame index base must be 0 or 1.")

    for row_index, row in enumerate(model.overrides, start=1):
        _validate_row(row, row_index, mapping_by_key, report)

    return report


def _frange(
    start_value: float,
    stop_value: float,
    step_value: float,
) -> list[float]:
    """Generate inclusive float range with bounded loop length."""
    if math.isclose(step_value, 0.0, abs_tol=1e-15):
        raise ValueError("step must be non-zero")
    values: list[float] = []
    max_count = 100_000
    current = start_value
    for _ in range(max_count):
        if step_value > 0.0 and current > stop_value + abs(step_value) * 1e-9:
            break
        if step_value < 0.0 and current < stop_value - abs(step_value) * 1e-9:
            break
        values.append(float(current))
        current += step_value
    return values


def _single_change_row(
    frame_index: int,
    key: str,
    value: Any,
    reason: str,
    additional_changes: Optional[dict[str, Any]] = None,
) -> OverrideRow:
    """Build single-frame override row."""
    changes = {key: value}
    if additional_changes:
        for extra_key, extra_value in additional_changes.items():
            if isinstance(extra_key, str) and extra_key.strip():
                changes[extra_key] = extra_value
    return OverrideRow(
        frame_start=int(frame_index),
        frame_end=int(frame_index),
        changes=changes,
        reason=reason.strip(),
    )


def generate_overrides(
    frame_plan: FramePlan,
    field_plan: FieldPlan,
    mode: str,
) -> list[OverrideRow]:
    """Generate override rows for one authoring mode.

    Supported modes are ``global_defaults_only``, ``explicit_list``,
    ``numeric_sweep``, and ``constant_range``.
    """
    normalized_mode = str(mode).strip().lower()
    if normalized_mode == "global_defaults_only":
        return []

    key = str(field_plan.key).strip()
    if not key:
        raise ValueError("field key is required for override generation")

    reason = field_plan.reason or "generated"
    additional = dict(field_plan.additional_changes)
    rows: list[OverrideRow] = []

    if normalized_mode == "explicit_list":
        values = list(field_plan.values)
        if not values:
            return []
        if frame_plan.frame_indices:
            if len(values) > len(frame_plan.frame_indices):
                raise ValueError(
                    "Explicit value count exceeds available frame indices.",
                )
            frame_indices = frame_plan.frame_indices[: len(values)]
        else:
            start = (
                int(frame_plan.start_frame)
                if frame_plan.start_frame is not None
                else 0
            )
            frame_indices = list(range(start, start + len(values)))
        for frame_index, value in zip(frame_indices, values):
            rows.append(
                _single_change_row(
                    frame_index=frame_index,
                    key=key,
                    value=value,
                    reason=reason,
                    additional_changes=additional,
                ),
            )
        return rows

    if normalized_mode == "numeric_sweep":
        if (
            field_plan.start_value is None
            or field_plan.stop_value is None
            or field_plan.step_value is None
        ):
            raise ValueError("Numeric sweep requires start/stop/step values.")
        values = _frange(
            float(field_plan.start_value),
            float(field_plan.stop_value),
            float(field_plan.step_value),
        )
        if not values:
            return []
        if frame_plan.frame_indices:
            if len(values) > len(frame_plan.frame_indices):
                raise ValueError(
                    "Generated sweep exceeds available frame indices.",
                )
            frame_indices = frame_plan.frame_indices[: len(values)]
        else:
            start = (
                int(frame_plan.start_frame)
                if frame_plan.start_frame is not None
                else 0
            )
            frame_indices = list(range(start, start + len(values)))
        for frame_index, value in zip(frame_indices, values):
            rows.append(
                _single_change_row(
                    frame_index=frame_index,
                    key=key,
                    value=value,
                    reason=reason,
                    additional_changes=additional,
                ),
            )
        return rows

    if normalized_mode == "constant_range":
        if frame_plan.start_frame is None or frame_plan.end_frame is None:
            raise ValueError("Constant range mode requires frame start/end.")
        start = int(frame_plan.start_frame)
        end = int(frame_plan.end_frame)
        if start > end:
            start, end = end, start
        return [
            OverrideRow(
                frame_start=start,
                frame_end=end,
                changes={
                    **additional,
                    key: field_plan.constant_value,
                },
                reason=reason,
            ),
        ]

    raise ValueError(f"Unsupported generation mode: {mode}")


def _ranges_overlap(
    left_start: int,
    left_end: int,
    right_start: int,
    right_end: int,
) -> bool:
    """Return whether two frame ranges overlap."""
    return not (left_end < right_start or right_end < left_start)


def append_overrides(
    existing_rows: list[OverrideRow],
    new_rows: list[OverrideRow],
    policy: str = "last_write_wins",
) -> MergeResult:
    """Append/merge override rows according to requested policy."""
    if policy != "last_write_wins":
        raise ValueError(f"Unsupported merge policy: {policy}")

    merged = [deepcopy(row) for row in existing_rows]
    warnings: list[str] = []
    for row in new_rows:
        for existing in merged:
            if not _ranges_overlap(
                row.frame_start,
                row.frame_end,
                existing.frame_start,
                existing.frame_end,
            ):
                continue
            overlap_keys = set(row.changes.keys()).intersection(
                set(existing.changes.keys()),
            )
            for key in sorted(overlap_keys):
                warnings.append(
                    "Overlap detected for field "
                    f"'{key}' on ranges [{existing.frame_start}, {existing.frame_end}] "
                    f"and [{row.frame_start}, {row.frame_end}]; "
                    "new row takes precedence by order.",
                )
        merged.append(deepcopy(row))
    return MergeResult(rows=merged, warnings=warnings)


def _rows_to_payload(
    rows: list[OverrideRow],
) -> list[dict[str, Any]]:
    """Convert canonical rows to datacard payload override objects."""
    payload_rows: list[dict[str, Any]] = []
    for row in rows:
        start = int(row.frame_start)
        end = int(row.frame_end)
        if start > end:
            start, end = end, start
        payload_rows.append(
            {
                "selector": {"frame_range": [start, end]},
                "changes": unflatten_payload_dict(dict(row.changes)),
                "reason": row.reason or "explicit frame state",
            },
        )
    return payload_rows


def datacard_to_payload(model: AcquisitionDatacardModel) -> dict[str, Any]:
    """Serialize model to JSON payload dictionary."""
    allowed_keys = set(load_field_mapping().by_key())
    payload: dict[str, Any] = dict(model.extra_top_level)
    payload.update(
        {
            "schema_version": model.schema_version,
            "entity": model.entity,
            "identity": deepcopy(model.identity),
            "paths": _sanitize_paths_dict(model.paths),
            "intent": deepcopy(model.intent),
            "defaults": _sanitize_defaults_dict(model.defaults, allowed_keys),
            "overrides": _rows_to_payload(
                _sanitize_override_rows(model.overrides, allowed_keys),
            ),
            "quality": deepcopy(model.quality),
        },
    )
    external_sources = _sanitize_external_sources_dict(model.external_sources)
    if external_sources:
        payload["external_sources"] = external_sources
    return payload


def save_acquisition_datacard(
    path: str | Path,
    model: AcquisitionDatacardModel,
) -> None:
    """Save model as ``acquisition_datacard.json``."""
    datacard_path = resolve_acquisition_datacard_path(path)
    payload = datacard_to_payload(model)
    write_json_dict(datacard_path, payload)

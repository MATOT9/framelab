"""Metadata extraction helpers for TIFF datasets."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
import re
from pathlib import Path
from typing import Any, Optional

from .acquisition_datacard import (
    find_campaign_root,
    find_acquisition_root,
    find_session_root,
    normalize_override_selectors,
    override_applies_to_frame,
    resolve_campaign_datacard_path,
    resolve_acquisition_datacard_path,
    resolve_session_datacard_path,
)
from .datacard_labels import label_for_camera_setting_key
from .ebus import (
    EbusCanonicalFieldResolution,
    EbusCanonicalResolutionSet,
    apply_ebus_canonical_baseline,
    discover_effective_ebus_snapshot_path,
    discover_ebus_snapshot_path,
    parse_ebus_config,
    resolve_ebus_canonical_fields,
)
from .frame_indexing import parse_frame_name, resolve_frame_index_map
from .metadata_state import (
    MetadataFieldSource,
    clear_metadata_state_cache,
    invalidate_metadata_state_cache,
    resolve_path_node_metadata,
)
from .node_metadata import path_has_nodecard
from .payload_utils import (
    flatten_payload_dict,
    read_json_dict,
    unflatten_payload_dict,
)
from .raw_decode import (
    SUPPORTED_MONO_RAW_PIXEL_FORMATS,
    normalize_raw_pixel_format,
)

EXPOSURE_PATTERN = re.compile(
    r"(?:exp(?:osure)?)[_\-\s]*([0-9]+(?:\.[0-9]+)?)\s*(us|µs|ms|s)?",
    re.IGNORECASE,
)
TIME_PATTERN = re.compile(
    r"([0-9]+(?:\.[0-9]+)?)\s*(us|µs|ms|s)",
    re.IGNORECASE,
)
IRIS_PATTERN = re.compile(
    r"(?:iris|pos(?:ition)?)[_\-\s]*([0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE,
)
_RAW_IMAGE_SUFFIXES = {".bin", ".raw"}
_RAW_FILENAME_METADATA_PATTERN = re.compile(
    r"(?:^|[_-])w(?P<width>\d+)[_-]h(?P<height>\d+)[_-]p(?P<pixel_format>[A-Za-z0-9_]+)(?:$|[._-])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _AcquisitionDatacard:
    """Resolved acquisition metadata stack for one acquisition root."""

    base_context: dict[str, Any]
    node_metadata_flat: dict[str, Any]
    node_source_by_key: dict[str, MetadataFieldSource]
    legacy_campaign_defaults_flat: dict[str, Any]
    legacy_session_defaults_flat: dict[str, Any]
    acquisition_defaults_flat: dict[str, Any]
    normalized_overrides: tuple[dict[str, Any], ...]
    override_index_base: int
    frame_index_by_name: dict[str, int]
    frame_index_mode: str
    ebus_resolutions: EbusCanonicalResolutionSet
    ebus_resolution_by_key: dict[str, EbusCanonicalFieldResolution]
    json_metadata_available: bool = False
    acquisition_datacard_path: Path | None = None
    session_datacard_path: Path | None = None
    campaign_datacard_path: Path | None = None
    frames_dir_path: Path | None = None
    ebus_attached: bool = False


_ACQ_CARD_CACHE: dict[tuple[Path, Path | None], Optional[_AcquisitionDatacard]] = {}


def clear_metadata_cache() -> None:
    """Clear per-acquisition metadata cache used by extraction helpers."""
    _ACQ_CARD_CACHE.clear()
    clear_metadata_state_cache()


def _is_same_or_child_path(path: Path, root: Path) -> bool:
    """Return whether ``path`` is the same as or below ``root``."""

    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _normalize_cache_root(root: str | Path) -> Path:
    """Normalize cache invalidation roots from either file or folder input."""

    candidate = Path(root).expanduser()
    if candidate.exists():
        return (candidate if candidate.is_dir() else candidate.parent).resolve()
    return (candidate.parent if candidate.suffix else candidate).resolve()


def invalidate_metadata_cache(
    changed_roots: tuple[str | Path, ...] = (),
) -> None:
    """Invalidate cached metadata derived from one or more edited roots."""

    normalized_roots = tuple(
        _normalize_cache_root(root)
        for root in changed_roots
    )
    if not normalized_roots:
        return
    invalidate_metadata_state_cache(normalized_roots)
    for key in tuple(_ACQ_CARD_CACHE):
        acquisition_root, _boundary_root = key
        if any(
            _is_same_or_child_path(acquisition_root, root)
            for root in normalized_roots
        ):
            _ACQ_CARD_CACHE.pop(key, None)


def _normalize_metadata_boundary_root(
    path: str | Path,
    boundary_root: str | Path | None,
) -> Path | None:
    """Return a resolved metadata boundary when the path falls inside it."""

    if boundary_root is None:
        return None
    candidate = Path(path).expanduser()
    candidate_dir = candidate if candidate.is_dir() else candidate.parent
    boundary = Path(boundary_root).expanduser().resolve()
    try:
        candidate_dir.resolve().relative_to(boundary)
    except ValueError:
        return None
    return boundary


def _root_within_metadata_boundary(
    root: Path | None,
    boundary_root: Path | None,
) -> Path | None:
    """Return the candidate root only when it sits inside the allowed boundary."""

    if root is None:
        return None
    resolved = root.resolve()
    if boundary_root is None:
        return resolved
    try:
        resolved.relative_to(boundary_root)
    except ValueError:
        return None
    return resolved


def _unit_to_ms(value: float, unit: str) -> float:
    """Convert time value/unit pair to milliseconds."""
    normalized = unit.lower()
    if normalized in {"us", "µs"}:
        return value / 1000.0
    if normalized == "s":
        return value * 1000.0
    return value


def _find_exposure_ms(text: str) -> Optional[float]:
    """Extract exposure from text and convert to milliseconds."""
    match = EXPOSURE_PATTERN.search(text)
    if match is not None:
        value = float(match.group(1))
        unit = match.group(2) or "ms"
        return _unit_to_ms(value, unit)

    match = TIME_PATTERN.search(text)
    if match is None:
        return None
    return _unit_to_ms(float(match.group(1)), match.group(2))


def _find_iris_position(text: str) -> Optional[float]:
    """Extract iris position from text, if present."""
    match = IRIS_PATTERN.search(text)
    if match is None:
        return None
    return float(match.group(1))


def _is_raw_image_path(path: Path) -> bool:
    """Return whether one path should use RAW metadata fallbacks."""

    return path.suffix.lower() in _RAW_IMAGE_SUFFIXES


def _raw_metadata_fallback_root(path: Path) -> Path | None:
    """Find the nearest acquisition-like root that carries RAW fallback context."""

    acquisition_root = find_acquisition_root(path, allow_name_only=True)
    if acquisition_root is not None:
        return acquisition_root.resolve()
    search_root = path if path.is_dir() else path.parent
    for parent in (search_root, *search_root.parents):
        try:
            if discover_ebus_snapshot_path(parent) is not None:
                return parent.resolve()
        except Exception:
            continue
    return None


def _raw_metadata_from_ebus_snapshot(path: Path) -> dict[str, object]:
    """Resolve RAW-required metadata from a nearby acquisition snapshot."""

    acquisition_root = _raw_metadata_fallback_root(path)
    if acquisition_root is None:
        return {}
    payload = read_json_dict(resolve_acquisition_datacard_path(acquisition_root))
    snapshot_path = discover_effective_ebus_snapshot_path(acquisition_root, payload or {})
    if snapshot_path is None or not snapshot_path.is_file():
        return {}
    try:
        snapshot = parse_ebus_config(snapshot_path)
    except Exception:
        return {}
    snapshot_by_key = snapshot.by_key()
    metadata: dict[str, object] = {
        "acquisition_root": str(acquisition_root),
    }
    raw_width = snapshot_by_key.get("device.Width")
    raw_height = snapshot_by_key.get("device.Height")
    raw_pixel_format = snapshot_by_key.get("device.PixelFormat")
    if raw_width is not None and isinstance(raw_width.normalized_value, int):
        metadata["camera_settings.resolution_x"] = int(raw_width.normalized_value)
        metadata["camera_settings.resolution_x_source"] = "ebus_snapshot"
    if raw_height is not None and isinstance(raw_height.normalized_value, int):
        metadata["camera_settings.resolution_y"] = int(raw_height.normalized_value)
        metadata["camera_settings.resolution_y_source"] = "ebus_snapshot"
    if raw_pixel_format is not None and str(raw_pixel_format.normalized_value or "").strip():
        metadata["camera_settings.pixel_format"] = str(raw_pixel_format.normalized_value)
        metadata["camera_settings.pixel_format_source"] = "ebus_snapshot"
    return metadata


def _raw_metadata_from_filename(path: Path) -> dict[str, object]:
    """Extract RAW-required metadata from filename tokens when present."""

    match = _RAW_FILENAME_METADATA_PATTERN.search(path.name)
    if match is None:
        return {}
    pixel_format = normalize_raw_pixel_format(match.group("pixel_format"))
    if pixel_format not in SUPPORTED_MONO_RAW_PIXEL_FORMATS:
        return {}
    try:
        width = int(match.group("width"))
        height = int(match.group("height"))
    except Exception:
        return {}
    if width <= 0 or height <= 0:
        return {}
    return {
        "camera_settings.pixel_format": pixel_format,
        "camera_settings.pixel_format_source": "filename_fallback",
        "camera_settings.resolution_x": width,
        "camera_settings.resolution_x_source": "filename_fallback",
        "camera_settings.resolution_y": height,
        "camera_settings.resolution_y_source": "filename_fallback",
    }


def _apply_raw_metadata_fallbacks(values: dict[str, object], path: Path) -> None:
    """Fill missing RAW decode fields from acquisition snapshots or filenames."""

    if not _is_raw_image_path(path):
        return
    for fallback in (
        _raw_metadata_from_ebus_snapshot(path),
        _raw_metadata_from_filename(path),
    ):
        if not fallback:
            continue
        acquisition_root = fallback.get("acquisition_root")
        if acquisition_root and "acquisition_root" not in values:
            values["acquisition_root"] = acquisition_root
        for key in (
            "camera_settings.pixel_format",
            "camera_settings.resolution_x",
            "camera_settings.resolution_y",
        ):
            if key in values or key not in fallback:
                continue
            values[key] = fallback[key]
            values[f"{key}_label"] = label_for_camera_setting_key(key)
            source = fallback.get(f"{key}_source")
            if source not in {None, ""}:
                values[f"{key}_source"] = source


def path_has_json_metadata(
    path: str | Path,
    *,
    metadata_boundary_root: str | Path | None = None,
) -> bool:
    """Return whether path belongs to any JSON-backed metadata ancestry."""
    candidate = Path(path)
    boundary_root = _normalize_metadata_boundary_root(
        candidate,
        metadata_boundary_root,
    )
    nodecard_present = False
    if boundary_root is None:
        nodecard_present = path_has_nodecard(candidate)
    else:
        nodecard_present = bool(
            resolve_path_node_metadata(
                candidate,
                boundary_root=boundary_root,
            ).layers,
        )
    return nodecard_present or any(
        root is not None
        for root in (
            _root_within_metadata_boundary(
                find_acquisition_root(candidate),
                boundary_root,
            ),
            _root_within_metadata_boundary(
                find_session_root(candidate),
                boundary_root,
            ),
            _root_within_metadata_boundary(
                find_campaign_root(candidate),
                boundary_root,
            ),
        )
    )


# LEGACY_COMPAT[path_has_acquisition_datacard_alias]: Preserve the old helper name while callers migrate to the broader nodecard-aware metadata check. Remove after: all call sites and docs use path_has_json_metadata instead of acquisition-datacard wording.
def path_has_acquisition_datacard(path: str | Path) -> bool:
    """Compatibility wrapper for older call sites expecting the old helper."""

    return path_has_json_metadata(path)


def _merge_inherit(base: Any, override: Any) -> Any:
    """Merge dictionaries with datacard inheritance semantics."""
    if override is None:
        return deepcopy(base)

    if isinstance(override, dict):
        merged = deepcopy(base) if isinstance(base, dict) else {}
        for key, value in override.items():
            if value is None:
                if key not in merged:
                    merged[key] = None
                continue

            base_value = merged.get(key)
            if isinstance(value, dict):
                merged[key] = _merge_inherit(base_value, value)
            elif isinstance(value, list):
                merged[key] = deepcopy(value)
            else:
                merged[key] = deepcopy(value)
        return merged

    if isinstance(override, list):
        return deepcopy(override)
    return deepcopy(override)


def _apply_overrides(
    base_context: dict[str, Any],
    normalized_overrides: tuple[dict[str, Any], ...],
    frame_index: int,
) -> tuple[dict[str, Any], bool, set[str]]:
    """Resolve frame context from acquisition defaults and overrides."""
    context = deepcopy(base_context)
    matched = False
    changed_keys: set[str] = set()
    for override in normalized_overrides:
        if not override_applies_to_frame(override, frame_index):
            continue
        changes = override.get("changes")
        if not isinstance(changes, dict):
            continue

        changed_keys.update(flatten_payload_dict(changes).keys())
        patch = unflatten_payload_dict(changes)
        context = _merge_inherit(context, patch)
        matched = True
    return (context, matched, changed_keys)


def _field_source_for_key(
    key: str,
    *,
    acquisition_defaults_flat: dict[str, Any],
    node_source_by_key: dict[str, MetadataFieldSource],
    legacy_session_defaults_flat: dict[str, Any],
    legacy_campaign_defaults_flat: dict[str, Any],
    override_keys: set[str],
    resolution_by_key: dict[str, EbusCanonicalFieldResolution],
) -> str:
    """Return acquisition-metadata provenance for one canonical field key."""

    def _layer_has_value(source: dict[str, Any]) -> bool:
        return key in source and source.get(key) is not None

    if key in override_keys:
        return "frame_override"
    resolution = resolution_by_key.get(key)
    if resolution is not None and resolution.snapshot_present:
        return resolution.provenance
    if _layer_has_value(acquisition_defaults_flat):
        return "acquisition_default"
    node_source = node_source_by_key.get(key)
    if node_source is not None and node_source.value is not None:
        return node_source.provenance
    if _layer_has_value(legacy_session_defaults_flat):
        return "session_default"
    if _layer_has_value(legacy_campaign_defaults_flat):
        return "campaign_default"
    return "none"


def _campaign_defaults_payload(payload: Any) -> dict[str, Any]:
    """Build one campaign-level defaults dictionary from campaign payload blocks."""
    if not isinstance(payload, dict):
        return {}
    merged: dict[str, Any] = {}
    instrument_defaults = payload.get("instrument_defaults")
    if isinstance(instrument_defaults, dict):
        merged = _merge_inherit(
            merged,
            {"instrument": deepcopy(instrument_defaults)},
        )
    campaign_defaults = payload.get("campaign_defaults")
    if isinstance(campaign_defaults, dict):
        merged = _merge_inherit(merged, campaign_defaults)
    return merged


def _load_acquisition_datacard(
    acq_root: Path,
    *,
    metadata_boundary_root: str | Path | None = None,
) -> Optional[_AcquisitionDatacard]:
    """Load and cache resolved acquisition/session/campaign metadata."""
    boundary_root = _normalize_metadata_boundary_root(
        acq_root,
        metadata_boundary_root,
    )
    key = (acq_root.resolve(), boundary_root)
    if key in _ACQ_CARD_CACHE:
        return _ACQ_CARD_CACHE[key]

    acquisition_datacard_path = resolve_acquisition_datacard_path(acq_root)
    acquisition_payload = read_json_dict(acquisition_datacard_path)
    session_root = _root_within_metadata_boundary(
        find_session_root(acq_root),
        boundary_root,
    )
    session_datacard_path = (
        resolve_session_datacard_path(session_root)
        if session_root is not None
        else None
    )
    session_payload = (
        read_json_dict(session_datacard_path)
        if session_datacard_path is not None
        else None
    )
    campaign_root = _root_within_metadata_boundary(
        find_campaign_root(acq_root),
        boundary_root,
    )
    campaign_datacard_path = (
        resolve_campaign_datacard_path(campaign_root)
        if campaign_root is not None
        else None
    )
    campaign_payload = (
        read_json_dict(campaign_datacard_path)
        if campaign_datacard_path is not None
        else None
    )

    campaign_defaults = _campaign_defaults_payload(campaign_payload)
    session_defaults = {}
    if isinstance(session_payload, dict):
        raw_session_defaults = session_payload.get("session_defaults")
        if isinstance(raw_session_defaults, dict):
            session_defaults = deepcopy(raw_session_defaults)
    acquisition_defaults = {}
    if isinstance(acquisition_payload, dict):
        raw_defaults = acquisition_payload.get("defaults")
        if isinstance(raw_defaults, dict):
            acquisition_defaults = deepcopy(raw_defaults)

    node_resolution = resolve_path_node_metadata(
        acq_root,
        exclude_paths=(acq_root,),
        boundary_root=boundary_root,
    )

    base_context: dict[str, Any] = {}
    # LEGACY_COMPAT[legacy_campaign_session_datacards]: Preserve campaign/session datacard defaults as fallback until nodecards fully replace higher-level authored metadata. Remove after: workflow metadata inspector ships nodecard editing plus a migration away from campaign/session datacard defaults.
    base_context = _merge_inherit(base_context, campaign_defaults)
    # LEGACY_COMPAT[legacy_campaign_session_datacards]: Preserve campaign/session datacard defaults as fallback until nodecards fully replace higher-level authored metadata. Remove after: workflow metadata inspector ships nodecard editing plus a migration away from campaign/session datacard defaults.
    base_context = _merge_inherit(base_context, session_defaults)
    base_context = _merge_inherit(base_context, node_resolution.effective_metadata)
    base_context = _merge_inherit(base_context, acquisition_defaults)
    ebus_resolutions = resolve_ebus_canonical_fields(acq_root, acquisition_payload or {})
    base_context = apply_ebus_canonical_baseline(base_context, ebus_resolutions)
    node_metadata_flat = dict(node_resolution.flat_metadata)
    legacy_campaign_defaults_flat = flatten_payload_dict(campaign_defaults)
    legacy_session_defaults_flat = flatten_payload_dict(session_defaults)
    acquisition_defaults_flat = flatten_payload_dict(acquisition_defaults)

    paths_block = acquisition_payload.get("paths") if isinstance(acquisition_payload, dict) else None
    frames_dir_name = "frames"
    if isinstance(paths_block, dict):
        raw_frames_dir = paths_block.get("frames_dir")
        if isinstance(raw_frames_dir, str) and raw_frames_dir.strip():
            frames_dir_name = raw_frames_dir
    resolution = resolve_frame_index_map(acq_root.joinpath(frames_dir_name))

    overrides_raw = (
        acquisition_payload.get("overrides")
        if isinstance(acquisition_payload, dict)
        else None
    )
    overrides = overrides_raw if isinstance(overrides_raw, list) else []
    normalized, index_base = normalize_override_selectors(
        overrides,
        resolution.indices,
    )
    datacard = _AcquisitionDatacard(
        base_context=base_context,
        node_metadata_flat=node_metadata_flat,
        node_source_by_key=dict(node_resolution.field_sources),
        legacy_campaign_defaults_flat=legacy_campaign_defaults_flat,
        legacy_session_defaults_flat=legacy_session_defaults_flat,
        acquisition_defaults_flat=acquisition_defaults_flat,
        normalized_overrides=tuple(normalized),
        override_index_base=index_base,
        frame_index_by_name=resolution.index_by_name,
        frame_index_mode=resolution.mode,
        ebus_resolutions=ebus_resolutions,
        ebus_resolution_by_key=ebus_resolutions.by_key(),
        json_metadata_available=any(
            payload is not None
            for payload in (
                acquisition_payload,
                session_payload,
                campaign_payload,
            )
        )
        or node_resolution.has_metadata,
        acquisition_datacard_path=acquisition_datacard_path,
        session_datacard_path=session_datacard_path,
        campaign_datacard_path=campaign_datacard_path,
        frames_dir_path=acq_root.joinpath(frames_dir_name),
        ebus_attached=ebus_resolutions.snapshot_loaded,
    )
    _ACQ_CARD_CACHE[key] = datacard
    return datacard


def _nested_get(root: Any, path: tuple[str, ...]) -> Any:
    """Get nested value from dictionary-like payload."""
    current = root
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _as_finite_float(value: Any) -> Optional[float]:
    """Convert value to finite float, returning None on failure."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, str):
        try:
            numeric = float(value.strip())
        except Exception:
            return None
        return numeric if math.isfinite(numeric) else None
    return None


def extract_path_metadata(
    path: str,
    metadata_source: str = "path",
    *,
    metadata_boundary_root: str | Path | None = None,
) -> dict[str, object]:
    """Extract structured metadata fields from a file path.

    Parameters
    ----------
    path : str
        Absolute or relative TIFF file path.
    metadata_source : str, optional
        Requested metadata source. Supported values are ``"path"`` and
        ``"json"``.

    Returns
    -------
    dict[str, object]
        Parsed metadata values suitable for grouping and analysis.
    """
    source_mode = (
        metadata_source if metadata_source in {"path", "json"} else "path"
    )
    p = Path(path)
    parent = p.parent.name
    grandparent = p.parent.parent.name
    stem = p.stem

    values: dict[str, object] = {
        "filename": p.name,
        "parent_folder": parent,
        "grandparent_folder": grandparent,
        "stem": stem,
        "metadata_source_selected": source_mode,
    }

    frame_info = parse_frame_name(stem)
    raw_frame_index = frame_info.frame_index
    if raw_frame_index is not None:
        values["frame_index_raw"] = int(raw_frame_index)
        values["frame_index"] = int(raw_frame_index)
        values["frame_naming"] = frame_info.naming
    if frame_info.ebus_timestamp_hex is not None:
        values["ebus_timestamp_hex"] = frame_info.ebus_timestamp_hex
    if frame_info.ebus_timestamp_ms is not None:
        values["ebus_timestamp_ms"] = int(frame_info.ebus_timestamp_ms)

    path_iris_position = (
        _find_iris_position(parent)
        or _find_iris_position(grandparent)
        or _find_iris_position(stem)
    )
    path_exposure_ms = _find_exposure_ms(stem) or _find_exposure_ms(parent)

    if path_iris_position is not None:
        values["iris_position_path"] = path_iris_position
    if path_exposure_ms is not None:
        values["exposure_ms_path"] = path_exposure_ms

    datacard_iris_position: Optional[float] = None
    datacard_exposure_ms: Optional[float] = None
    datacard_iris_source = "none"
    datacard_exposure_source = "none"

    acq_root = find_acquisition_root(p, allow_name_only=True)
    boundary_root = _normalize_metadata_boundary_root(
        p,
        metadata_boundary_root,
    )
    acq_root = _root_within_metadata_boundary(acq_root, boundary_root)
    values["json_metadata_available"] = False
    if acq_root is not None:
        values["acquisition_root"] = str(acq_root)
        datacard_path = resolve_acquisition_datacard_path(acq_root)
        values["acquisition_datacard_path"] = str(datacard_path)
        card = _load_acquisition_datacard(
            acq_root,
            metadata_boundary_root=boundary_root,
        )
        if card is not None:
            values["json_metadata_available"] = bool(card.json_metadata_available)
            if card.session_datacard_path is not None:
                values["session_datacard_path"] = str(card.session_datacard_path)
            if card.campaign_datacard_path is not None:
                values["campaign_datacard_path"] = str(card.campaign_datacard_path)
            values["override_index_base_detected"] = int(
                card.override_index_base,
            )
            values["frame_index_mode"] = card.frame_index_mode
            effective_frame_index = card.frame_index_by_name.get(p.name)
            frames_dir_matches = (
                card.frames_dir_path is not None
                and p.parent.resolve() == card.frames_dir_path.resolve()
            )
            if (
                effective_frame_index is None
                and raw_frame_index is not None
                and frames_dir_matches
            ):
                effective_frame_index = int(raw_frame_index)
            if effective_frame_index is not None:
                values["frame_index"] = int(effective_frame_index)
                (
                    resolved_context,
                    override_matched,
                    override_keys,
                ) = _apply_overrides(
                    card.base_context,
                    card.normalized_overrides,
                    int(effective_frame_index),
                )
                values["frame_override_matched"] = bool(override_matched)
                values["frame_link_mode"] = (
                    "frame_index"
                    if override_matched
                    else "frame_index_no_override"
                )
            else:
                values["frame_link_mode"] = "path_only"
                values["frame_override_matched"] = False
                resolved_context = deepcopy(card.base_context)
                override_keys = set()

            for key in card.ebus_resolution_by_key:
                values[f"{key}_source"] = _field_source_for_key(
                    key,
                    acquisition_defaults_flat=card.acquisition_defaults_flat,
                    node_source_by_key=card.node_source_by_key,
                    legacy_session_defaults_flat=card.legacy_session_defaults_flat,
                    legacy_campaign_defaults_flat=card.legacy_campaign_defaults_flat,
                    override_keys=override_keys,
                    resolution_by_key=card.ebus_resolution_by_key,
                )

            camera_settings = _nested_get(
                resolved_context,
                ("camera_settings",),
            )
            if isinstance(camera_settings, dict):
                for key, raw_value in camera_settings.items():
                    if not isinstance(key, str):
                        continue
                    full_key = f"camera_settings.{key}"
                    values[full_key] = raw_value
                    values[f"{full_key}_label"] = (
                        label_for_camera_setting_key(full_key)
                    )

            exposure_us = _as_finite_float(
                _nested_get(
                    resolved_context,
                    ("camera_settings", "exposure_us"),
                ),
            )
            datacard_exposure_source = _field_source_for_key(
                "camera_settings.exposure_us",
                acquisition_defaults_flat=card.acquisition_defaults_flat,
                node_source_by_key=card.node_source_by_key,
                legacy_session_defaults_flat=card.legacy_session_defaults_flat,
                legacy_campaign_defaults_flat=card.legacy_campaign_defaults_flat,
                override_keys=override_keys,
                resolution_by_key=card.ebus_resolution_by_key,
            )
            values["camera_settings.exposure_us_source"] = (
                datacard_exposure_source
            )
            if exposure_us is not None:
                datacard_exposure_ms = float(exposure_us / 1000.0)
                values["exposure_ms_datacard"] = datacard_exposure_ms

            iris_datacard = _as_finite_float(
                _nested_get(
                    resolved_context,
                    ("instrument", "optics", "iris", "position"),
                ),
            )
            datacard_iris_source = _field_source_for_key(
                "instrument.optics.iris.position",
                acquisition_defaults_flat=card.acquisition_defaults_flat,
                node_source_by_key=card.node_source_by_key,
                legacy_session_defaults_flat=card.legacy_session_defaults_flat,
                legacy_campaign_defaults_flat=card.legacy_campaign_defaults_flat,
                override_keys=override_keys,
                resolution_by_key=card.ebus_resolution_by_key,
            )
            values["instrument.optics.iris.position_source"] = (
                datacard_iris_source
            )
            if iris_datacard is not None:
                datacard_iris_position = float(iris_datacard)
                values["iris_position_datacard"] = datacard_iris_position

    _apply_raw_metadata_fallbacks(values, p)

    final_iris: Optional[float]
    final_exposure_ms: Optional[float]
    iris_source: str
    exposure_source: str
    if source_mode == "json":
        if datacard_iris_position is not None:
            final_iris = datacard_iris_position
            iris_source = datacard_iris_source
        elif path_iris_position is not None:
            final_iris = path_iris_position
            iris_source = "path_fallback"
        else:
            final_iris = None
            iris_source = "none"

        if datacard_exposure_ms is not None:
            final_exposure_ms = datacard_exposure_ms
            exposure_source = datacard_exposure_source
        elif path_exposure_ms is not None:
            final_exposure_ms = path_exposure_ms
            exposure_source = "path_fallback"
        else:
            final_exposure_ms = None
            exposure_source = "none"
    else:
        final_iris = path_iris_position
        final_exposure_ms = path_exposure_ms
        iris_source = "path" if path_iris_position is not None else "none"
        exposure_source = "path" if path_exposure_ms is not None else "none"

    values["iris_source"] = iris_source
    values["exposure_source"] = exposure_source

    if final_iris is not None:
        values["iris_position"] = final_iris
        values["iris_label"] = f"pos_{final_iris:g}"

    if final_exposure_ms is not None:
        values["exposure_ms"] = final_exposure_ms

    return values

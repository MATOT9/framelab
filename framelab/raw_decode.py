"""RAW decode spec models and shared resolution helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .metrics_cache import build_file_metric_identity, FileMetricIdentity
from .payload_utils import get_dot_path


SUPPORTED_MONO_RAW_PIXEL_FORMATS = (
    "mono8",
    "mono12_lsb",
    "mono12_msb",
    "mono12p",
    "mono16",
)

_RAW_REQUIRED_FIELD_KEYS = {
    "pixel_format": "camera_settings.pixel_format",
    "width": "camera_settings.resolution_x",
    "height": "camera_settings.resolution_y",
}
_RAW_OPTIONAL_FIELD_KEYS = {
    "stride_bytes": "camera_settings.stride_bytes",
    "offset_bytes": "camera_settings.offset_bytes",
}


class RawDecodeSpecError(ValueError):
    """Raised when a RAW decode specification cannot be resolved or validated."""


@dataclass(frozen=True, slots=True)
class RawDecodeSpec:
    """Validated decode inputs for one monochrome RAW file."""

    source_kind: str
    pixel_format: str
    width: int
    height: int
    stride_bytes: int | None = None
    offset_bytes: int = 0


@dataclass(frozen=True, slots=True)
class RawDecodeResolverContext:
    """Shared RAW metadata inputs reused across scan, preview, and worker paths."""

    path_metadata_by_path: Mapping[str, Mapping[str, object]] | None = None
    scope_metadata: Mapping[str, object] | None = None
    manual_overrides: Mapping[str, object] | None = None
    metadata_boundary_root: str | Path | None = None


def _lookup_metadata_value(
    metadata: Mapping[str, object] | None,
    key: str,
) -> object | None:
    if not metadata:
        return None
    if key in metadata:
        return metadata.get(key)
    if "." not in key:
        return metadata.get(key)
    try:
        return get_dot_path(dict(metadata), key)
    except Exception:
        return None


def _first_non_empty_string(*values: object | None) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _first_positive_int(*values: object | None) -> int | None:
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            number = int(value)
        except Exception:
            continue
        if number > 0:
            return int(number)
    return None


def _first_non_negative_int(*values: object | None) -> int | None:
    for value in values:
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            continue
        try:
            number = int(value)
        except Exception:
            continue
        if number >= 0:
            return int(number)
    return None


def validate_raw_decode_spec(spec: RawDecodeSpec) -> RawDecodeSpec:
    """Validate one RAW decode spec and return a normalized copy."""

    pixel_format = str(spec.pixel_format or "").strip().lower()
    if pixel_format not in SUPPORTED_MONO_RAW_PIXEL_FORMATS:
        supported = ", ".join(SUPPORTED_MONO_RAW_PIXEL_FORMATS)
        raise RawDecodeSpecError(
            f"Unsupported RAW pixel format '{spec.pixel_format}'. "
            f"Supported monochrome formats: {supported}",
        )
    width = int(spec.width)
    height = int(spec.height)
    if width <= 0:
        raise RawDecodeSpecError("RAW decode width must be greater than 0")
    if height <= 0:
        raise RawDecodeSpecError("RAW decode height must be greater than 0")
    stride_bytes = (
        None
        if spec.stride_bytes in {None, 0}
        else int(spec.stride_bytes)
    )
    if stride_bytes is not None and stride_bytes <= 0:
        raise RawDecodeSpecError("RAW decode stride_bytes must be positive when provided")
    offset_bytes = int(spec.offset_bytes)
    if offset_bytes < 0:
        raise RawDecodeSpecError("RAW decode offset_bytes must be non-negative")
    return RawDecodeSpec(
        source_kind="raw",
        pixel_format=pixel_format,
        width=width,
        height=height,
        stride_bytes=stride_bytes,
        offset_bytes=offset_bytes,
    )


def raw_decode_spec_fingerprint(spec: RawDecodeSpec) -> str:
    """Return a stable cache fingerprint for one validated RAW decode spec."""

    validated = validate_raw_decode_spec(spec)
    return (
        f"{validated.pixel_format}|{validated.width}x{validated.height}|"
        f"stride={validated.stride_bytes or 0}|offset={validated.offset_bytes}"
    )


def _structured_path_metadata(
    path: Path,
    *,
    context: RawDecodeResolverContext | None,
) -> Mapping[str, object]:
    from .metadata import extract_path_metadata

    mapping = context.path_metadata_by_path if context is not None else None
    resolved = str(path.resolve())
    cached = mapping.get(resolved) if mapping is not None else None
    if isinstance(cached, Mapping) and cached.get("metadata_source_selected") == "json":
        return cached
    boundary_root = None if context is None else context.metadata_boundary_root
    return extract_path_metadata(
        resolved,
        metadata_source="json",
        metadata_boundary_root=boundary_root,
    )


def resolve_raw_decode_spec(
    path: str | Path,
    *,
    context: RawDecodeResolverContext | None = None,
) -> RawDecodeSpec:
    """Resolve one RAW decode spec using the shared precedence model."""

    candidate = Path(path).expanduser().resolve()
    file_metadata = _structured_path_metadata(candidate, context=context)
    scope_metadata = context.scope_metadata if context is not None else None
    manual_overrides = context.manual_overrides if context is not None else None

    pixel_format = _first_non_empty_string(
        _lookup_metadata_value(file_metadata, _RAW_REQUIRED_FIELD_KEYS["pixel_format"]),
        _lookup_metadata_value(scope_metadata, _RAW_REQUIRED_FIELD_KEYS["pixel_format"]),
        _lookup_metadata_value(manual_overrides, _RAW_REQUIRED_FIELD_KEYS["pixel_format"]),
    )
    width = _first_positive_int(
        _lookup_metadata_value(file_metadata, _RAW_REQUIRED_FIELD_KEYS["width"]),
        _lookup_metadata_value(scope_metadata, _RAW_REQUIRED_FIELD_KEYS["width"]),
        _lookup_metadata_value(manual_overrides, _RAW_REQUIRED_FIELD_KEYS["width"]),
    )
    height = _first_positive_int(
        _lookup_metadata_value(file_metadata, _RAW_REQUIRED_FIELD_KEYS["height"]),
        _lookup_metadata_value(scope_metadata, _RAW_REQUIRED_FIELD_KEYS["height"]),
        _lookup_metadata_value(manual_overrides, _RAW_REQUIRED_FIELD_KEYS["height"]),
    )
    stride_bytes = _first_non_negative_int(
        _lookup_metadata_value(file_metadata, _RAW_OPTIONAL_FIELD_KEYS["stride_bytes"]),
        _lookup_metadata_value(scope_metadata, _RAW_OPTIONAL_FIELD_KEYS["stride_bytes"]),
        _lookup_metadata_value(manual_overrides, _RAW_OPTIONAL_FIELD_KEYS["stride_bytes"]),
    )
    offset_bytes = _first_non_negative_int(
        _lookup_metadata_value(file_metadata, _RAW_OPTIONAL_FIELD_KEYS["offset_bytes"]),
        _lookup_metadata_value(scope_metadata, _RAW_OPTIONAL_FIELD_KEYS["offset_bytes"]),
        _lookup_metadata_value(manual_overrides, _RAW_OPTIONAL_FIELD_KEYS["offset_bytes"]),
    )

    missing: list[str] = []
    if pixel_format is None:
        missing.append("pixel_format")
    if width is None:
        missing.append("width")
    if height is None:
        missing.append("height")
    if missing:
        raise RawDecodeSpecError(
            "Missing RAW decode spec fields: " + ", ".join(missing),
        )

    return validate_raw_decode_spec(
        RawDecodeSpec(
            source_kind="raw",
            pixel_format=pixel_format,
            width=int(width),
            height=int(height),
            stride_bytes=stride_bytes,
            offset_bytes=0 if offset_bytes is None else int(offset_bytes),
        ),
    )


def build_image_metric_identity(
    path: str | Path,
    *,
    dataset_root: str | Path | None = None,
    workspace_root: str | Path | None = None,
    raw_resolver_context: RawDecodeResolverContext | None = None,
) -> FileMetricIdentity:
    """Build one cache identity that is sensitive to RAW decode spec changes."""

    candidate = Path(path).expanduser().resolve()
    suffix = candidate.suffix.lower()
    extra_fingerprint = None
    if suffix == ".raw":
        extra_fingerprint = {
            "source_kind": "raw",
            "decode_spec": raw_decode_spec_fingerprint(
                resolve_raw_decode_spec(candidate, context=raw_resolver_context),
            ),
        }
    return build_file_metric_identity(
        candidate,
        dataset_root=dataset_root,
        workspace_root=workspace_root,
        extra_fingerprint=extra_fingerprint,
    )

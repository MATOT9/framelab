"""Shared image I/O helpers for supported dataset formats."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from .native import backend as native_backend
from .raw_decode import (
    RawDecodeResolverContext,
    RawDecodeSpecError,
    SUPPORTED_RAW_IMAGE_SUFFIXES,
    is_raw_image_path,
)

if TYPE_CHECKING:
    import numpy as np
    from .raw_decode import RawDecodeSpec


SUPPORTED_IMAGE_SUFFIXES = (".tif", ".tiff", *SUPPORTED_RAW_IMAGE_SUFFIXES)
_TIFF_SUFFIXES = (".tif", ".tiff")
_SUFFIX_READER: dict[str, Callable[[Path], object]] = {}


class ImageIoError(Exception):
    """Base error raised for shared image-loading failures."""


class UnsupportedImageFormatError(ImageIoError):
    """Raised when a file extension is not supported by the current app."""


class InvalidImageError(ImageIoError):
    """Raised when an image cannot be read or coerced into the expected shape."""


def _read_tiff(path: Path) -> object:
    """Read one TIFF image array from disk."""
    import numpy as np
    import tifffile

    return np.asarray(tifffile.imread(str(path)))


for _suffix in _TIFF_SUFFIXES:
    _SUFFIX_READER[_suffix] = _read_tiff


def supported_suffixes() -> tuple[str, ...]:
    """Return supported image suffixes in canonical lowercase form."""
    return SUPPORTED_IMAGE_SUFFIXES


def source_kind_for_path(path: str | Path) -> str:
    """Return the normalized source kind for one supported image path."""

    if is_raw_image_path(path):
        return "raw"
    suffix = Path(path).suffix.lower()
    if suffix in {".tif", ".tiff"}:
        return "tiff"
    return "unknown"


def is_supported_image(path: str | Path) -> bool:
    """Return whether the given path is supported by the shared image loader."""
    return Path(path).suffix.lower() in SUPPORTED_IMAGE_SUFFIXES


def read_image(
    path: str | Path,
    *,
    raw_spec_resolver: Callable[..., RawDecodeSpec] | None = None,
    raw_resolver_context: RawDecodeResolverContext | None = None,
) -> object:
    """Read one supported image file from disk."""
    resolved = Path(path)
    if is_raw_image_path(resolved):
        if raw_spec_resolver is None:
            raise InvalidImageError(
                "RAW decode spec resolver required for .bin/.raw image loading",
            )
        try:
            spec = raw_spec_resolver(resolved, context=raw_resolver_context)
            return native_backend.decode_raw_file(str(resolved), spec=spec)
        except (RawDecodeSpecError, ValueError) as exc:
            raise InvalidImageError(str(exc)) from exc
        except ImageIoError:
            raise
        except Exception as exc:
            raise InvalidImageError(str(exc)) from exc

    suffix = resolved.suffix.lower()
    reader = _SUFFIX_READER.get(suffix)
    if reader is None:
        supported = ", ".join(SUPPORTED_IMAGE_SUFFIXES)
        raise UnsupportedImageFormatError(
            f"Unsupported image format '{resolved.suffix or '<none>'}'. "
            f"Supported suffixes: {supported}",
        )
    try:
        return reader(resolved)
    except ImageIoError:
        raise
    except Exception as exc:
        raise InvalidImageError(str(exc)) from exc


def read_2d_image(
    path: str | Path,
    *,
    raw_spec_resolver: Callable[..., RawDecodeSpec] | None = None,
    raw_resolver_context: RawDecodeResolverContext | None = None,
) -> np.ndarray:
    """Read one supported image file and coerce it to a single 2D frame."""
    import numpy as np

    arr = np.asarray(
        read_image(
            path,
            raw_spec_resolver=raw_spec_resolver,
            raw_resolver_context=raw_resolver_context,
        ),
    )
    arr = np.squeeze(arr)
    while arr.ndim > 2:
        arr = arr[0]
    if arr.ndim != 2:
        raise InvalidImageError(f"Expected 2D image, got shape {arr.shape}")
    return arr

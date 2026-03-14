"""Shared image I/O helpers for supported dataset formats."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    import numpy as np


SUPPORTED_IMAGE_SUFFIXES = (".tif", ".tiff")
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


for _suffix in SUPPORTED_IMAGE_SUFFIXES:
    _SUFFIX_READER[_suffix] = _read_tiff


def supported_suffixes() -> tuple[str, ...]:
    """Return supported image suffixes in canonical lowercase form."""
    return SUPPORTED_IMAGE_SUFFIXES


def is_supported_image(path: str | Path) -> bool:
    """Return whether the given path is supported by the shared image loader."""
    return Path(path).suffix.lower() in _SUFFIX_READER


def read_image(path: str | Path) -> object:
    """Read one supported image file from disk."""
    resolved = Path(path)
    reader = _SUFFIX_READER.get(resolved.suffix.lower())
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


def read_2d_image(path: str | Path) -> np.ndarray:
    """Read one supported image file and coerce it to a single 2D frame."""
    import numpy as np

    arr = np.asarray(read_image(path))
    arr = np.squeeze(arr)
    while arr.ndim > 2:
        arr = arr[0]
    if arr.ndim != 2:
        raise InvalidImageError(f"Expected 2D image, got shape {arr.shape}")
    return arr

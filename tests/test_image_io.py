from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile

from framelab.image_io import (
    InvalidImageError,
    UnsupportedImageFormatError,
    is_supported_image,
    read_2d_image,
    read_image,
    supported_suffixes,
)


pytestmark = [pytest.mark.fast, pytest.mark.core]


def _write_tiff(root: Path, name: str, array: np.ndarray) -> Path:
    path = root / name
    tifffile.imwrite(str(path), array)
    return path


def test_supported_suffixes_and_detection_are_canonical() -> None:
    assert supported_suffixes() == (".tif", ".tiff")
    assert is_supported_image("frame.TIF")
    assert is_supported_image(Path("frame.tiff"))
    assert not is_supported_image("frame.png")


def test_read_image_rejects_unsupported_suffix() -> None:
    with pytest.raises(UnsupportedImageFormatError):
        read_image("frame.png")


def test_read_image_wraps_invalid_tiff_payload(tmp_path: Path) -> None:
    path = tmp_path / "broken.tif"
    path.write_text("not a tiff", encoding="utf-8")
    with pytest.raises(InvalidImageError):
        read_image(path)


def test_read_2d_image_preserves_2d_arrays(tmp_path: Path) -> None:
    expected = np.arange(12, dtype=np.uint16).reshape(3, 4)
    path = _write_tiff(tmp_path, "plain.TIF", expected)
    actual = read_2d_image(path)
    np.testing.assert_array_equal(actual, expected)


def test_read_2d_image_squeezes_singleton_axes(tmp_path: Path) -> None:
    source = np.arange(12, dtype=np.uint16).reshape(1, 3, 4)
    expected = source.reshape(3, 4)
    path = _write_tiff(tmp_path, "stack.tif", source)
    actual = read_2d_image(path)
    np.testing.assert_array_equal(actual, expected)


def test_read_2d_image_selects_first_plane_until_2d(tmp_path: Path) -> None:
    source = np.arange(24, dtype=np.uint16).reshape(2, 3, 4)
    expected = source[0]
    path = _write_tiff(tmp_path, "cube.tiff", source)
    actual = read_2d_image(path)
    np.testing.assert_array_equal(actual, expected)


def test_read_2d_image_rejects_non_2d_result(tmp_path: Path) -> None:
    source = np.arange(5, dtype=np.uint16)
    path = _write_tiff(tmp_path, "line.tif", source)
    with pytest.raises(InvalidImageError):
        read_2d_image(path)

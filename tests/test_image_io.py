from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

import numpy as np
import tifffile

from framelab.image_io import (
    InvalidImageError,
    UnsupportedImageFormatError,
    is_supported_image,
    read_2d_image,
    read_image,
    supported_suffixes,
)


class ImageIoTests(unittest.TestCase):
    def _write_tiff(self, root: Path, name: str, array: np.ndarray) -> Path:
        path = root / name
        tifffile.imwrite(str(path), array)
        return path

    def test_supported_suffixes_and_detection_are_canonical(self) -> None:
        self.assertEqual(supported_suffixes(), (".tif", ".tiff"))
        self.assertTrue(is_supported_image("frame.TIF"))
        self.assertTrue(is_supported_image(Path("frame.tiff")))
        self.assertFalse(is_supported_image("frame.png"))

    def test_read_image_rejects_unsupported_suffix(self) -> None:
        with self.assertRaises(UnsupportedImageFormatError):
            read_image("frame.png")

    def test_read_image_wraps_invalid_tiff_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "broken.tif"
            path.write_text("not a tiff", encoding="utf-8")
            with self.assertRaises(InvalidImageError):
                read_image(path)

    def test_read_2d_image_preserves_2d_arrays(self) -> None:
        expected = np.arange(12, dtype=np.uint16).reshape(3, 4)
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = self._write_tiff(Path(tmp_dir), "plain.TIF", expected)
            actual = read_2d_image(path)
        np.testing.assert_array_equal(actual, expected)

    def test_read_2d_image_squeezes_singleton_axes(self) -> None:
        source = np.arange(12, dtype=np.uint16).reshape(1, 3, 4)
        expected = source.reshape(3, 4)
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = self._write_tiff(Path(tmp_dir), "stack.tif", source)
            actual = read_2d_image(path)
        np.testing.assert_array_equal(actual, expected)

    def test_read_2d_image_selects_first_plane_until_2d(self) -> None:
        source = np.arange(24, dtype=np.uint16).reshape(2, 3, 4)
        expected = source[0]
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = self._write_tiff(Path(tmp_dir), "cube.tiff", source)
            actual = read_2d_image(path)
        np.testing.assert_array_equal(actual, expected)

    def test_read_2d_image_rejects_non_2d_result(self) -> None:
        source = np.arange(5, dtype=np.uint16)
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = self._write_tiff(Path(tmp_dir), "line.tif", source)
            with self.assertRaises(InvalidImageError):
                read_2d_image(path)


if __name__ == "__main__":
    unittest.main()

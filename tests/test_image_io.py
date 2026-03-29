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
    source_kind_for_path,
    supported_suffixes,
)
from framelab.raw_decode import (
    RawDecodeResolverContext,
    RawDecodeSpec,
    RawDecodeSpecError,
)


pytestmark = [pytest.mark.fast, pytest.mark.core]


def _write_tiff(root: Path, name: str, array: np.ndarray) -> Path:
    path = root / name
    tifffile.imwrite(str(path), array)
    return path


def test_supported_suffixes_and_detection_are_canonical() -> None:
    assert supported_suffixes() == (".tif", ".tiff", ".raw")
    assert is_supported_image("frame.TIF")
    assert is_supported_image(Path("frame.tiff"))
    assert is_supported_image("frame.RAW")
    assert not is_supported_image("frame.png")
    assert source_kind_for_path("frame.raw") == "raw"
    assert source_kind_for_path("frame.tif") == "tiff"


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


def test_read_image_requires_shared_raw_resolver(tmp_path: Path) -> None:
    path = tmp_path / "frame.raw"
    path.write_bytes(b"\x00" * 8)

    with pytest.raises(InvalidImageError, match="RAW decode spec resolver required"):
        read_image(path)


def test_read_image_routes_raw_through_shared_resolver_and_native_decode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "frame.raw"
    path.write_bytes(b"\x00" * 8)
    context = RawDecodeResolverContext(
        manual_overrides={"camera_settings.offset_bytes": 4},
    )
    expected = np.arange(6, dtype=np.uint16).reshape(2, 3)
    calls: dict[str, object] = {}
    spec = RawDecodeSpec(
        source_kind="raw",
        pixel_format="mono8",
        width=3,
        height=2,
        stride_bytes=None,
        offset_bytes=4,
    )

    def _fake_resolver(candidate, *, context=None):
        calls["resolver_path"] = str(candidate)
        calls["resolver_context"] = context
        return spec

    def _fake_decode(candidate, *, spec=None, **_kwargs):
        calls["decode_path"] = str(candidate)
        calls["decode_spec"] = spec
        return expected

    monkeypatch.setattr(
        "framelab.image_io.native_backend.decode_raw_file",
        _fake_decode,
    )

    actual = read_2d_image(
        path,
        raw_spec_resolver=_fake_resolver,
        raw_resolver_context=context,
    )

    assert calls["resolver_path"] == str(path)
    assert calls["resolver_context"] == context
    assert calls["decode_path"] == str(path)
    assert calls["decode_spec"] == spec
    np.testing.assert_array_equal(actual, expected)


def test_read_image_wraps_raw_spec_errors(tmp_path: Path) -> None:
    path = tmp_path / "broken.raw"
    path.write_bytes(b"\x00" * 4)

    def _bad_resolver(candidate, *, context=None):
        _ = candidate
        _ = context
        raise RawDecodeSpecError("Missing RAW decode spec fields: width")

    with pytest.raises(InvalidImageError, match="Missing RAW decode spec fields"):
        read_image(path, raw_spec_resolver=_bad_resolver)

from __future__ import annotations

from pathlib import Path

import pytest

import framelab.raw_decode as raw_decode
from framelab.raw_decode import (
    RawDecodeResolverContext,
    RawDecodeSpec,
    RawDecodeSpecError,
    build_image_metric_identity,
    normalize_raw_pixel_format,
    raw_decode_spec_fingerprint,
    resolve_raw_decode_spec,
    validate_raw_decode_spec,
)


pytestmark = [pytest.mark.fast, pytest.mark.core]


def _write_snapshot(path: Path, parameters: dict[str, object]) -> None:
    lines = [
        '<?xml version="1.0"?>',
        '<puregevpersistencefile version="1.0">',
        '  <device name="" version="1.0">',
        "    <device>",
    ]
    for name, value in parameters.items():
        lines.append(f'      <parameter name="{name}">{value}</parameter>')
    lines.extend(
        [
            "    </device>",
            "  </device>",
            "</puregevpersistencefile>",
        ],
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_validate_raw_decode_spec_normalizes_supported_values() -> None:
    spec = validate_raw_decode_spec(
        RawDecodeSpec(
            source_kind="raw",
            pixel_format=" Mono12Packed ",
            width=640,
            height=512,
            stride_bytes=0,
            offset_bytes=0,
        ),
    )

    assert spec.pixel_format == "mono12packed"
    assert spec.width == 640
    assert spec.height == 512
    assert spec.stride_bytes is None
    assert spec.offset_bytes == 0
    assert raw_decode_spec_fingerprint(spec) == "mono12packed|640x512|stride=0|offset=0"


def test_normalize_raw_pixel_format_supports_standard_aliases() -> None:
    assert normalize_raw_pixel_format("Mono10") == "mono10_msb"
    assert normalize_raw_pixel_format("mono10lsb") == "mono10_lsb"
    assert normalize_raw_pixel_format("Mono10Packed") == "mono10packed"
    assert normalize_raw_pixel_format("Mono12") == "mono12_msb"
    assert normalize_raw_pixel_format("Mono12Packed") == "mono12packed"


def test_validate_raw_decode_spec_rejects_invalid_fields() -> None:
    with pytest.raises(RawDecodeSpecError, match="Unsupported RAW pixel format"):
        validate_raw_decode_spec(
            RawDecodeSpec(
                source_kind="raw",
                pixel_format="bayer12",
                width=640,
                height=512,
            ),
        )

    with pytest.raises(RawDecodeSpecError, match="width must be greater than 0"):
        validate_raw_decode_spec(
            RawDecodeSpec(
                source_kind="raw",
                pixel_format="mono8",
                width=0,
                height=10,
            ),
        )


def test_resolve_raw_decode_spec_uses_json_metadata_and_precedence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "frame.bin"
    path.write_bytes(b"\x00" * 16)
    calls: list[dict[str, object]] = []

    def _fake_extract(candidate, *, metadata_source, metadata_boundary_root=None):
        calls.append(
            {
                "path": str(candidate),
                "metadata_source": metadata_source,
                "metadata_boundary_root": metadata_boundary_root,
            },
        )
        return {
            "camera_settings": {
                "pixel_format": "mono16",
                "resolution_x": 320,
            },
        }

    monkeypatch.setattr(raw_decode, "extract_path_metadata", _fake_extract)
    context = RawDecodeResolverContext(
        scope_metadata={
            "camera_settings": {
                "pixel_format": "mono8",
                "resolution_y": 240,
            },
        },
        manual_overrides={
            "camera_settings.pixel_format": "mono12p",
            "camera_settings.resolution_x": 128,
            "camera_settings.resolution_y": 64,
            "camera_settings.offset_bytes": 12,
        },
        metadata_boundary_root=tmp_path,
    )

    spec = resolve_raw_decode_spec(path, context=context)

    assert spec.pixel_format == "mono16"
    assert spec.width == 320
    assert spec.height == 240
    assert spec.offset_bytes == 12
    assert calls == [
        {
            "path": str(path.resolve()),
            "metadata_source": "json",
            "metadata_boundary_root": tmp_path,
        },
    ]


def test_resolve_raw_decode_spec_reuses_cached_json_metadata_without_reresolving(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "cached.bin"
    path.write_bytes(b"\x00" * 16)
    cached_metadata = {
        str(path.resolve()): {
            "metadata_source_selected": "json",
            "camera_settings": {
                "pixel_format": "mono8",
                "resolution_x": 64,
                "resolution_y": 32,
            },
        },
    }
    context = RawDecodeResolverContext(
        path_metadata_by_path=cached_metadata,
        manual_overrides={"camera_settings.offset_bytes": 8},
    )

    monkeypatch.setattr(
        raw_decode,
        "extract_path_metadata",
        lambda *args, **kwargs: pytest.fail("extract_path_metadata should not run"),
    )

    spec = resolve_raw_decode_spec(path, context=context)

    assert spec.pixel_format == "mono8"
    assert spec.width == 64
    assert spec.height == 32
    assert spec.offset_bytes == 8


def test_resolve_raw_decode_spec_falls_back_to_acquisition_snapshot_without_datacard(
    tmp_path: Path,
) -> None:
    acquisition_root = tmp_path / "scene-raw"
    frames_root = acquisition_root / "frames"
    frames_root.mkdir(parents=True, exist_ok=True)
    path = frames_root / "capture.bin"
    path.write_bytes(b"\x00" * 16)
    _write_snapshot(
        acquisition_root / "camera_config.pvcfg",
        {
            "Width": 320,
            "Height": 240,
            "PixelFormat": "Mono12Packed",
        },
    )

    spec = resolve_raw_decode_spec(path)

    assert spec.pixel_format == "mono12packed"
    assert spec.width == 320
    assert spec.height == 240


def test_resolve_raw_decode_spec_falls_back_to_filename_tokens(
    tmp_path: Path,
) -> None:
    path = tmp_path / "00000000_00000000000DA20D_w2848_h2848_pMono12Packed.bin"
    path.write_bytes(b"\x00" * 16)

    spec = resolve_raw_decode_spec(path)

    assert spec.pixel_format == "mono12packed"
    assert spec.width == 2848
    assert spec.height == 2848


def test_build_image_metric_identity_changes_when_raw_spec_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "identity.bin"
    path.write_bytes(b"\x00" * 64)

    def _fake_resolve(candidate, *, context=None):
        _ = candidate
        width = int((context.manual_overrides or {}).get("camera_settings.resolution_x", 0))
        return RawDecodeSpec(
            source_kind="raw",
            pixel_format="mono8",
            width=width,
            height=4,
            stride_bytes=None,
            offset_bytes=0,
        )

    monkeypatch.setattr(raw_decode, "resolve_raw_decode_spec", _fake_resolve)

    first = build_image_metric_identity(
        path,
        raw_resolver_context=RawDecodeResolverContext(
            manual_overrides={"camera_settings.resolution_x": 8},
        ),
    )
    second = build_image_metric_identity(
        path,
        raw_resolver_context=RawDecodeResolverContext(
            manual_overrides={"camera_settings.resolution_x": 16},
        ),
    )

    assert first.path == second.path
    assert first.fingerprint_hash != second.fingerprint_hash

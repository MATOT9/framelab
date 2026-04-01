from __future__ import annotations

import json

import pytest

from framelab.datacard_authoring.mapping import (
    DEFAULT_MAPPING_FILE,
    load_field_mapping,
    mapping_config_path,
)
from framelab.raw_decode import SUPPORTED_MONO_RAW_PIXEL_FORMATS


pytestmark = [pytest.mark.fast, pytest.mark.core]


def test_load_field_mapping_backfills_pixel_format_options(
    monkeypatch,
    tmp_path,
) -> None:
    config_dir = tmp_path / "config"
    monkeypatch.setenv("FRAMELAB_CONFIG_DIR", str(config_dir))

    payload = json.loads(DEFAULT_MAPPING_FILE.read_text(encoding="utf-8"))
    for field in payload.get("fields", []):
        if field.get("key") == "camera_settings.pixel_format":
            field.pop("options", None)

    path = mapping_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    mapping = load_field_mapping()
    spec = mapping.by_key()["camera_settings.pixel_format"]

    assert spec.value_type == "string"
    assert spec.options == SUPPORTED_MONO_RAW_PIXEL_FORMATS

    updated = json.loads(path.read_text(encoding="utf-8"))
    entry = next(
        item
        for item in updated["fields"]
        if item.get("key") == "camera_settings.pixel_format"
    )
    assert entry["options"] == list(SUPPORTED_MONO_RAW_PIXEL_FORMATS)


def test_load_field_mapping_reinserts_missing_pixel_format_field(
    monkeypatch,
    tmp_path,
) -> None:
    config_dir = tmp_path / "config"
    monkeypatch.setenv("FRAMELAB_CONFIG_DIR", str(config_dir))

    payload = json.loads(DEFAULT_MAPPING_FILE.read_text(encoding="utf-8"))
    payload["fields"] = [
        field
        for field in payload.get("fields", [])
        if field.get("key") != "camera_settings.pixel_format"
    ]

    path = mapping_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    mapping = load_field_mapping()

    assert "camera_settings.pixel_format" in mapping.by_key()
    updated = json.loads(path.read_text(encoding="utf-8"))
    assert any(
        item.get("key") == "camera_settings.pixel_format"
        for item in updated["fields"]
    )


def test_load_field_mapping_merges_new_pixel_format_options_into_existing_file(
    monkeypatch,
    tmp_path,
) -> None:
    config_dir = tmp_path / "config"
    monkeypatch.setenv("FRAMELAB_CONFIG_DIR", str(config_dir))

    payload = json.loads(DEFAULT_MAPPING_FILE.read_text(encoding="utf-8"))
    for field in payload.get("fields", []):
        if field.get("key") == "camera_settings.pixel_format":
            field["options"] = [
                "mono8",
                "mono12_lsb",
                "mono12_msb",
                "mono12p",
                "mono16",
                "vendor-custom-format",
            ]

    path = mapping_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    mapping = load_field_mapping()
    spec = mapping.by_key()["camera_settings.pixel_format"]

    assert spec.options == (
        *SUPPORTED_MONO_RAW_PIXEL_FORMATS,
        "vendor-custom-format",
    )

    updated = json.loads(path.read_text(encoding="utf-8"))
    entry = next(
        item
        for item in updated["fields"]
        if item.get("key") == "camera_settings.pixel_format"
    )
    assert entry["options"] == [
        *SUPPORTED_MONO_RAW_PIXEL_FORMATS,
        "vendor-custom-format",
    ]

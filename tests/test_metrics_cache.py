from __future__ import annotations

import os
from pathlib import Path

import pytest

from framelab.background import BackgroundConfig, BackgroundLibrary
from framelab.metrics_cache import (
    STATIC_METRIC_KIND,
    MetricCacheWrite,
    MetricsCache,
    background_signature_payload,
    build_file_metric_identity,
    dynamic_metric_signature_hash,
    static_metric_signature_hash,
)


pytestmark = [pytest.mark.fast, pytest.mark.core]


def test_build_file_metric_identity_uses_dataset_relative_path(
    tmp_path: Path,
) -> None:
    dataset_root = tmp_path / "dataset"
    image_path = dataset_root / "nested" / "image.tif"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"abc")

    identity = build_file_metric_identity(
        image_path,
        dataset_root=dataset_root,
    )

    assert identity.path == str(image_path.resolve())
    assert identity.relative_path == "nested/image.tif"
    assert identity.size_bytes == 3
    assert identity.fingerprint_hash


def test_metrics_cache_round_trip_invalidates_when_file_fingerprint_changes(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "image.tif"
    image_path.write_bytes(b"abc")
    cache = MetricsCache(tmp_path / "metrics.sqlite")
    signature_hash = static_metric_signature_hash()
    first_identity = build_file_metric_identity(image_path, dataset_root=tmp_path)

    cache.store_entries(
        [
            MetricCacheWrite(
                identity=first_identity,
                payload={"min_non_zero": 1, "max_pixel": 4},
            ),
        ],
        metric_kind=STATIC_METRIC_KIND,
        signature_hash=signature_hash,
    )

    first_hit = cache.fetch_entries(
        [first_identity],
        metric_kind=STATIC_METRIC_KIND,
        signature_hash=signature_hash,
    )
    assert first_hit == {
        str(image_path.resolve()): {"min_non_zero": 1, "max_pixel": 4},
    }

    previous_stat = image_path.stat()
    image_path.write_bytes(b"abcdef")
    os.utime(
        image_path,
        ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns + 1_000_000),
    )
    second_identity = build_file_metric_identity(image_path, dataset_root=tmp_path)

    second_hit = cache.fetch_entries(
        [second_identity],
        metric_kind=STATIC_METRIC_KIND,
        signature_hash=signature_hash,
    )

    assert second_identity.fingerprint_hash != first_identity.fingerprint_hash
    assert second_hit == {}


def test_dynamic_metric_signature_changes_with_background_inputs(
    tmp_path: Path,
) -> None:
    global_bg = tmp_path / "global.tif"
    exposure_bg = tmp_path / "10ms.tif"
    global_bg.write_bytes(b"global")
    exposure_bg.write_bytes(b"exposure")
    library = BackgroundLibrary(
        global_source_path=str(global_bg),
        source_paths_by_exposure_ms={10.0: (str(exposure_bg),)},
    )
    config = BackgroundConfig(enabled=True, clip_negative=True)

    payload = background_signature_payload(
        library,
        config,
        dataset_root=tmp_path,
    )
    first_hash = dynamic_metric_signature_hash(
        mode="topk",
        threshold_value=12.0,
        avg_count_value=8,
        background_payload=payload,
    )

    config.clip_negative = False
    changed_config_hash = dynamic_metric_signature_hash(
        mode="topk",
        threshold_value=12.0,
        avg_count_value=8,
        background_payload=background_signature_payload(
            library,
            config,
            dataset_root=tmp_path,
        ),
    )

    config.clip_negative = True
    previous_stat = global_bg.stat()
    global_bg.write_bytes(b"global-updated")
    os.utime(
        global_bg,
        ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns + 1_000_000),
    )
    changed_file_hash = dynamic_metric_signature_hash(
        mode="topk",
        threshold_value=12.0,
        avg_count_value=8,
        background_payload=background_signature_payload(
            library,
            config,
            dataset_root=tmp_path,
        ),
    )

    assert changed_config_hash != first_hash
    assert changed_file_hash != first_hash

"""Portable SQLite cache for static and derived image metrics."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterable

from .background import BackgroundConfig, BackgroundLibrary


CACHE_SCHEMA_VERSION = 1
STATIC_METRIC_KIND = "static_v1"
DYNAMIC_METRIC_KIND = "dynamic_v1"
ROI_METRIC_KIND = "roi_v1"


def _repo_root() -> Path:
    """Return the shareable application root that owns the cache file."""

    return Path(__file__).resolve().parent.parent


def metrics_cache_path() -> Path:
    """Return the SQLite path used for persisted metric entries."""

    override = os.environ.get("FRAMELAB_METRICS_CACHE_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return _repo_root() / ".framelab" / "cache" / "metrics.sqlite"


def _canonical_json(value: object) -> str:
    """Serialize a JSON-compatible payload in a stable canonical form."""

    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _stable_hash(payload: object) -> str:
    """Return one stable hash for a normalized cache-key payload."""

    return hashlib.blake2b(
        _canonical_json(payload).encode("utf-8"),
        digest_size=16,
    ).hexdigest()


def _is_same_or_child_path(path: Path, root: Path) -> bool:
    """Return whether ``path`` is the same as or below ``root``."""

    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _normalize_root(root: str | Path | None) -> Path | None:
    if root is None:
        return None
    return Path(root).expanduser().resolve()


def _external_relative_path(path: Path) -> str:
    """Return a stable-ish fallback relative path for external files."""

    parts = path.resolve().parts
    if len(parts) <= 4:
        return "/".join(parts).lstrip("/") or path.name
    return "/".join(parts[-4:])


def cache_relative_path(
    path: str | Path,
    *,
    dataset_root: str | Path | None = None,
    workspace_root: str | Path | None = None,
    app_root: str | Path | None = None,
) -> str:
    """Return the preferred portable relative path for one source file."""

    resolved_path = Path(path).expanduser().resolve()
    app_candidate = _normalize_root(app_root) or _repo_root()
    if _is_same_or_child_path(resolved_path, app_candidate):
        return resolved_path.relative_to(app_candidate).as_posix()

    workspace_candidate = _normalize_root(workspace_root)
    if (
        workspace_candidate is not None
        and _is_same_or_child_path(resolved_path, workspace_candidate)
    ):
        return resolved_path.relative_to(workspace_candidate).as_posix()

    dataset_candidate = _normalize_root(dataset_root)
    if (
        dataset_candidate is not None
        and _is_same_or_child_path(resolved_path, dataset_candidate)
    ):
        return resolved_path.relative_to(dataset_candidate).as_posix()

    return _external_relative_path(resolved_path)


@dataclass(frozen=True, slots=True)
class FileMetricIdentity:
    """Portable file identity used as the basis for cache validity."""

    path: str
    relative_path: str
    size_bytes: int
    mtime_ns: int
    fingerprint_hash: str


@dataclass(frozen=True, slots=True)
class MetricCacheWrite:
    """One cache write operation pairing a file identity with a payload."""

    identity: FileMetricIdentity
    payload: dict[str, Any]


def build_file_metric_identity(
    path: str | Path,
    *,
    dataset_root: str | Path | None = None,
    workspace_root: str | Path | None = None,
    app_root: str | Path | None = None,
    extra_fingerprint: object | None = None,
) -> FileMetricIdentity:
    """Build a portable file fingerprint from relative path, size, and mtime."""

    resolved_path = Path(path).expanduser().resolve()
    stat = resolved_path.stat()
    relative_path = cache_relative_path(
        resolved_path,
        dataset_root=dataset_root,
        workspace_root=workspace_root,
        app_root=app_root,
    )
    fingerprint_hash = _stable_hash(
        {
            "relative_path": relative_path,
            "size_bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "extra": extra_fingerprint,
        },
    )
    return FileMetricIdentity(
        path=str(resolved_path),
        relative_path=relative_path,
        size_bytes=int(stat.st_size),
        mtime_ns=int(stat.st_mtime_ns),
        fingerprint_hash=fingerprint_hash,
    )


def static_metric_signature_hash() -> str:
    """Return the versioned signature for static scan metrics."""

    return _stable_hash(
        {
            "metric_kind": STATIC_METRIC_KIND,
            "cache_schema_version": CACHE_SCHEMA_VERSION,
        },
    )


def background_signature_payload(
    library: BackgroundLibrary,
    config: BackgroundConfig,
    *,
    dataset_root: str | Path | None = None,
    workspace_root: str | Path | None = None,
    app_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return a stable JSON-compatible description of background inputs."""

    def _source_descriptor(path: str) -> dict[str, object]:
        source_path = Path(path).expanduser().resolve()
        stat = source_path.stat()
        return {
            "relative_path": cache_relative_path(
                source_path,
                dataset_root=dataset_root,
                workspace_root=workspace_root,
                app_root=app_root,
            ),
            "size_bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
        }

    payload: dict[str, Any] = {
        "enabled": bool(config.enabled),
        "source_mode": str(config.source_mode),
        "clip_negative": bool(config.clip_negative),
        "exposure_policy": str(config.exposure_policy),
        "no_match_policy": str(config.no_match_policy),
        "global_reference": None,
        "exposure_references": [],
    }
    if library.global_source_path:
        payload["global_reference"] = _source_descriptor(
            library.global_source_path,
        )
    exposure_items: list[dict[str, object]] = []
    for key, source_paths in sorted(library.source_paths_by_exposure_ms.items()):
        normalized_paths = tuple(
            str(Path(path).expanduser().resolve())
            for path in source_paths
        )
        exposure_items.append(
            {
                "exposure_ms": float(key),
                "sources": [
                    _source_descriptor(path)
                    for path in normalized_paths
                ],
            },
        )
    payload["exposure_references"] = exposure_items
    return payload


def dynamic_metric_signature_hash(
    *,
    mode: str,
    threshold_value: float,
    avg_count_value: int,
    background_payload: dict[str, Any],
) -> str:
    """Return the versioned signature for dynamic row metrics."""

    return _stable_hash(
        {
            "metric_kind": DYNAMIC_METRIC_KIND,
            "cache_schema_version": CACHE_SCHEMA_VERSION,
            "mode": str(mode),
            "threshold_value": float(threshold_value),
            "avg_count_value": int(avg_count_value) if str(mode) == "topk" else None,
            "background": background_payload,
        },
    )


def roi_metric_signature_hash(
    *,
    roi_rect: tuple[int, int, int, int],
    background_payload: dict[str, Any],
) -> str:
    """Return the versioned signature for ROI row metrics."""

    return _stable_hash(
        {
            "metric_kind": ROI_METRIC_KIND,
            "cache_schema_version": CACHE_SCHEMA_VERSION,
            "roi_rect": [int(value) for value in roi_rect],
            "background": background_payload,
        },
    )


class MetricsCache:
    """Small SQLite-backed cache for file-scoped metric payloads."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or metrics_cache_path()

    def clear(self) -> None:
        """Delete the SQLite cache file when it exists."""

        if self.path.exists():
            self.path.unlink()

    def fetch_entries(
        self,
        identities: Iterable[FileMetricIdentity],
        *,
        metric_kind: str,
        signature_hash: str,
    ) -> dict[str, dict[str, Any]]:
        """Load cached payloads for the requested identities and signature."""

        identity_list = list(identities)
        if not identity_list:
            return {}
        placeholder_sql = ",".join("?" for _ in identity_list)
        fingerprint_to_path = {
            identity.fingerprint_hash: identity.path
            for identity in identity_list
        }
        query = (
            "SELECT fingerprint_hash, payload_json "
            "FROM metric_entries "
            "WHERE metric_kind = ? "
            "AND signature_hash = ? "
            "AND cache_schema_version = ? "
            f"AND fingerprint_hash IN ({placeholder_sql})"
        )
        with self._connect() as connection:
            rows = connection.execute(
                query,
                [
                    str(metric_kind),
                    str(signature_hash),
                    int(CACHE_SCHEMA_VERSION),
                    *fingerprint_to_path.keys(),
                ],
            ).fetchall()
        return {
            fingerprint_to_path[str(fingerprint_hash)]: json.loads(payload_json)
            for fingerprint_hash, payload_json in rows
            if str(fingerprint_hash) in fingerprint_to_path
        }

    def store_entries(
        self,
        writes: Iterable[MetricCacheWrite],
        *,
        metric_kind: str,
        signature_hash: str,
    ) -> None:
        """Store or update one batch of cached metric payloads."""

        write_list = list(writes)
        if not write_list:
            return
        now_ns = time.time_ns()
        with self._connect() as connection:
            connection.executemany(
                (
                    "INSERT INTO files ("
                    " fingerprint_hash, relative_path, size_bytes, mtime_ns,"
                    " created_at_ns, updated_at_ns"
                    ") VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(fingerprint_hash) DO UPDATE SET "
                    " relative_path = excluded.relative_path,"
                    " size_bytes = excluded.size_bytes,"
                    " mtime_ns = excluded.mtime_ns,"
                    " updated_at_ns = excluded.updated_at_ns"
                ),
                [
                    (
                        write.identity.fingerprint_hash,
                        write.identity.relative_path,
                        int(write.identity.size_bytes),
                        int(write.identity.mtime_ns),
                        now_ns,
                        now_ns,
                    )
                    for write in write_list
                ],
            )
            connection.executemany(
                (
                    "INSERT INTO metric_entries ("
                    " fingerprint_hash, metric_kind, signature_hash, payload_json,"
                    " cache_schema_version, created_at_ns, updated_at_ns"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT("
                    " fingerprint_hash, metric_kind, signature_hash, cache_schema_version"
                    ") DO UPDATE SET "
                    " payload_json = excluded.payload_json,"
                    " updated_at_ns = excluded.updated_at_ns"
                ),
                [
                    (
                        write.identity.fingerprint_hash,
                        str(metric_kind),
                        str(signature_hash),
                        _canonical_json(write.payload),
                        int(CACHE_SCHEMA_VERSION),
                        now_ns,
                        now_ns,
                    )
                    for write in write_list
                ],
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path))
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        self._ensure_schema(connection)
        return connection

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS files (
                fingerprint_hash TEXT PRIMARY KEY,
                relative_path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                created_at_ns INTEGER NOT NULL,
                updated_at_ns INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS metric_entries (
                fingerprint_hash TEXT NOT NULL,
                metric_kind TEXT NOT NULL,
                signature_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                cache_schema_version INTEGER NOT NULL,
                created_at_ns INTEGER NOT NULL,
                updated_at_ns INTEGER NOT NULL,
                PRIMARY KEY (
                    fingerprint_hash,
                    metric_kind,
                    signature_hash,
                    cache_schema_version
                ),
                FOREIGN KEY (fingerprint_hash)
                    REFERENCES files(fingerprint_hash)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_metric_entries_lookup
            ON metric_entries (
                metric_kind,
                signature_hash,
                cache_schema_version
            );
            """
        )

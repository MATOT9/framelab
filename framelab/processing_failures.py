"""Structured processing-failure records and summaries."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


_STAGE_LABELS = {
    "scan": "Scan",
    "metrics": "Metrics",
    "roi": "ROI",
    "preview": "Preview",
    "background": "Background",
}


@dataclass(frozen=True, slots=True)
class ProcessingFailure:
    """One structured processing/load failure tied to a file and stage."""

    stage: str
    path: str
    reason: str


def stage_label(stage: str) -> str:
    """Return a user-facing label for one failure stage."""
    token = str(stage or "").strip().lower()
    return _STAGE_LABELS.get(token, token.title() or "Unknown")


def failure_reason_from_exception(exc: BaseException) -> str:
    """Build a concise, stable failure reason from one exception."""
    kind = exc.__class__.__name__
    message = " ".join(str(exc).split())
    if not message or message == kind:
        return kind
    return f"{kind}: {message}"


def make_processing_failure(
    *,
    stage: str,
    path: str | Path,
    reason: str,
) -> ProcessingFailure:
    """Build one normalized processing-failure record."""
    clean_reason = " ".join(str(reason or "").split()) or "Unknown error"
    return ProcessingFailure(
        stage=str(stage or "").strip().lower() or "unknown",
        path=str(Path(path)) if str(path).strip() else "",
        reason=clean_reason,
    )


def dedupe_processing_failures(
    failures: Iterable[ProcessingFailure],
) -> list[ProcessingFailure]:
    """Return processing failures without duplicate stage/path/reason tuples."""
    out: list[ProcessingFailure] = []
    seen: set[tuple[str, str, str]] = set()
    for failure in failures:
        key = (failure.stage, failure.path, failure.reason)
        if key in seen:
            continue
        seen.add(key)
        out.append(failure)
    return out


def merge_processing_failures(
    existing: Iterable[ProcessingFailure],
    new_failures: Iterable[ProcessingFailure],
    *,
    replace_stage: str | None = None,
) -> list[ProcessingFailure]:
    """Merge failure lists, optionally replacing all records for one stage."""
    normalized_stage = (
        str(replace_stage or "").strip().lower() or None
    )
    merged = list(existing)
    if normalized_stage is not None:
        merged = [
            failure for failure in merged
            if failure.stage != normalized_stage
        ]
    merged.extend(new_failures)
    return dedupe_processing_failures(merged)


def summarize_processing_failures(
    failures: Iterable[ProcessingFailure],
) -> str:
    """Return a compact stage-count summary for banner/status use."""
    items = list(failures)
    if not items:
        return "No processing issues."
    counts = Counter(stage_label(failure.stage) for failure in items)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{label} {count}" for label, count in ordered)


def format_processing_failure_details(
    failures: Iterable[ProcessingFailure],
) -> str:
    """Return detailed multi-line text for the failure-details dialog."""
    items = list(failures)
    if not items:
        return "No processing issues recorded."

    lines = [
        f"{len(items)} processing issue(s)",
        summarize_processing_failures(items),
        "",
    ]
    for failure in items:
        location = failure.path or "<operation>"
        lines.append(f"[{stage_label(failure.stage)}] {location}")
        lines.append(f"  {failure.reason}")
    return "\n".join(lines)

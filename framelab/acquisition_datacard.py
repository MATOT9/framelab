"""Helpers for acquisition datacard paths and override selectors."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any, Optional


ACQUISITION_DATACARD_NAME = "acquisition_datacard.json"
SESSION_DATACARD_NAME = "session_datacard.json"
CAMPAIGN_DATACARD_NAME = "campaign_datacard.json"
ACQUISITION_FOLDER_PATTERN = re.compile(
    r"^acq-(?P<number>\d+)(?:__(?P<label>.+))?$",
    re.IGNORECASE,
)


def resolve_acquisition_datacard_path(path: str | Path) -> Path:
    """Return the datacard file path for a folder or explicit file path.

    Parameters
    ----------
    path : str | Path
        Acquisition folder path or explicit datacard path.

    Returns
    -------
    Path
        Resolved acquisition datacard file path.
    """
    raw_path = Path(path)
    if raw_path.name.lower() == ACQUISITION_DATACARD_NAME:
        return raw_path
    return raw_path.joinpath(ACQUISITION_DATACARD_NAME)


def resolve_session_datacard_path(path: str | Path) -> Path:
    """Return the datacard file path for a folder or explicit session datacard."""
    raw_path = Path(path)
    if raw_path.name.lower() == SESSION_DATACARD_NAME:
        return raw_path
    return raw_path.joinpath(SESSION_DATACARD_NAME)


def resolve_campaign_datacard_path(path: str | Path) -> Path:
    """Return the datacard file path for a folder or explicit campaign datacard."""
    raw_path = Path(path)
    if raw_path.name.lower() == CAMPAIGN_DATACARD_NAME:
        return raw_path
    return raw_path.joinpath(CAMPAIGN_DATACARD_NAME)


def parse_acquisition_folder_name(
    name: str,
) -> tuple[int, str | None, int] | None:
    """Parse ``acq-####`` folder names with optional ``__label`` suffix."""
    match = ACQUISITION_FOLDER_PATTERN.match(str(name).strip())
    if match is None:
        return None
    raw_number = match.group("number")
    try:
        number = int(raw_number)
    except Exception:
        return None
    raw_label = (match.group("label") or "").strip()
    return (
        number,
        raw_label or None,
        len(raw_number),
    )


def is_acquisition_folder_name(name: str) -> bool:
    """Return whether a folder name matches the acquisition naming contract."""
    return parse_acquisition_folder_name(name) is not None


def format_acquisition_folder_name(
    number: int,
    label: str | None = None,
    *,
    width: int = 4,
) -> str:
    """Format one acquisition folder name from number and optional label."""
    safe_width = max(1, int(width))
    token = f"acq-{int(number):0{safe_width}d}"
    clean_label = str(label or "").strip()
    if clean_label:
        return f"{token}__{clean_label}"
    return token


def _search_roots_for_path(path: str | Path) -> list[Path]:
    """Return candidate directories for ancestor-based datacard/root lookup."""
    candidate = Path(path)
    search_roots: list[Path] = []
    if candidate.is_dir():
        search_roots.append(candidate)
    else:
        search_roots.append(candidate.parent)
    search_roots.extend(candidate.parents)
    seen: set[Path] = set()
    unique: list[Path] = []
    for root in search_roots:
        if root in seen:
            continue
        seen.add(root)
        unique.append(root)
    return unique


def find_acquisition_root(
    path: str | Path,
    *,
    allow_name_only: bool = False,
) -> Optional[Path]:
    """Find the nearest acquisition root by datacard or acquisition folder name.

    Parameters
    ----------
    path : str | Path
        File or directory path inside an acquisition tree.
    allow_name_only : bool, default=False
        When ``True``, fall back to the nearest ``acq-####`` ancestor even if
        it does not yet carry an acquisition datacard.

    Returns
    -------
    Optional[Path]
        Acquisition root directory when found, otherwise ``None``.
    """
    for parent in _search_roots_for_path(path):
        if resolve_acquisition_datacard_path(parent).is_file():
            return parent
        if allow_name_only and is_acquisition_folder_name(parent.name):
            return parent
    return None


def find_session_root(path: str | Path) -> Optional[Path]:
    """Find the nearest ancestor directory containing ``session_datacard.json``."""
    for parent in _search_roots_for_path(path):
        if resolve_session_datacard_path(parent).is_file():
            return parent
    return None


def find_campaign_root(path: str | Path) -> Optional[Path]:
    """Find the nearest ancestor directory containing ``campaign_datacard.json``."""
    for parent in _search_roots_for_path(path):
        if resolve_campaign_datacard_path(parent).is_file():
            return parent
    return None


def selector_frame_range(
    override: dict[str, Any],
) -> tuple[int, int] | None:
    """Return a normalized selector frame range from one override payload.

    Parameters
    ----------
    override : dict[str, Any]
        Raw override payload object.

    Returns
    -------
    tuple[int, int] | None
        Normalized inclusive frame range, or ``None`` when the selector is
        missing or invalid.
    """
    selector = override.get("selector")
    if not isinstance(selector, dict):
        return None
    frame_range = selector.get("frame_range")
    if (
        not isinstance(frame_range, list)
        or len(frame_range) != 2
        or not all(isinstance(value, int) for value in frame_range)
    ):
        return None
    start, end = int(frame_range[0]), int(frame_range[1])
    if start > end:
        start, end = end, start
    return (start, end)


def collect_override_frame_ranges(
    overrides: list[dict[str, Any]],
) -> list[tuple[int, int]]:
    """Collect normalized frame ranges from override payloads.

    Parameters
    ----------
    overrides : list[dict[str, Any]]
        Raw override payload objects.

    Returns
    -------
    list[tuple[int, int]]
        Normalized inclusive frame ranges.
    """
    ranges: list[tuple[int, int]] = []
    for item in overrides:
        frame_range = selector_frame_range(item)
        if frame_range is not None:
            ranges.append(frame_range)
    return ranges


def detect_override_index_base(
    overrides: list[dict[str, Any]],
    frame_indices: list[int],
) -> int:
    """Detect whether override frame selectors are zero- or one-based.

    Parameters
    ----------
    overrides : list[dict[str, Any]]
        Raw override payload objects.
    frame_indices : list[int]
        Available dataset frame indices.

    Returns
    -------
    int
        Detected selector base, either ``0`` or ``1``.
    """
    ranges = collect_override_frame_ranges(overrides)
    if not ranges:
        return 0

    starts = [start for start, _end in ranges]
    ends = [end for _start, end in ranges]
    if any(start == 0 for start in starts):
        return 0
    if starts and min(starts) >= 1 and frame_indices:
        if max(ends) == max(frame_indices) + 1:
            return 1
    return 0


def normalize_override_selectors(
    overrides: list[dict[str, Any]],
    frame_indices: list[int],
) -> tuple[list[dict[str, Any]], int]:
    """Normalize override selector frame ranges to zero-based indices.

    Parameters
    ----------
    overrides : list[dict[str, Any]]
        Raw override payload objects.
    frame_indices : list[int]
        Available dataset frame indices.

    Returns
    -------
    tuple[list[dict[str, Any]], int]
        Normalized override payloads and the detected selector base.
    """
    index_base = detect_override_index_base(overrides, frame_indices)
    normalized: list[dict[str, Any]] = []
    for item in overrides:
        out = deepcopy(item)
        frame_range = selector_frame_range(out)
        if frame_range is not None:
            start, end = frame_range
            if index_base == 1:
                start -= 1
                end -= 1
            selector = out.get("selector")
            if not isinstance(selector, dict):
                selector = {}
                out["selector"] = selector
            selector["frame_range"] = [start, end]
        normalized.append(out)
    return normalized, index_base


def override_applies_to_frame(
    override: dict[str, Any],
    frame_index: int,
) -> bool:
    """Return whether an override selector applies to a frame index.

    Parameters
    ----------
    override : dict[str, Any]
        Normalized override payload object.
    frame_index : int
        Zero-based frame index.

    Returns
    -------
    bool
        ``True`` when the override applies to the frame.
    """
    frame_range = selector_frame_range(override)
    if frame_range is None:
        return False
    start, end = frame_range
    return start <= frame_index <= end

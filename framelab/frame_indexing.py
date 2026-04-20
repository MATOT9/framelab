"""Shared frame-name parsing and frame-index discovery helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from pathlib import Path

from .image_io import is_supported_image


FRAME_PATTERN = re.compile(r"^f(?P<index>\d+)$", re.IGNORECASE)
EBUS_PATTERN = re.compile(
    r"^(?P<index>\d+)_(?P<timestamp>[0-9A-Fa-f]+)$",
)
UTC_TIMESTAMP_PATTERN = re.compile(
    r"(?:^|[_-])"
    r"(?P<date>\d{8})_(?P<time>\d{6})_(?P<msec>\d{3})Z"
    r"(?:$|[_-])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FrameNameInfo:
    """Parsed frame information extracted from a TIFF stem."""

    frame_index: int | None
    naming: str
    ebus_timestamp_hex: str | None = None
    ebus_timestamp_ms: int | None = None
    utc_timestamp_ms: int | None = None
    utc_timestamp_iso: str | None = None


def _parse_utc_timestamp_match(
    match: re.Match[str],
) -> tuple[int, str] | None:
    """Return epoch milliseconds and ISO text for a UTC filename timestamp."""

    try:
        date_text = match.group("date")
        time_text = match.group("time")
        millisecond = int(match.group("msec"), 10)
        timestamp = datetime(
            int(date_text[0:4]),
            int(date_text[4:6]),
            int(date_text[6:8]),
            int(time_text[0:2]),
            int(time_text[2:4]),
            int(time_text[4:6]),
            millisecond * 1000,
            tzinfo=timezone.utc,
        )
    except Exception:
        return None
    epoch_ms = int(round(timestamp.timestamp() * 1000.0))
    iso_text = timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return (epoch_ms, iso_text)


def _leading_index_before_utc_timestamp(stem: str, match: re.Match[str]) -> int | None:
    """Return a leading numeric frame index immediately before a UTC timestamp."""

    prefix = stem[:match.start()].rstrip("_-")
    if not prefix or not prefix.isdigit():
        return None
    try:
        return int(prefix, 10)
    except ValueError:
        return None


@dataclass(frozen=True)
class FrameIndexResolution:
    """Resolved frame-index mapping and discovery metadata."""

    index_by_name: dict[str, int]
    indices: list[int]
    mode: str


def parse_frame_name(stem: str) -> FrameNameInfo:
    """Parse known frame naming schemes from a TIFF stem.

    Parameters
    ----------
    stem : str
        Filename stem without extension.

    Returns
    -------
    FrameNameInfo
        Parsed naming details.
    """
    frame_match = FRAME_PATTERN.match(stem)
    if frame_match is not None:
        return FrameNameInfo(
            frame_index=int(frame_match.group("index")),
            naming="f_index",
        )

    utc_match = UTC_TIMESTAMP_PATTERN.search(stem)
    if utc_match is not None:
        parsed_utc = _parse_utc_timestamp_match(utc_match)
        if parsed_utc is not None:
            utc_timestamp_ms, utc_timestamp_iso = parsed_utc
            frame_index = _leading_index_before_utc_timestamp(stem, utc_match)
            return FrameNameInfo(
                frame_index=frame_index,
                naming=(
                    "utc_index_timestamp"
                    if frame_index is not None
                    else "utc_timestamp"
                ),
                utc_timestamp_ms=utc_timestamp_ms,
                utc_timestamp_iso=utc_timestamp_iso,
            )

    ebus_match = EBUS_PATTERN.match(stem)
    if ebus_match is None:
        return FrameNameInfo(frame_index=None, naming="unknown")

    timestamp_hex = ebus_match.group("timestamp").upper()
    try:
        frame_index = int(ebus_match.group("index"), 10)
    except ValueError:
        frame_index = None
    try:
        timestamp_ms = int(timestamp_hex, 16)
    except ValueError:
        timestamp_ms = None
    return FrameNameInfo(
        frame_index=frame_index,
        naming="ebus_index_timestamp",
        ebus_timestamp_hex=timestamp_hex,
        ebus_timestamp_ms=timestamp_ms,
    )


def resolve_frame_index_map(frames_dir: Path) -> FrameIndexResolution:
    """Resolve robust frame indices for one frame directory.

    Parameters
    ----------
    frames_dir : Path
        Directory containing TIFF frame files.

    Returns
    -------
    FrameIndexResolution
        Mapping and discovery metadata for the directory.
    """
    if not frames_dir.is_dir():
        return FrameIndexResolution({}, [], "none")

    files = sorted(
        (
            child
            for child in frames_dir.iterdir()
            if child.is_file() and is_supported_image(child)
        ),
        key=lambda item: item.name.lower(),
    )
    if not files:
        return FrameIndexResolution({}, [], "none")

    parsed_indices: dict[str, int] = {}
    parsed_values: list[int] = []
    parsed_namings: set[str] = set()
    timestamp_by_name: dict[str, int] = {}
    for frame_path in files:
        parsed = parse_frame_name(frame_path.stem)
        parsed_namings.add(parsed.naming)
        if parsed.frame_index is not None:
            parsed_indices[frame_path.name] = int(parsed.frame_index)
            parsed_values.append(int(parsed.frame_index))
        if parsed.ebus_timestamp_ms is not None:
            timestamp_by_name[frame_path.name] = int(parsed.ebus_timestamp_ms)

    if (
        len(parsed_indices) == len(files)
        and len(set(parsed_values)) == len(files)
    ):
        mode = (
            "ebus_index"
            if parsed_namings == {"ebus_index_timestamp"}
            else "filename_index"
        )
        return FrameIndexResolution(
            index_by_name=parsed_indices,
            indices=sorted(set(parsed_values)),
            mode=mode,
        )

    if (
        len(timestamp_by_name) == len(files)
        and len(set(timestamp_by_name.values())) == len(files)
    ):
        ordered = sorted(files, key=lambda item: timestamp_by_name[item.name])
        index_by_name = {
            frame_path.name: idx
            for idx, frame_path in enumerate(ordered)
        }
        return FrameIndexResolution(
            index_by_name=index_by_name,
            indices=list(range(len(ordered))),
            mode="ebus_timestamp_order",
        )

    ordered = sorted(files, key=lambda item: item.name.lower())
    index_by_name = {
        frame_path.name: idx
        for idx, frame_path in enumerate(ordered)
    }
    return FrameIndexResolution(
        index_by_name=index_by_name,
        indices=list(range(len(ordered))),
        mode="filename_order",
    )

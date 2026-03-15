"""Helpers for tracking legacy-compatibility code paths.

Use one searchable single-line comment directly above the compatibility code:

    # LEGACY_COMPAT[tag_name]: Short reason. Remove after: concrete cleanup trigger.

This keeps temporary bridges easy to audit with ``rg 'LEGACY_COMPAT\\['`` and
lets tests validate that every marker carries both intent and a removal target.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


LEGACY_COMPAT_PATTERN = re.compile(
    r"LEGACY_COMPAT\[(?P<tag>[a-z0-9_]+)\]: "
    r"(?P<reason>.+?) "
    r"Remove after: (?P<remove_after>.+)",
)


@dataclass(frozen=True, slots=True)
class LegacyCompatAnnotation:
    """One parsed legacy-compatibility marker from source code."""

    tag: str
    reason: str
    remove_after: str
    path: Path
    line_number: int


def parse_legacy_compat_line(
    line: str,
    *,
    path: Path,
    line_number: int,
) -> LegacyCompatAnnotation | None:
    """Parse one source line into a legacy-compatibility marker."""

    match = LEGACY_COMPAT_PATTERN.search(str(line))
    if match is None:
        return None
    return LegacyCompatAnnotation(
        tag=match.group("tag"),
        reason=match.group("reason").strip(),
        remove_after=match.group("remove_after").strip(),
        path=path,
        line_number=int(line_number),
    )

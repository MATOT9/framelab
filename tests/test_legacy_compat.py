"""Tests for searchable legacy-compatibility annotations."""

from __future__ import annotations

from pathlib import Path

import pytest

from framelab.legacy_compat import parse_legacy_compat_line


pytestmark = [pytest.mark.fast, pytest.mark.core]


def test_legacy_compat_markers_have_reason_and_cleanup_target() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    annotations = []

    for path in sorted((repo_root / "framelab").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            annotation = parse_legacy_compat_line(
                line,
                path=path.relative_to(repo_root),
                line_number=line_number,
            )
            if annotation is None:
                continue
            annotations.append(annotation)
            assert annotation.reason
            assert annotation.remove_after

    assert annotations, "expected at least one LEGACY_COMPAT marker in the codebase"

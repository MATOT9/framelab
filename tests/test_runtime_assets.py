from __future__ import annotations

from pathlib import Path

import pytest

import framelab.widgets as widgets_module
from framelab.runtime_assets import assets_dir, labreport_style_path


pytestmark = [pytest.mark.fast, pytest.mark.core]


def test_assets_dir_and_style_path_resolve_to_packaged_files() -> None:
    assert assets_dir().is_dir()
    assert labreport_style_path().is_file()


def test_widgets_style_path_is_independent_of_current_working_directory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    style_path = Path(widgets_module._labreport_style_path())

    assert style_path == labreport_style_path()
    assert style_path.is_file()

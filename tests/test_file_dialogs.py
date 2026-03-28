from __future__ import annotations

from pathlib import Path

import pytest

import framelab.file_dialogs as file_dialogs


pytestmark = [pytest.mark.fast, pytest.mark.core]


class _FakeFileDialog:
    Directory = 1
    ExistingFile = 2
    AcceptOpen = 3
    AcceptSave = 4
    ShowDirsOnly = 5
    DontUseNativeDialog = 6

    instances: list["_FakeFileDialog"] = []
    next_exec_result = True
    next_selected_files: list[str] = []
    next_selected_name_filter = ""

    def __init__(self, parent, title: str, directory: str) -> None:
        self.parent = parent
        self.title = title
        self.directory = directory
        self.file_mode = None
        self.accept_mode = None
        self.filter_value = None
        self.options: dict[int, bool] = {}
        self.name_filters: list[str] = []
        self.selected_file = ""
        self.selected_name_filter_value = ""
        self.stylesheet = ""
        type(self).instances.append(self)

    def setFileMode(self, mode: int) -> None:
        self.file_mode = mode

    def setFilter(self, value: int) -> None:
        self.filter_value = value

    def setOption(self, option: int, enabled: bool) -> None:
        self.options[option] = enabled

    def setDirectory(self, directory: str) -> None:
        self.directory = directory

    def setAcceptMode(self, mode: int) -> None:
        self.accept_mode = mode

    def setNameFilters(self, filters: list[str]) -> None:
        self.name_filters = list(filters)

    def selectNameFilter(self, name_filter: str) -> None:
        self.selected_name_filter_value = name_filter

    def selectFile(self, file_name: str) -> None:
        self.selected_file = file_name

    def setStyleSheet(self, stylesheet: str) -> None:
        self.stylesheet = stylesheet

    def exec(self) -> bool:
        return type(self).next_exec_result

    def selectedFiles(self) -> list[str]:
        return list(type(self).next_selected_files)

    def selectedNameFilter(self) -> str:
        return type(self).next_selected_name_filter or self.selected_name_filter_value


def test_resolve_dialog_start_path_falls_back_to_existing_parent(tmp_path: Path) -> None:
    missing = tmp_path / "missing" / "child" / "file.txt"

    resolved = file_dialogs.resolve_dialog_start_path(missing)

    assert resolved == tmp_path


def test_choose_existing_directory_uses_non_native_dialog(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _FakeFileDialog.instances.clear()
    _FakeFileDialog.next_exec_result = True
    _FakeFileDialog.next_selected_files = [str(tmp_path / "chosen")]
    monkeypatch.setattr(file_dialogs.qtw, "QFileDialog", _FakeFileDialog)

    selected = file_dialogs.choose_existing_directory(
        None,
        "Select Folder",
        tmp_path / "missing" / "child",
    )

    dialog = _FakeFileDialog.instances[-1]
    assert selected == str(tmp_path / "chosen")
    assert dialog.file_mode == _FakeFileDialog.Directory
    assert dialog.options[_FakeFileDialog.ShowDirsOnly] is True
    assert dialog.options[_FakeFileDialog.DontUseNativeDialog] is True
    assert dialog.directory == str(tmp_path)


def test_choose_save_file_uses_non_native_dialog_and_preserves_filter(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _FakeFileDialog.instances.clear()
    _FakeFileDialog.next_exec_result = True
    _FakeFileDialog.next_selected_files = [str(tmp_path / "plot")]
    _FakeFileDialog.next_selected_name_filter = "PNG Image (*.png)"
    monkeypatch.setattr(file_dialogs.qtw, "QFileDialog", _FakeFileDialog)

    selected_path, selected_filter = file_dialogs.choose_save_file(
        None,
        "Export Plot",
        tmp_path / "plot.png",
        name_filters=(
            "PNG Image (*.png)",
            "JPEG Image (*.jpg *.jpeg)",
        ),
    )

    dialog = _FakeFileDialog.instances[-1]
    assert selected_path == str(tmp_path / "plot")
    assert selected_filter == "PNG Image (*.png)"
    assert dialog.accept_mode == _FakeFileDialog.AcceptSave
    assert dialog.options[_FakeFileDialog.DontUseNativeDialog] is True
    assert dialog.name_filters == [
        "PNG Image (*.png)",
        "JPEG Image (*.jpg *.jpeg)",
    ]
    assert dialog.selected_file == "plot.png"


def test_choose_open_file_uses_non_native_dialog_and_preserves_filter(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _FakeFileDialog.instances.clear()
    _FakeFileDialog.next_exec_result = True
    _FakeFileDialog.next_selected_files = [str(tmp_path / "chosen.json")]
    _FakeFileDialog.next_selected_name_filter = "JSON (*.json)"
    monkeypatch.setattr(file_dialogs.qtw, "QFileDialog", _FakeFileDialog)

    selected = file_dialogs.choose_open_file(
        None,
        "Load ROI",
        tmp_path / "roi.json",
        name_filters=("JSON (*.json)", "All files (*)"),
        selected_name_filter="JSON (*.json)",
    )

    dialog = _FakeFileDialog.instances[-1]
    assert selected == str(tmp_path / "chosen.json")
    assert dialog.accept_mode == _FakeFileDialog.AcceptOpen
    assert dialog.file_mode == _FakeFileDialog.ExistingFile
    assert dialog.options[_FakeFileDialog.DontUseNativeDialog] is True
    assert dialog.name_filters == ["JSON (*.json)", "All files (*)"]
    assert dialog.selected_file == "roi.json"

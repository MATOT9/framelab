"""Explicit dataset/session state ownership for the main window."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable


class DatasetStateController:
    """Own loaded-dataset state outside the main window UI object."""

    def __init__(self) -> None:
        self.dataset_root: Path | None = None
        self.paths: list[str] = []
        self.path_metadata: dict[str, dict[str, object]] = {}
        self.metadata_source_mode = "json"
        self.preferred_metadata_source_mode = "json"
        self.has_json_metadata_source = False
        self.metadata_visible_paths: list[str] = []
        self.selected_index: int | None = None

    def clear_loaded_dataset(self) -> None:
        """Clear loaded-dataset content while preserving source preferences."""
        self.dataset_root = None
        self.paths = []
        self.path_metadata = {}
        self.metadata_visible_paths = []
        self.selected_index = None

    def set_loaded_dataset(
        self,
        dataset_root: Path | str | None,
        paths: Iterable[str],
    ) -> None:
        """Replace the current loaded dataset root and path list."""
        self.dataset_root = (
            Path(dataset_root).expanduser()
            if dataset_root is not None
            else None
        )
        self.paths = [str(path) for path in paths]
        self.path_metadata = {}
        self.metadata_visible_paths = []
        self.selected_index = None

    def has_loaded_data(self) -> bool:
        """Return whether a dataset is currently loaded."""
        return bool(self.paths)

    def path_count(self) -> int:
        """Return number of currently loaded dataset paths."""
        return len(self.paths)

    def set_path_metadata(
        self,
        mapping: dict[str, dict[str, object]],
    ) -> None:
        """Replace cached metadata for the currently loaded paths."""
        self.path_metadata = {
            str(path): dict(payload)
            for path, payload in mapping.items()
        }

    def set_metadata_visible_paths(self, paths: Iterable[str]) -> None:
        """Store current metadata-table visible row ordering."""
        self.metadata_visible_paths = [str(path) for path in paths]

    def visible_metadata_path(self, row: int) -> str | None:
        """Return visible metadata-table path for one row, if present."""
        if 0 <= int(row) < len(self.metadata_visible_paths):
            return self.metadata_visible_paths[int(row)]
        return None

    def source_index_for_path(self, path: str) -> int | None:
        """Return loaded-path index for a path, if the path is present."""
        try:
            return self.paths.index(str(path))
        except ValueError:
            return None

    def metadata_for_path(self, path: str) -> dict[str, object]:
        """Return cached metadata for one loaded path."""
        return self.path_metadata.get(str(path), {})

    def set_selected_index(
        self,
        index: int | None,
        *,
        path_count: int | None = None,
    ) -> int | None:
        """Store current selected dataset row, clamped when path count is known."""
        if index is None:
            self.selected_index = None
            return None
        try:
            value = int(index)
        except Exception:
            self.selected_index = None
            return None
        if path_count is not None:
            if path_count <= 0:
                self.selected_index = None
                return None
            value = min(max(value, 0), int(path_count) - 1)
        self.selected_index = value
        return value

    def update_metadata_source_availability(self, has_json: bool) -> str:
        """Update JSON availability and return the active source mode."""
        self.has_json_metadata_source = bool(has_json)
        if not self.has_json_metadata_source and self.metadata_source_mode == "json":
            self.metadata_source_mode = "path"
        elif self.has_json_metadata_source:
            preferred = self.preferred_metadata_source_mode
            if preferred not in {"path", "json"}:
                preferred = "json"
            self.metadata_source_mode = preferred
        return self.metadata_source_mode

    def request_metadata_source_mode(self, mode: str | None) -> bool:
        """Set requested metadata source mode and return whether it changed."""
        selected = str(mode or "path")
        if selected not in {"path", "json"}:
            selected = "path"
        if selected == "json" and not self.has_json_metadata_source:
            selected = "path"
        changed = selected != self.metadata_source_mode
        self.preferred_metadata_source_mode = selected
        self.metadata_source_mode = selected
        return changed

    def as_debug_dict(self) -> dict[str, Any]:
        """Return a compact debug snapshot of controller-owned dataset state."""
        return {
            "dataset_root": (
                str(self.dataset_root) if self.dataset_root is not None else None
            ),
            "path_count": len(self.paths),
            "metadata_source_mode": self.metadata_source_mode,
            "preferred_metadata_source_mode": self.preferred_metadata_source_mode,
            "has_json_metadata_source": self.has_json_metadata_source,
            "visible_metadata_rows": len(self.metadata_visible_paths),
        }

"""Background-subtraction utilities for TIFF metric processing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

import numpy as np

BackgroundSourceMode = Literal["single_file", "folder_library"]
BackgroundExposurePolicy = Literal["require_match"]
BackgroundNoMatchPolicy = Literal["fallback_raw"]


@dataclass(slots=True)
class BackgroundConfig:
    """Configuration for optional background subtraction."""

    enabled: bool = False
    source_mode: BackgroundSourceMode = "single_file"
    clip_negative: bool = True
    exposure_policy: BackgroundExposurePolicy = "require_match"
    no_match_policy: BackgroundNoMatchPolicy = "fallback_raw"


@dataclass(slots=True)
class BackgroundLibrary:
    """Loaded background references used for subtraction."""

    global_ref: Optional[np.ndarray] = None
    global_source_path: str | None = None
    refs_by_exposure_ms: dict[float, np.ndarray] = field(default_factory=dict)
    label_by_exposure_ms: dict[float, str] = field(default_factory=dict)
    source_paths_by_exposure_ms: dict[float, tuple[str, ...]] = field(
        default_factory=dict,
    )

    def clear(self) -> None:
        """Clear all loaded references."""
        self.global_ref = None
        self.global_source_path = None
        self.refs_by_exposure_ms.clear()
        self.label_by_exposure_ms.clear()
        self.source_paths_by_exposure_ms.clear()

    def has_any_reference(self) -> bool:
        """Return ``True`` if any reference is available."""
        return (
            self.global_ref is not None
            or bool(self.refs_by_exposure_ms)
        )

    def copy(self) -> BackgroundLibrary:
        """Return a deep copy of the background library arrays."""
        global_copy = (
            None
            if self.global_ref is None
            else np.array(self.global_ref, copy=True, order="C")
        )
        refs_copy = {
            key: np.array(value, copy=True, order="C")
            for key, value in self.refs_by_exposure_ms.items()
        }
        return BackgroundLibrary(
            global_ref=global_copy,
            global_source_path=self.global_source_path,
            refs_by_exposure_ms=refs_copy,
            label_by_exposure_ms=dict(self.label_by_exposure_ms),
            source_paths_by_exposure_ms=dict(self.source_paths_by_exposure_ms),
        )

    def shared_snapshot(self) -> BackgroundLibrary:
        """Return a lightweight snapshot that reuses the loaded arrays."""
        return BackgroundLibrary(
            global_ref=self.global_ref,
            global_source_path=self.global_source_path,
            refs_by_exposure_ms=dict(self.refs_by_exposure_ms),
            label_by_exposure_ms=dict(self.label_by_exposure_ms),
            source_paths_by_exposure_ms=dict(self.source_paths_by_exposure_ms),
        )


def freeze_background_array(array: np.ndarray) -> np.ndarray:
    """Return a contiguous float32 background array marked read-only."""
    frozen = np.asarray(array, dtype=np.float32, order="C")
    frozen.setflags(write=False)
    return frozen


def canonical_exposure_key(exposure_ms: object) -> Optional[float]:
    """Convert exposure value to a stable dictionary key."""
    try:
        value = float(exposure_ms)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(value):
        return None
    return float(round(value, 9))


def select_reference(
    exposure_ms: object,
    library: BackgroundLibrary,
    policy: BackgroundExposurePolicy = "require_match",
) -> Optional[np.ndarray]:
    """Select background reference for a target image.

    Parameters
    ----------
    exposure_ms : object
        Exposure value associated with the target image.
    library : BackgroundLibrary
        Loaded background references.
    policy : {"require_match"}, default="require_match"
        Exposure matching strategy.

    Returns
    -------
    numpy.ndarray or None
        Matching reference array, else ``None``.
    """
    if library.global_ref is not None:
        return library.global_ref

    if policy != "require_match":
        return None

    key = canonical_exposure_key(exposure_ms)
    if key is None:
        return None
    return library.refs_by_exposure_ms.get(key)


def validate_reference_shape(
    image_shape: tuple[int, ...],
    ref_shape: tuple[int, ...],
) -> bool:
    """Return whether image/reference shapes are compatible."""
    return tuple(image_shape) == tuple(ref_shape)


def apply_background(
    image: np.ndarray,
    reference: np.ndarray,
    clip_negative: bool = True,
) -> np.ndarray:
    """Subtract background from image and optionally clip negatives.

    Parameters
    ----------
    image : numpy.ndarray
        Source 2D image values.
    reference : numpy.ndarray
        Background reference image.
    clip_negative : bool, default=True
        If ``True``, clamp negative results to ``0``.

    Returns
    -------
    numpy.ndarray
        Background-corrected image array.
    """
    corrected = np.array(image, dtype=np.float32, copy=True, order="C")
    corrected -= np.asarray(reference, dtype=np.float32)
    if clip_negative:
        np.maximum(corrected, 0.0, out=corrected)
    return corrected

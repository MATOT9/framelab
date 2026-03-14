from __future__ import annotations

import numpy as np
import pytest

from framelab.background import (
    BackgroundLibrary,
    apply_background,
    canonical_exposure_key,
    select_reference,
    validate_reference_shape,
)


pytestmark = [pytest.mark.fast, pytest.mark.core]


def test_canonical_exposure_key_normalizes_and_rejects_invalid_values() -> None:
    assert canonical_exposure_key(10) == 10.0
    assert canonical_exposure_key("10.1234567894") == 10.123456789
    assert canonical_exposure_key(None) is None
    assert canonical_exposure_key(float("nan")) is None


def test_select_reference_prefers_global_reference() -> None:
    global_ref = np.full((2, 2), 7.0)
    library = BackgroundLibrary(
        global_ref=global_ref,
        refs_by_exposure_ms={10.0: np.ones((2, 2), dtype=np.float64)},
    )
    selected = select_reference(10.0, library)
    assert selected is global_ref


def test_select_reference_matches_exposure_and_handles_missing_values() -> None:
    reference = np.full((2, 2), 2.0)
    library = BackgroundLibrary(
        refs_by_exposure_ms={10.0: reference},
        label_by_exposure_ms={10.0: "10 ms"},
    )
    assert select_reference(10.0, library) is reference
    assert select_reference(20.0, library) is None
    assert select_reference(None, library) is None


def test_validate_reference_shape_requires_exact_match() -> None:
    assert validate_reference_shape((2, 3), (2, 3))
    assert not validate_reference_shape((2, 3), (3, 2))


def test_apply_background_clips_negative_values_when_enabled() -> None:
    image = np.array([[5.0, 3.0], [1.0, 0.0]])
    reference = np.array([[2.0, 4.0], [1.0, 1.0]])
    corrected = apply_background(image, reference, clip_negative=True)
    np.testing.assert_allclose(
        corrected,
        np.array([[3.0, 0.0], [0.0, 0.0]]),
    )


def test_apply_background_can_preserve_negative_values() -> None:
    image = np.array([[5.0, 3.0], [1.0, 0.0]])
    reference = np.array([[2.0, 4.0], [1.0, 1.0]])
    corrected = apply_background(image, reference, clip_negative=False)
    np.testing.assert_allclose(
        corrected,
        np.array([[3.0, -1.0], [0.0, -1.0]]),
    )


def test_background_library_copy_is_deep() -> None:
    library = BackgroundLibrary(
        global_ref=np.array([[1.0, 2.0]]),
        refs_by_exposure_ms={10.0: np.array([[3.0, 4.0]])},
        label_by_exposure_ms={10.0: "10 ms"},
    )
    copied = library.copy()
    assert copied is not library
    assert copied.label_by_exposure_ms == library.label_by_exposure_ms
    copied.global_ref[0, 0] = 99.0
    copied.refs_by_exposure_ms[10.0][0, 1] = 88.0
    assert float(library.global_ref[0, 0]) == 1.0
    assert float(library.refs_by_exposure_ms[10.0][0, 1]) == 4.0

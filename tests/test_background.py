from __future__ import annotations

import unittest

import numpy as np

from framelab.background import (
    BackgroundLibrary,
    apply_background,
    canonical_exposure_key,
    select_reference,
    validate_reference_shape,
)


class BackgroundHelpersTests(unittest.TestCase):
    def test_canonical_exposure_key_normalizes_and_rejects_invalid_values(self) -> None:
        self.assertEqual(canonical_exposure_key(10), 10.0)
        self.assertEqual(canonical_exposure_key("10.1234567894"), 10.123456789)
        self.assertIsNone(canonical_exposure_key(None))
        self.assertIsNone(canonical_exposure_key(float("nan")))

    def test_select_reference_prefers_global_reference(self) -> None:
        global_ref = np.full((2, 2), 7.0)
        library = BackgroundLibrary(
            global_ref=global_ref,
            refs_by_exposure_ms={10.0: np.ones((2, 2), dtype=np.float64)},
        )
        selected = select_reference(10.0, library)
        self.assertIs(selected, global_ref)

    def test_select_reference_matches_exposure_and_handles_missing_values(self) -> None:
        reference = np.full((2, 2), 2.0)
        library = BackgroundLibrary(
            refs_by_exposure_ms={10.0: reference},
            label_by_exposure_ms={10.0: "10 ms"},
        )
        self.assertIs(select_reference(10.0, library), reference)
        self.assertIsNone(select_reference(20.0, library))
        self.assertIsNone(select_reference(None, library))

    def test_validate_reference_shape_requires_exact_match(self) -> None:
        self.assertTrue(validate_reference_shape((2, 3), (2, 3)))
        self.assertFalse(validate_reference_shape((2, 3), (3, 2)))

    def test_apply_background_clips_negative_values_when_enabled(self) -> None:
        image = np.array([[5.0, 3.0], [1.0, 0.0]])
        reference = np.array([[2.0, 4.0], [1.0, 1.0]])
        corrected = apply_background(image, reference, clip_negative=True)
        np.testing.assert_allclose(
            corrected,
            np.array([[3.0, 0.0], [0.0, 0.0]]),
        )

    def test_apply_background_can_preserve_negative_values(self) -> None:
        image = np.array([[5.0, 3.0], [1.0, 0.0]])
        reference = np.array([[2.0, 4.0], [1.0, 1.0]])
        corrected = apply_background(image, reference, clip_negative=False)
        np.testing.assert_allclose(
            corrected,
            np.array([[3.0, -1.0], [0.0, -1.0]]),
        )

    def test_background_library_copy_is_deep(self) -> None:
        library = BackgroundLibrary(
            global_ref=np.array([[1.0, 2.0]]),
            refs_by_exposure_ms={10.0: np.array([[3.0, 4.0]])},
            label_by_exposure_ms={10.0: "10 ms"},
        )
        copied = library.copy()
        self.assertIsNot(copied, library)
        self.assertEqual(copied.label_by_exposure_ms, library.label_by_exposure_ms)
        copied.global_ref[0, 0] = 99.0
        copied.refs_by_exposure_ms[10.0][0, 1] = 88.0
        self.assertEqual(float(library.global_ref[0, 0]), 1.0)
        self.assertEqual(float(library.refs_by_exposure_ms[10.0][0, 1]), 4.0)


if __name__ == "__main__":
    unittest.main()

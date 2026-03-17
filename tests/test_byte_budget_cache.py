from __future__ import annotations

import numpy as np
import pytest

from framelab.byte_budget_cache import ByteBudgetCache


pytestmark = [pytest.mark.fast, pytest.mark.core]


def test_byte_budget_cache_evicts_least_recently_used_entries_by_bytes() -> None:
    cache = ByteBudgetCache[str](12)
    a = np.arange(3, dtype=np.uint16)
    b = np.arange(3, 6, dtype=np.uint16)
    c = np.arange(6, 9, dtype=np.uint16)

    assert cache.put("a", a)
    assert cache.put("b", b)
    np.testing.assert_array_equal(cache.get("a"), a)

    assert cache.put("c", c)

    assert cache.get("b") is None
    np.testing.assert_array_equal(cache.get("a"), a)
    np.testing.assert_array_equal(cache.get("c"), c)
    assert cache.bytes_used == 12


def test_byte_budget_cache_skips_entries_larger_than_budget() -> None:
    cache = ByteBudgetCache[str](4)
    huge = np.arange(3, dtype=np.uint16)

    assert not cache.put("huge", huge)
    assert len(cache) == 0
    assert cache.bytes_used == 0

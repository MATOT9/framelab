"""Small byte-budgeted LRU cache for NumPy-backed image arrays."""

from __future__ import annotations

from collections import OrderedDict
from typing import Generic, TypeVar

import numpy as np


K = TypeVar("K")


class ByteBudgetCache(Generic[K]):
    """Store arrays under an LRU policy constrained by total byte size."""

    def __init__(self, budget_bytes: int) -> None:
        self._budget_bytes = max(0, int(budget_bytes))
        self._items: OrderedDict[K, np.ndarray] = OrderedDict()
        self._bytes_used = 0

    @property
    def budget_bytes(self) -> int:
        """Return the configured byte budget."""
        return self._budget_bytes

    @property
    def bytes_used(self) -> int:
        """Return current cache occupancy in bytes."""
        return self._bytes_used

    def __len__(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        """Remove all cached arrays."""
        self._items.clear()
        self._bytes_used = 0

    def get(self, key: K) -> np.ndarray | None:
        """Return one cached array and mark it as recently used."""
        value = self._items.get(key)
        if value is None:
            return None
        self._items.move_to_end(key)
        return value

    def put(self, key: K, value: np.ndarray) -> bool:
        """Insert one array if it fits within the configured budget."""
        array = np.asarray(value)
        size_bytes = int(array.nbytes)
        if self._budget_bytes <= 0 or size_bytes > self._budget_bytes:
            self.pop(key)
            return False

        previous = self._items.pop(key, None)
        if previous is not None:
            self._bytes_used -= int(previous.nbytes)

        self._items[key] = array
        self._bytes_used += size_bytes
        self._items.move_to_end(key)
        self._evict_to_budget()
        return True

    def pop(self, key: K) -> np.ndarray | None:
        """Remove and return one cached array if present."""
        value = self._items.pop(key, None)
        if value is not None:
            self._bytes_used -= int(value.nbytes)
        return value

    def _evict_to_budget(self) -> None:
        while self._bytes_used > self._budget_bytes and self._items:
            _key, value = self._items.popitem(last=False)
            self._bytes_used -= int(value.nbytes)

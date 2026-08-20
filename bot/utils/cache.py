from __future__ import annotations

from collections import OrderedDict
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class LRUCache(OrderedDict, Generic[K, V]):
    """Tiny insertion-order cache used for snipe/spam windows."""

    def __init__(self, maxsize: int = 256) -> None:
        super().__init__()
        self.maxsize = maxsize

    def __setitem__(self, key: K, value: V) -> None:  # type: ignore[override]
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        while len(self) > self.maxsize:
            self.popitem(last=False)

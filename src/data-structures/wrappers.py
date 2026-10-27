"""Reusable wrappers for the most common cross-cutting patterns in the samples.

See ANALYSIS.md for the evidence and the full design. Three wrappers are
implemented here (standard library only, Python 3.8+):

* ``FakeClock`` / ``Clock``: time injection. Replaces the ``t = [0];
  clock=lambda: t[0]`` and ``sleep=slept.append`` test hacks used in samples
  12, 13, 36 and 37. It is also the default clock type for the other wrappers.
* ``TTLCache`` / ``ttl_cache``: an expiring, optionally size-bounded (LRU)
  cache. It unifies ``ttl_cache`` and ``AlertDeduper`` (37),
  ``IdempotencyStore`` (36) and the OrderedDict LRU (09).
* ``TopK`` / ``top_k``: a bounded min-heap that keeps the k largest items.
  It covers the streaming top-k code in 07, 08, 17 and 33.

The original 37 sample files are intentionally left unchanged.
"""
from __future__ import annotations

import functools
import heapq
import itertools
import time
from collections import OrderedDict
from typing import (Any, Callable, Dict, Generic, Hashable, Iterable, List,
                    Optional, Tuple, TypeVar)

__all__ = ["Clock", "FakeClock", "TTLCache", "ttl_cache", "TopK", "top_k"]

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")
T = TypeVar("T")
R = TypeVar("R")

_MISSING = object()

# --------------------------------------------------------------------------
# 1. Time injection
# --------------------------------------------------------------------------

#: Any zero-arg callable returning seconds as a float, e.g. ``time.monotonic``.
Clock = Callable[[], float]


class FakeClock:
    """Deterministic, manually advanced clock for tests.

    Call the instance to read the time. That makes it a drop-in ``clock=``
    argument for TokenBucket, SlidingWindowLog, IdempotencyStore, ttl_cache
    and the like. ``sleep`` advances the time and records the delay, so the
    same object also works as a ``sleep=`` argument (see ``call_with_retry``
    in sample 36).

    >>> clk = FakeClock()
    >>> clk(), clk.advance(5), clk()
    (0.0, 5.0, 5.0)
    """

    def __init__(self, start: float = 0.0) -> None:
        self.now: float = float(start)
        self.sleeps: List[float] = []

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        """Move time forward by ``seconds``. Returns the new time."""
        if seconds < 0:
            raise ValueError("FakeClock cannot go backwards")
        self.now += seconds
        return self.now

    def set(self, t: float) -> float:
        """Jump to absolute time ``t``, which must not be earlier than now."""
        if t < self.now:
            raise ValueError(f"cannot rewind clock from {self.now} to {t}")
        self.now = float(t)
        return self.now

    def sleep(self, seconds: float) -> None:
        """Stand-in for ``time.sleep``: records the delay, then advances."""
        self.sleeps.append(seconds)
        self.advance(seconds)

    def __repr__(self) -> str:
        return f"FakeClock(now={self.now})"


# --------------------------------------------------------------------------
# 2. TTL cache (+ optional LRU bound) and decorator
# --------------------------------------------------------------------------

class TTLCache(Generic[K, V]):
    """Mapping whose entries expire ``ttl`` seconds after they are written.

    * An entry counts as live while ``expires_at > clock()``. Samples 36 and
      37 use the same rule.
    * When ``maxsize`` is set, the least recently used live entry is evicted
      on overflow. With ``ttl=None`` this is a plain LRU cache, like sample 09.
    * Expired entries are removed lazily on access. ``purge()`` removes them
      all at once.

    Typical uses:

    * Memoize or replay results: ``get_or_compute(key, fn)``. This is
      sample 36's ``IdempotencyStore.run``.
    * Suppress duplicates within a window: ``add_if_absent(fp)``. This is
      sample 37's ``AlertDeduper.should_send``.
    """

    def __init__(self, ttl: Optional[float], maxsize: Optional[int] = None,
                 clock: Clock = time.monotonic) -> None:
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be > 0 or None")
        if maxsize is not None and maxsize <= 0:
            raise ValueError("maxsize must be > 0 or None")
        self.ttl = ttl
        self.maxsize = maxsize
        self.clock = clock
        self._data: "OrderedDict[K, Tuple[V, float]]" = OrderedDict()

    def _expiry(self, now: float) -> float:
        return float("inf") if self.ttl is None else now + self.ttl

    def _live(self, key: K, now: float) -> Any:
        hit = self._data.get(key)
        if hit is None:
            return _MISSING
        value, expires_at = hit
        if expires_at <= now:
            del self._data[key]
            return _MISSING
        self._data.move_to_end(key)          # mark most recently used
        return value

    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        """Return the live value for ``key``, otherwise ``default``."""
        v = self._live(key, self.clock())
        return default if v is _MISSING else v

    def set(self, key: K, value: V) -> None:
        """Insert or overwrite ``key``. This resets its TTL."""
        now = self.clock()
        self._data[key] = (value, self._expiry(now))
        self._data.move_to_end(key)
        if self.maxsize is not None and len(self._data) > self.maxsize:
            self.purge(now)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)   # evict LRU

    def get_or_compute(self, key: K, fn: Callable[[], V]) -> V:
        """Return the cached value, or call ``fn()`` once and cache the result."""
        v = self._live(key, self.clock())
        if v is not _MISSING:
            return v
        value = fn()
        self.set(key, value)
        return value

    def add_if_absent(self, key: K, value: Any = True) -> bool:
        """Insert only if ``key`` has no live entry. Returns True if inserted.

        This is the dedup primitive: True means first sighting in the window.
        """
        if self._live(key, self.clock()) is not _MISSING:
            return False
        self.set(key, value)
        return True

    def purge(self, now: Optional[float] = None) -> int:
        """Drop every expired entry. Returns how many were removed."""
        now = self.clock() if now is None else now
        dead = [k for k, (_, exp) in self._data.items() if exp <= now]
        for k in dead:
            del self._data[k]
        return len(dead)

    def __contains__(self, key: object) -> bool:
        return self._live(key, self.clock()) is not _MISSING  # type: ignore[arg-type]

    def __len__(self) -> int:
        """Number of live entries. This purges expired ones first."""
        self.purge()
        return len(self._data)

    def clear(self) -> None:
        self._data.clear()


def ttl_cache(ttl: Optional[float], maxsize: Optional[int] = None,
              clock: Clock = time.monotonic
              ) -> Callable[[Callable[..., R]], Callable[..., R]]:
    """Decorator that memoizes ``fn`` for ``ttl`` seconds per argument tuple.

    It generalizes sample 37's ``ttl_cache``: keyword arguments are supported,
    the size can be bounded, and the underlying ``TTLCache`` is exposed as
    ``wrapper.cache`` so tests can inspect or clear it. Arguments must be
    hashable.
    """
    def deco(fn: Callable[..., R]) -> Callable[..., R]:
        cache: TTLCache[Hashable, R] = TTLCache(ttl, maxsize, clock)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> R:
            key = (args, tuple(sorted(kwargs.items()))) if kwargs else args
            return cache.get_or_compute(key, lambda: fn(*args, **kwargs))

        wrapper.cache = cache  # type: ignore[attr-defined]
        return wrapper
    return deco


# --------------------------------------------------------------------------
# 3. Bounded top-k heap
# --------------------------------------------------------------------------

class TopK(Generic[T]):
    """Keep the ``k`` largest items seen so far, using O(k) memory.

    Internally this is a size-k min-heap of ``(key(item), seq, item)``. The
    smallest kept item sits at the root and is evicted when something larger
    arrives. The ``seq`` counter breaks ties, so items themselves never need
    to be comparable: dicts, (value, count) tuples and the like all work.
    Like sample 08 (``val > heap[0]``), a new item whose key only *ties* the
    current k-th key is rejected, so the first-come item wins. When a strictly
    larger item arrives, the oldest of the equal-key items at the root is
    evicted.

    ``push`` returns the current k-th largest item (the heap root), which is
    exactly what ``KthLargest.add`` returns in sample 08.
    """

    def __init__(self, k: int, key: Optional[Callable[[T], Any]] = None,
                 items: Iterable[T] = ()) -> None:
        if k <= 0:
            raise ValueError("k must be >= 1")
        self.k = k
        self.key: Callable[[T], Any] = key if key is not None else (lambda x: x)
        self._heap: List[Tuple[Any, int, T]] = []
        self._seq = itertools.count()
        for it in items:
            self.push(it)

    def push(self, item: T) -> T:
        """Offer ``item``. Returns the current k-th largest item (the root)."""
        entry = (self.key(item), next(self._seq), item)
        if len(self._heap) < self.k:
            heapq.heappush(self._heap, entry)
        elif entry[0] > self._heap[0][0]:
            heapq.heapreplace(self._heap, entry)
        return self._heap[0][2]

    def kth(self) -> T:
        """The smallest kept item. Once k items have been seen, this is the
        k-th largest. Raises IndexError if the heap is empty."""
        if not self._heap:
            raise IndexError("TopK is empty")
        return self._heap[0][2]

    def items(self) -> List[T]:
        """Kept items, largest first. Ties are listed in insertion order."""
        # Sort by insertion order, then stable-sort by key descending, so
        # equal keys keep insertion order. Works for any orderable key.
        by_seq = sorted(self._heap, key=lambda e: e[1])
        return [e[2] for e in sorted(by_seq, key=lambda e: e[0], reverse=True)]

    def __len__(self) -> int:
        return len(self._heap)

    def __iter__(self):
        return iter(self.items())


def top_k(iterable: Iterable[T], k: int,
          key: Optional[Callable[[T], Any]] = None) -> List[T]:
    """Return the ``k`` largest items of ``iterable``, largest first.

    ``top_k(Counter(xs).items(), k, key=lambda kv: kv[1])`` gives the k most
    frequent elements with their counts (samples 07, 17, 33).
    Returns ``[]`` when ``k <= 0``.
    """
    if k <= 0:
        return []
    return TopK(k, key, iterable).items()


# --------------------------------------------------------------------------
# Usage demo (also a smoke test): python wrappers.py
# --------------------------------------------------------------------------

if __name__ == "__main__":
    from collections import Counter

    # FakeClock replaces `t = [0]; clock=lambda: t[0]` (samples 12/13/36/37)
    clk = FakeClock()
    assert clk() == 0.0
    clk.advance(2.5)
    assert clk() == 2.5
    clk.sleep(0.5)
    assert clk() == 3.0 and clk.sleeps == [0.5]

    # TTLCache as sample 36's IdempotencyStore: run side effect once per TTL
    clk = FakeClock()
    store: TTLCache[str, str] = TTLCache(ttl=60, clock=clk)
    created: List[str] = []
    mk = lambda: created.append("vol") or f"vol-{len(created)}"
    assert store.get_or_compute("req-1", mk) == store.get_or_compute("req-1", mk) == "vol-1"
    clk.set(61)
    assert store.get_or_compute("req-1", mk) == "vol-2"

    # TTLCache as sample 37's AlertDeduper (300s suppression window)
    clk = FakeClock()
    dd: TTLCache[tuple, bool] = TTLCache(ttl=300, clock=clk)
    fp = ("api", "5xx", "P1")
    assert dd.add_if_absent(fp) is True
    clk.set(120)
    assert dd.add_if_absent(fp) is False
    clk.set(301)
    assert dd.add_if_absent(fp) is True

    # ttl_cache decorator, matching the self-test in sample 37
    clk, lookups = FakeClock(), []

    @ttl_cache(ttl=30, clock=clk)
    def resolve(name: str) -> str:
        lookups.append(name)
        return f"10.0.0.{len(lookups)}"

    assert resolve("db") == resolve("db") == "10.0.0.1"
    clk.set(31)
    assert resolve("db") == "10.0.0.2" and len(lookups) == 2

    # TTLCache(ttl=None, maxsize=2) behaves like sample 09's LRU
    lru: TTLCache[int, int] = TTLCache(ttl=None, maxsize=2)
    lru.set(1, 1); lru.set(2, 2)
    assert lru.get(1) == 1
    lru.set(3, 3)                               # evicts 2
    assert lru.get(2) is None and lru.get(3) == 3

    # TopK, matching samples 08 and 07
    kl = TopK(3, items=[4, 5, 8, 2])
    assert [kl.push(x) for x in (3, 5, 10, 9, 4)] == [4, 5, 5, 8, 8]
    pairs = top_k(Counter([1, 1, 1, 2, 2, 3]).items(), 2, key=lambda kv: kv[1])
    assert [v for v, _ in pairs] == [1, 2]
    assert top_k([3, 2, 1, 5, 6, 4], 2) == [6, 5]

    print("wrappers.py demo: all asserts passed")

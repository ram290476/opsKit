"""Tests for wrappers.py.

Run either way from the repo root:
    python tests/test_wrappers.py
    python -m pytest tests/        # if pytest is installed

Besides unit tests, several tests load an original sample (read-only, through
importlib) and check that the wrapper behaves the same on random inputs.
That supports the refactor map in ANALYSIS.md.
"""
from __future__ import annotations

import importlib.util
import random
import sys
import traceback
from collections import Counter
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wrappers import FakeClock, TTLCache, TopK, top_k, ttl_cache  # noqa: E402


def load_sample(prefix: str) -> ModuleType:
    """Import a sample like '08_*.py' by number. This runs its own asserts."""
    (path,) = ROOT.glob(f"{prefix}_*.py")
    spec = importlib.util.spec_from_file_location(f"sample_{prefix}", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def expect_raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc:
        return
    raise AssertionError(f"{fn.__name__} did not raise {exc.__name__}")


# ---------------------------------------------------------------- FakeClock

def test_fake_clock_basics():
    c = FakeClock(10)
    assert c() == 10.0
    assert c.advance(5) == 15.0
    assert c.set(20) == 20.0
    c.sleep(1.5)
    assert c() == 21.5 and c.sleeps == [1.5]
    expect_raises(ValueError, c.advance, -1)
    expect_raises(ValueError, c.set, 0)


def test_fake_clock_drives_original_token_bucket():
    tb_mod = load_sample("12")
    c = FakeClock()
    tb = tb_mod.TokenBucket(rate=1, capacity=2, clock=c)
    assert [tb.allow() for _ in range(3)] == [True, True, False]
    c.advance(1)
    assert tb.allow() is True and tb.allow() is False


def test_fake_clock_as_sleep_for_original_retry():
    m = load_sample("36")
    c, calls = FakeClock(), []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise m.TransientError("503")
        return "ok"

    assert m.call_with_retry(flaky, sleep=c.sleep) == "ok"
    assert len(c.sleeps) == 2 and c() == sum(c.sleeps)


# ---------------------------------------------------------------- TTLCache

def test_ttl_expiry_boundary():
    c = FakeClock()
    cache = TTLCache(ttl=10, clock=c)
    cache.set("a", 1)
    c.set(9.999)
    assert cache.get("a") == 1 and "a" in cache
    c.set(10)                               # expires_at <= now: gone
    assert cache.get("a") is None and "a" not in cache
    assert cache.get("a", "dflt") == "dflt"


def test_ttl_set_resets_expiry_and_len_purges():
    c = FakeClock()
    cache = TTLCache(ttl=10, clock=c)
    cache.set("a", 1); cache.set("b", 2)
    c.set(5); cache.set("a", 11)            # a now expires at 15
    c.set(12)
    assert len(cache) == 1 and cache.get("a") == 11
    assert cache.purge() == 0
    c.set(100)
    assert len(cache) == 0


def test_lru_eviction_matches_original_samples():
    m9 = load_sample("09")
    ours = TTLCache(ttl=None, maxsize=3)
    ref = m9.LRUCache(3)
    rng = random.Random(7)
    for _ in range(2000):
        k = rng.randrange(8)
        if rng.random() < 0.5:
            v = rng.randrange(100)
            ours.set(k, v); ref.put(k, v)
        else:
            assert ours.get(k, -1) == ref.get(k)


def test_maxsize_prefers_dropping_expired_over_live():
    c = FakeClock()
    cache = TTLCache(ttl=10, maxsize=2, clock=c)
    cache.set("old", 1)
    c.set(5); cache.set("live", 2)
    c.set(11)                               # "old" expired, "live" not
    cache.set("new", 3)
    assert cache.get("live") == 2 and cache.get("new") == 3


def test_get_or_compute_matches_idempotency_store():
    m = load_sample("36")
    c = FakeClock()
    ref = m.IdempotencyStore(ttl=60, clock=c)
    ours = TTLCache(ttl=60, clock=c)
    n_ref, n_ours = [0], [0]

    def bump(counter):
        counter[0] += 1
        return counter[0]

    rng = random.Random(1)
    for _ in range(500):
        c.advance(rng.choice([0, 1, 5, 30, 61]))
        key = f"req-{rng.randrange(4)}"
        assert ref.run(key, lambda: bump(n_ref)) == \
            ours.get_or_compute(key, lambda: bump(n_ours))


def test_add_if_absent_matches_alert_deduper():
    m = load_sample("37")
    c = FakeClock()
    ref = m.AlertDeduper(window=300)
    ours = TTLCache(ttl=300, clock=c)
    rng = random.Random(2)
    for _ in range(500):
        c.advance(rng.choice([0, 50, 150, 299, 300, 301]))
        alert = {"service": rng.choice("ab"), "name": "5xx",
                 "severity": rng.choice(["P1", "P2"])}
        fp = (alert["service"], alert["name"], alert["severity"])
        assert ref.should_send(alert, c()) == ours.add_if_absent(fp)


def test_ttl_cache_decorator_kwargs_and_cache_attr():
    c, calls = FakeClock(), []

    @ttl_cache(ttl=30, clock=c)
    def f(x, scale=1):
        calls.append((x, scale))
        return x * scale

    assert f(2) == f(2) == 2
    assert f(2, scale=3) == f(2, scale=3) == 6
    assert len(calls) == 2
    c.set(30)
    assert f(2) == 2 and len(calls) == 3
    f.cache.clear()
    f(2)
    assert len(calls) == 4
    assert f.__name__ == "f"


def test_ttl_cache_validation():
    expect_raises(ValueError, TTLCache, 0)
    expect_raises(ValueError, TTLCache, 5, 0)


# ---------------------------------------------------------------- TopK

def test_topk_matches_original_kth_largest():
    m = load_sample("08")
    rng = random.Random(3)
    for _ in range(50):
        k = rng.randint(1, 6)
        seed = [rng.randrange(50) for _ in range(rng.randrange(10))]
        ref, ours = m.KthLargest(k, seed), TopK(k, items=seed)
        for _ in range(100):
            x = rng.randrange(50)
            assert ref.add(x) == ours.push(x)
        nums = [rng.randrange(100) for _ in range(rng.randint(k, 40))]
        assert m.kth_largest(nums, k) == TopK(k, items=nums).kth()


def test_top_k_frequency_counts_match_original():
    m = load_sample("07")
    rng = random.Random(4)
    for _ in range(200):
        nums = [rng.randrange(6) for _ in range(rng.randrange(30))]
        k = rng.randint(1, 4)
        ref = m.top_k_heap(nums, k)
        ours = [v for v, _ in top_k(Counter(nums).items(), k, key=lambda kv: kv[1])]
        cnt = Counter(nums)
        # Tie order can differ, but the multiset of counts must match.
        assert sorted(cnt[v] for v in ref) == sorted(cnt[v] for v in ours)


def test_topk_order_ties_and_unorderable_items():
    t = TopK(3, key=lambda d: d["n"])
    for i, n in enumerate([5, 1, 5, 9, 5]):
        t.push({"id": i, "n": n})
    assert [d["n"] for d in t.items()] == [9, 5, 5]
    # The third 5 (id 4) only ties the root, so it is rejected (as in 08).
    assert [d["id"] for d in t.items()] == [3, 0, 2]
    assert len(t) == 3 and [d["id"] for d in t] == [3, 0, 2]
    t.push({"id": 5, "n": 7})              # strictly larger: evicts oldest 5
    assert [d["id"] for d in t.items()] == [3, 5, 2]


def test_topk_edges():
    assert top_k([], 3) == []
    assert top_k([1, 2], 0) == []
    assert top_k([1, 2], 5) == [2, 1]
    expect_raises(ValueError, TopK, 0)
    expect_raises(IndexError, TopK(2).kth)


# ---------------------------------------------------------------- runner

def _main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception:
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())

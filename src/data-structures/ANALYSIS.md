# Cross-cutting patterns in the 37 Python samples

**Scope:** `01_*.py` to `37_*.py` (1,474 lines). None of the sample files were modified.
**Method:** I read every file by hand, and also ran `tools/analyze_patterns.py`, an AST scanner with one explicit rule per pattern (imports, call names, parameter names, module-level `assert`s, `try`/`raise` inside defs, and so on). The counts below come from that scanner. They were checked against the hand reading, and the notes say where an idiom can only be approximated with AST. To reproduce: `python tools/analyze_patterns.py` (add `--json` for machine-readable output).

Samples are referred to by their two-digit prefix. For example, `12` means `12_p10_rate_limiter_token_bucket.py`.

## 1. Ranked patterns

| # | Pattern | Count | Samples |
|---|---------|------:|---------|
| 1 | Assert-based self-tests (module-level `assert`) | **36** | 01–08, 10–37 (all except 09; its test lives in 10) |
| 2 | Input validation / guard clauses | **8** | 11, 14, 17, 18, 28, 32, 33, 35 |
| 3 | Time & randomness injection (`clock=`/`sleep=`/`rng=` params, or explicit `now`/`ts` args) | **7** | 12, 13, 15, 16, 24, 36, 37 |
| 4 | Intervals: sort-and-sweep | **7** | 01, 02, 03, 04, 05, 06, 29 |
| 5 | Running min/max tracking (`peak = max(peak, …)`, `min_freq`, `max(key=)`) | **7** | 02, 04, 05, 06, 11, 15, 24 |
| 6 | Hash-map grouping (`defaultdict` / `setdefault`) | **7** | 11, 18, 20, 22, 27, 33, 34 |
| 7 | Heap / priority queue (`heapq`) | **6** | 01, 07, 08, 21, 24, 29 |
| 8 | Deque / ring buffer | **6** | 13, 16, 20, 25, 31, 34 |
| 9 | Counters & top-k (`Counter`, `most_common`, size-k heap) | **6** | 07, 08, 17, 24, 27, 33 (top-k selection specifically: 07, 08, 17, 33) |
| 10 | Caching / memoization | **5** | 09, 10, 11, 36, 37 |
| 11 | Graph traversal (topo sort, BFS/DFS, Dijkstra, union-find) | **5** | 18, 19, 20, 21, 22 |
| 12 | Error handling (`raise` on bad state / `try`-`except`) | **5** | 18, 30, 31, 35, 36 (`try` inside logic: 31, 36; tests that expect an exception: 18, 30, 36) |
| 13 | Sliding windows (time- or count-based) | **4** | 13, 16, 25, 34 |
| 14 | Stack / LIFO | **4** | 19, 20, 28, 35 |
| 15 | Fake clock in tests (`t=[0]; clock=lambda: t[0]`, `sleep=slept.append`) | **4** | 12, 13, 36, 37 |
| 16 | Hash map + ordered eviction (OrderedDict / DLL: LRU, LFU) | **3** | 09, 10, 11 |
| 17 | Dedup / TTL / idempotency | **3** | 27, 36, 37 (explicit TTL: 36, 37) |
| 18 | Two pointers / index scan | **3** | 02, 03, 05 |
| 19 | Same asserts run against several implementations (`for f in (a, b):`) | **3** | 02, 07, 10 |
| 20 | Retries with backoff / attempt limits | **2** | 31, 36 |
| 21 | `bisect` on a sorted list | 2 | 14, 29 |
| 22 | `hashlib` hashing (ring, Bloom) | 2 | 14, 26 |
| 23 | Regex parsing | 2 | 17, 33 |
| 24 | Timing / benchmarking (`perf_counter`, `timeit`, `time.time()`) | **0** | none |

## 2. Notes on each pattern

1. **Assert self-tests (36).** Every sample ends with bare module-level `assert`s, so it tests itself on import. Running each file on its own shows that `10_*.py` raises `NameError: LRUCache`, because its test loop also exercises the class from `09_*.py`. The document split one code block into two tables. There is no shared runner, and a failure stops at the first assert with no name for the case that broke.
2. **Input validation (8).** These are ad-hoc and each sample does it differently: `if self.cap <= 0: return` (11), an empty ring returns `None` (14), unparseable log lines are counted or skipped (17, 33), `raise ValueError` for a cycle or for no older version (18, 35), bracket validation with line and column (28), and a recursive type schema (32). There is no common "reject bad args" helper. Most functions trust their input, for example `insert()` in 05 assumes the list is already sorted.
3. **Time / RNG injection (7).** This is the most consistent design idiom. `clock=time.monotonic` is used in 12, 13 and 36 (`IdempotencyStore`) and 37 (`ttl_cache`). `sleep=time.sleep` and `rng=random` appear in 36, and `rng=random` in 15. Explicit `now`/`ts` arguments are used in 16, 24 and 37 (`AlertDeduper`). Tests fake time with a mutable one-element list (pattern 15), copied four times.
4. **Intervals (7).** These sort by start (01–04) or by end (06) and then do a single pass that compares each interval with the last kept one. They share the same "touching is not overlapping" rule (`<=` vs `<`). 29 uses `bisect` over merged freeze windows.
5. **Running min/max (7).** Peak concurrency (02), extending the merged end (04, 05), the greedy `prev_end` (06), `min_freq` (11), `max`/`min(…, key=)` for weighted-RR and least-connections (15), and `max(counts)` (24). A min-heap root plays the same role in 01, 08 and 29. These are small inline idioms, and a wrapper adds little.
6. **Hash-map grouping (7).** `defaultdict(list)` builds adjacency and reverse graphs (18, 20), groups (22 `setdefault`, 27), and per-key series (33, 34). `defaultdict(OrderedDict)` holds the LFU buckets (11).
7. **Heap / PQ (6).** These are min-heaps of tuples, sometimes with an `itertools.count()` tie-breaker (24), used for size-k top-k (07, 08), earliest-free resources (01, 29), Dijkstra (21) and timed scheduling (24). Each sample re-implements the push-or-replace-root logic.
8. **Deque / ring buffer (6).** `deque` serves as a time-window log (13, 16), a BFS queue (20), a retry queue (31) and a fixed-size window via `maxlen` (25, 31, 34). 25 also hand-rolls a ring buffer that keeps a running total.
9. **Counters / top-k (6).** `Counter` plus `most_common(k)` appears in 17 and 33, a heap or buckets in 07, the k-th largest in a stream in 08, and plain counting in 24 and 27.
10. **Caching (5).** OrderedDict LRU (09), hash map plus DLL LRU (10), LFU (11), a TTL replay store (36) and a TTL memoize decorator (37). They all follow the same "hit? return; else compute, store, maybe evict" shape.
11. **Graphs (5).** Kahn's topological waves (18), three-colour DFS (19), BFS by hops plus iterative DFS (20), Dijkstra (21) and union-find (22). Each takes a different graph shape (`{n: [deps]}`, edge pairs, or `{u: [(v, w)]}`).
12. **Error handling (5).** `raise ValueError` / `RuntimeError` on bad state (18, 30, 35), and catch, count and dead-letter (31) or catch and retry (36). Tests check for exceptions with a hand-written `try: …; raise AssertionError … except` block (18, 30, 36).
13. **Sliding windows (4).** A time-based log evicted from the left (13 `SlidingWindowLog`, 16 `ErrorRateWindow`), a weighted fixed-window estimate (13 `SlidingWindowCounter`), and count-based windows (25 ring mean, 34 `deque(maxlen=window)`). The rate limiter in 12 (token bucket) is a close relative.
14. **Stack (4).** DFS path (19), DFS work stack (20), bracket matching (28) and a version-history stack for rollback (35).
15. **Fake clocks (4).** `t = [0]` plus `clock=lambda: t[0]` (12, 13, 36, 37) and `sleep=slept.append` (36). This is the same boilerplate each time.
16. **Ordered eviction (3).** These are the textbook LRU and LFU structures. They overlap with pattern 10.
17. **Dedup / TTL (3).** `dict.fromkeys` keeps order while removing duplicates (27, 37). Idempotency keys with a TTL (36) and alert fingerprints with a suppression window (37) work the same way: they key on a value and check `expires > now`.
18. **Two pointers (3).** The merge-style `j` pointer over sorted ends (02), a three-phase index scan (05) and an adjacent-pair `zip(xs, xs[1:])` (03). AST can only approximate this idiom (`while i < n …` or `zip(…[1:])`). 27 (two-sum) uses a hash-map complement lookup, not two pointers.
19. **Multi-implementation tests (3).** `for f in (impl_a, impl_b): assert …` (02, 07, 10). This is a natural place for a table-driven test helper.
20. **Retries (2).** 36 uses full-jitter exponential backoff with an injectable `sleep`/`rng`. 31 re-queues failed messages up to `max_attempts`, then sends them to a DLQ. Only two samples, but it is the classic cross-cutting concern for SRE code.
21–23. `bisect` (14, 29), `hashlib` (14, 26) and regex (17, 33) are each used in only two samples and are domain-specific.
24. **Timing (0).** No sample measures its own runtime. Time appears only as injected logical clocks, so a `timed()` decorator would add something new, not factor out existing code.

## 3. Proposed wrapper design

★ = implemented in `wrappers.py` (with tests in `tests/test_wrappers.py`). The others are proposals.

| Wrapper | Signature | Description |
|---|---|---|
| ★ Clock / FakeClock | `Clock = Callable[[], float]`<br>`class FakeClock: __init__(start: float = 0.0); __call__() -> float; advance(seconds) -> float; set(t) -> float; sleep(seconds) -> None; sleeps: list[float]` | Standard clock type plus a deterministic test clock. One object works as both `clock=` and `sleep=`, replacing the `t=[0]` and `slept.append` boilerplate. |
| ★ TTLCache | `class TTLCache(Generic[K, V]): __init__(ttl: float \| None, maxsize: int \| None = None, clock: Clock = time.monotonic); get(key, default=None); set(key, value); get_or_compute(key, fn) -> V; add_if_absent(key, value=True) -> bool; purge(now=None) -> int; __contains__; __len__; clear()` | An expiring map with an optional LRU bound. `get_or_compute` is idempotent replay, `add_if_absent` is dedup within a window, and `ttl=None, maxsize=n` gives a plain LRU. |
| ★ ttl_cache | `ttl_cache(ttl: float \| None, maxsize: int \| None = None, clock: Clock = time.monotonic) -> Callable[[F], F]` | Memoizing decorator built on `TTLCache`. Supports kwargs and exposes `wrapper.cache`. |
| ★ TopK / top_k | `class TopK(Generic[T]): __init__(k: int, key: Callable[[T], Any] \| None = None, items: Iterable[T] = ()); push(item) -> T; kth() -> T; items() -> list[T]`<br>`top_k(iterable, k, key=None) -> list[T]` | A bounded size-k min-heap with a sequence tie-breaker, so items need not be comparable. `push` returns the current k-th largest, as `KthLargest.add` does. |
| MinHeap / PriorityQueue | `class PriorityQueue(Generic[T]): push(item: T, priority: Any) -> None; pop() -> tuple[Any, T]; peek() -> tuple[Any, T]; pop_until(limit) -> list[tuple[Any, T]]; __len__; __bool__` | A stable `heapq` wrapper (priority, seq, item) for schedulers, Dijkstra and worker pools. |
| retry_with_backoff | `retry_with_backoff(attempts: int = 5, base: float = 0.1, cap: float = 10.0, retry_on: tuple[type[BaseException], ...] = (Exception,), sleep: Callable[[float], None] = time.sleep, rng: random.Random = random) -> Callable[[F], F]`<br>`backoff_delays(n, base, cap, rng) -> Iterator[float]` | Decorator with full-jitter exponential backoff that re-raises after the last attempt. Pairs with `FakeClock.sleep` in tests. |
| SlidingWindow | `class SlidingWindow: __init__(window: float, clock: Clock = time.monotonic); add(value: float = 1.0, ts: float \| None = None); count(now=None) -> int; total(now=None) -> float; rate(pred=None, now=None) -> float` | A time-based deque window with running totals and left eviction (`ts <= now - window`). |
| SlidingWindowCounter | `class SlidingWindowCounter: __init__(limit: int, window: float, clock: Clock = time.monotonic); allow(cost: int = 1) -> bool; estimate(now=None) -> float` | An O(1)-memory weighted two-bucket rate estimate (13). |
| RingStats | `class RingStats: __init__(capacity: int); push(x: float); items() -> list[float]; mean() -> float; min() -> float; max() -> float` | A fixed-size, count-based window with a running sum (25, 34). |
| validate_inputs / require | `require(cond: bool, msg: str, exc: type[Exception] = ValueError) -> None`<br>`validate_inputs(**checks: Callable[[Any], bool]) -> Callable[[F], F]` | One-line precondition checks, and a decorator that validates named arguments before the call (for example `k=lambda k: k > 0`). |
| interval helpers | `sort_intervals(xs, by="start" \| "end") -> list`; `merge_intervals(xs, touching=True) -> list[list]`; `max_overlap(xs) -> int`; `overlaps(a, b, touching_ok=True) -> bool` | Shared sort-and-sweep primitives that encode the "touching is not overlap" rule in one place. |
| graph helpers | `topo_waves(nodes, edges) -> list[list]` (raises `CycleError`); `bfs_levels(adj, start, max_hops=None) -> dict`; `reverse_graph(adj) -> dict[list]`; `find_cycle(adj) -> list \| None` | Common adjacency-dict algorithms with a single graph shape. |
| timed | `timed(fn=None, *, clock: Clock = time.perf_counter, sink: Callable[[str, float], None] \| None = None)` | A decorator that records wall time per call (for example to `fn.timings`). New capability: no sample benchmarks today. |
| run_self_tests / check_impls | `check_impls(impls: Iterable[Callable], cases: Iterable[tuple[tuple, Any]]) -> None`; `expect_raises(exc, fn, *a, match: str \| None = None, **kw)`; `run_self_tests(module_or_globals) -> int` | A table-driven test harness that names the failing implementation and case, and replaces the hand-written `try/raise AssertionError` blocks. |

### Why these three were implemented first

* **Clock/FakeClock.** Time injection is the most consistent design idiom (7 samples), and the fake-clock boilerplate is copied in 4 test blocks. Everything time-based (TTL, windows, retries) depends on it.
* **TTLCache (+ `ttl_cache`).** One class covers caching, TTL, dedup and idempotency, which spans 5 samples (09, 10/11 by design, 36, 37). The tests show that it behaves exactly like `LRUCache` (09), `IdempotencyStore` (36) and `AlertDeduper` (37) on randomized operation streams.
* **TopK.** Heap and top-k logic shows up in 8 distinct samples (01, 07, 08, 17, 21, 24, 29, 33), and the push-or-replace-root logic is re-implemented each time. The tests show it matches `KthLargest` and `kth_largest` (08) exactly, and matches `top_k_heap` (07) up to tie order.

`retry_with_backoff` is the obvious next wrapper. It has lower frequency (2) but the highest operational value.

## 4. Refactor map

| Sample(s) | Would use |
|---|---|
| 01, 29 (`dispatch`) | `PriorityQueue` (earliest-free resource); 29 `in_freeze` → `overlaps` |
| 02, 03, 04, 05, 06 | interval helpers (`max_overlap`, `overlaps`, `merge_intervals`, `sort_intervals(by="end")`) |
| 07, 17, 33 | ★ `top_k(Counter(...).items(), k, key=…)` |
| 08 | ★ `TopK` (`KthLargest.add` → `TopK.push`) |
| 09 | ★ `TTLCache(ttl=None, maxsize=cap)` |
| 10, 11 | stay hand-rolled (the data structure is the interview answer); tests → `check_impls` |
| 12, 13 | ★ `FakeClock` in tests; 13 → `SlidingWindow` / `SlidingWindowCounter` |
| 14, 15, 26 | `require` for args (`vnodes > 0`, `n_items > 0`, `0 < fp_rate < 1`); 15 → pass a seeded `random.Random()` as `rng` |
| 16 | `SlidingWindow.rate(pred=is_error)` |
| 18, 19, 20, 22 | graph helpers (`topo_waves`, `find_cycle`, `bfs_levels`, `reverse_graph`) |
| 21, 24 | `PriorityQueue` (24 `Scheduler.run_until` → `pop_until`) |
| 25, 34 | `RingStats` / `deque(maxlen)` window |
| 28, 32 | `validate_inputs` / `require`; 32's schema validator is already the reference implementation |
| 30, 35 | `require` for preconditions; `expect_raises` in tests |
| 31 | `retry_with_backoff` (or keep attempt counting) plus DLQ |
| 36 | `retry_with_backoff` + ★ `FakeClock.sleep`; `IdempotencyStore` → ★ `TTLCache.get_or_compute` |
| 37 | ★ `ttl_cache`; `AlertDeduper` → ★ `TTLCache.add_if_absent`; ★ `FakeClock` |
| 23, 27 | no wrapper needed (trie and two-sum are self-contained) |
| all 36 asserting samples | `check_impls` / `expect_raises` / `run_self_tests` (and a fix for 10 depending on 09) |
| any | `timed` for ad-hoc benchmarking (none today) |

## 5. Verification

* `python wrappers.py`: the usage demo asserts pass.
* `python tests/test_wrappers.py` (and `pytest tests/`): 15 tests pass, 7 of them equivalence tests against samples 07, 08, 09, 12, 36 and 37.
* `py_compile` succeeds on all 37 samples. `git diff` shows no change to any sample file.

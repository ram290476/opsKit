"""AST-based pattern scanner for the 37 interview samples.

Run from the repo root:  python tools/analyze_patterns.py [--json]

Each detector is a small, explicit AST rule. Its output is the evidence behind
the ranked table in ANALYSIS.md. Some patterns (e.g. two pointers, min/max
tracking) are algorithmic idioms that AST can only approximate, so ANALYSIS.md
notes where the counts were adjusted by hand after reading the code.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, List, Set

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = sorted(p for p in ROOT.glob("[0-3][0-9]_*.py"))


def imported_names(tree: ast.AST) -> Set[str]:
    out: Set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            out |= {f"{n.module}.{a.name}" for a in n.names}
            out.add(n.module or "")
    return out


def call_names(tree: ast.AST) -> Set[str]:
    out: Set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                base = f.value.id if isinstance(f.value, ast.Name) else ""
                out.add(f"{base}.{f.attr}" if base else f".{f.attr}")
    return out


def param_names(tree: ast.AST) -> Set[str]:
    out: Set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.Lambda)):
            a = n.args
            out |= {x.arg for x in a.args + a.kwonlyargs + a.posonlyargs}
    return out


# Module-level helpers that exist only to drive a sample's self-tests.
TEST_DOUBLES = {"handler", "flaky", "always_fail", "mk"}


def defs_body(tree: ast.Module) -> List[ast.AST]:
    """Top-level defs/classes, excluding self-test doubles."""
    return [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
            and n.name not in TEST_DOUBLES]


def module_level_asserts(tree: ast.Module) -> int:
    count = 0
    for top in tree.body:
        if isinstance(top, (ast.FunctionDef, ast.ClassDef)):
            continue
        count += sum(isinstance(n, ast.Assert) for n in ast.walk(top))
    return count


def in_defs(tree: ast.Module, pred: Callable[[ast.AST], bool]) -> bool:
    return any(pred(n) for d in defs_body(tree) for n in ast.walk(d))


def src_has(src: str, *needles: str) -> bool:
    return any(s in src for s in needles)


def detect(path: Path) -> Dict[str, bool]:
    src = path.read_text()
    tree = ast.parse(src)
    imps, calls, params = imported_names(tree), call_names(tree), param_names(tree)
    attr_calls = {c.split(".")[-1] for c in calls}

    sorted_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == "sorted"]
    sort_then_loop = any(
        isinstance(n, ast.For) and isinstance(n.iter, ast.Call)
        and isinstance(n.iter.func, ast.Name) and n.iter.func.id == "sorted"
        for n in ast.walk(tree))
    # running peak/extreme: x = max(x, ...) / x = min(x, ...)  (compare by source,
    # not ast.dump, because Store vs Load ctx differ)
    running_extreme = any(
        isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name) and n.value.func.id in ("max", "min")
        and any(ast.unparse(t) == ast.unparse(a) for t in n.targets for a in n.value.args)
        for n in ast.walk(tree))
    tracked_extreme = bool(re.search(r"\bmin_freq\b|\bpeak\b|\bprev_end\b|max\(counts", ast.unparse(tree)))
    argext_key = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id in ("max", "min") and any(k.arg == "key" for k in n.keywords)
        for n in ast.walk(tree))
    index_while = any(  # while i < len(...)/n and ... : index-pointer scan
        isinstance(n, ast.While) and isinstance(n.test, ast.BoolOp)
        and any(isinstance(v, ast.Compare) and isinstance(v.left, ast.Name)
                and v.left.id in ("i", "j") for v in n.test.values)
        for n in ast.walk(tree))
    adjacent_zip = "zip" in calls and src_has(src, "[1:]")
    has_try_in_defs = in_defs(tree, lambda n: isinstance(n, ast.Try))
    has_raise_in_defs = in_defs(tree, lambda n: isinstance(n, ast.Raise))
    test_expects_raise = any(
        isinstance(top, ast.Try) and any(isinstance(n, ast.Raise) and
        "AssertionError" in ast.dump(n) for n in ast.walk(top))
        for top in tree.body)
    isinstance_in_defs = in_defs(tree, lambda n: isinstance(n, ast.Call)
                                 and isinstance(n.func, ast.Name)
                                 and n.func.id == "isinstance")
    # guard clause: `if not X: return/continue` or `if X <= 0: return`
    guard_return = in_defs(tree, lambda n: isinstance(n, ast.If) and n.body and
                           isinstance(n.body[0], (ast.Return, ast.Continue)) and
                           (isinstance(n.test, ast.UnaryOp) or
                            (isinstance(n.test, ast.Compare) and
                             any(isinstance(o, (ast.NotIn, ast.LtE, ast.Is))
                                 for o in n.test.ops))))
    impl_loop = any(  # for f in (impl_a, impl_b): assert f(...)
        isinstance(top, ast.For) and isinstance(top.iter, ast.Tuple)
        and all(isinstance(e, ast.Name) for e in top.iter.elts)
        and any(isinstance(n, ast.Assert) for n in ast.walk(top))
        for top in tree.body)
    fake_clock = src_has(src, "clock=lambda", "sleep=slept.append")

    cache_names = any(isinstance(n, (ast.ClassDef, ast.FunctionDef)) and
                      re.search(r"cache|Cache|IdempotencyStore", n.name)
                      for n in ast.walk(tree))
    raises_value_error = in_defs(tree, lambda n: isinstance(n, ast.Raise) and
                                 n.exc is not None and "ValueError" in ast.unparse(n.exc))
    deque_or_ring = "collections.deque" in imps or "% self.cap" in src
    return {
        "assert_self_tests": module_level_asserts(tree) > 0,
        "multi_impl_test_loop": impl_loop,
        "heap_priority_queue": "heapq" in imps,
        "counter_counting": "collections.Counter" in imps,
        "top_k_selection": "most_common" in attr_calls or ("heapq" in imps and "k" in params),
        "hashmap_grouping_defaultdict": "collections.defaultdict" in imps or "setdefault" in attr_calls,
        "deque_ring_buffer": deque_or_ring,
        "ordered_eviction_lru": "collections.OrderedDict" in imps or "_add_front" in src,
        "intervals_sort_and_sweep": bool(re.search(r"start, end|\bs, e\b|\bs, _\b|\(s1, e1\)|\[1\] <|freezes", src))
                                    and bool(sorted_calls or "bisect" in imps or "intervals" in params),
        "bisect_sorted_search": "bisect" in imps,
        "graph_traversal": bool(re.search(r"\bgraph\b|\bdeps\b|indeg|UnionFind", src)),
        "running_min_max": running_extreme or argext_key or tracked_extreme,
        "two_pointers_index_scan": index_while or adjacent_zip,
        "injected_clock_sleep_rng": bool({"clock", "sleep", "rng"} & params),
        "explicit_now_ts_param": bool({"now", "ts"} & params),
        "fake_clock_in_tests": fake_clock,
        "ttl_expiry": "ttl" in params or "self.ttl" in src,
        "dedup_idempotency": src_has(src, "dict.fromkeys", "Idempotency", "Deduper"),
        "sliding_window": deque_or_ring and src_has(src, "window", "% self.cap"),
        "error_handling_try_except": has_try_in_defs,
        "raises_on_bad_state": has_raise_in_defs,
        "tests_expect_exception": test_expects_raise,
        "retry_backoff": src_has(src, "max_attempts", "call_with_retry"),
        "input_validation_guards": (isinstance_in_defs or raises_value_error
                                    or src_has(src, "if not m:", "malformed", "self.cap <= 0",
                                               "if not self.ring", "def is_valid")),
        "caching_memoization": cache_names,
        "hashing_hashlib": "hashlib" in imps,
        "regex_parsing": "re" in imps,
        "stack_lifo": src_has(src, "stack", "history", "path.pop()"),
        "timing_benchmark": src_has(src, "perf_counter", "timeit", "time.time(", "process_time"),
    }


def main() -> None:
    hits: Dict[str, List[str]] = defaultdict(list)
    for p in SAMPLES:
        for k, v in detect(p).items():
            if v:
                hits[k].append(p.name[:2])
    ranked = sorted(hits.items(), key=lambda kv: -len(kv[1]))
    if "--json" in sys.argv:
        print(json.dumps(dict(ranked), indent=1))
        return
    print(f"scanned {len(SAMPLES)} samples")
    for k, v in ranked:
        print(f"{len(v):3d}  {k:32s} {' '.join(v)}")
    zero = [k for k in detect(SAMPLES[0]) if k not in hits]
    if zero:
        print("  0  " + ", ".join(zero))


if __name__ == "__main__":
    main()

from collections import Counter
from typing import Iterable, Iterator

def parse(lines: Iterable[str]) -> Iterator[tuple[str, str]]:
    """Yield (level, service); skip malformed or stack-trace lines."""
    for line in lines:
        parts = line.split(maxsplit=3)
        if len(parts) >= 3 and parts[1].isupper():
            yield parts[1], parts[2]

def count_levels(lines: Iterable[str]) -> tuple[Counter, list[tuple[str, int]]]:
    levels: Counter = Counter()
    errors: Counter = Counter()
    for level, svc in parse(lines):
        levels[level] += 1
        if level == "ERROR":
            errors[svc] += 1
    return levels, errors.most_common(3)

if __name__ == "__main__":
    sample = [
        "2026-10-28T13:30:01Z ERROR payment-svc Timeout calling db",
        "2026-10-28T13:30:02Z INFO auth-svc login ok",
        "2026-10-28T13:30:03Z ERROR payment-svc Timeout calling db",
        "    at db.connect(Pool.java:42)",
        "2026-10-28T13:30:04Z ERROR auth-svc token expired",
        "2026-10-28T13:30:05Z WARN cart-svc slow response",
    ]
    levels, top = count_levels(sample)  # with open(path) as f: count_levels(f)
    print(dict(levels), top)
    assert top[0] == ("payment-svc", 2)

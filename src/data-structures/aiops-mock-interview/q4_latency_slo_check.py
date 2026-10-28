import math
from collections import defaultdict

def percentile(sorted_vals: list[float], p: float) -> float:
    """Nearest-rank percentile on a sorted list."""
    k = max(0, math.ceil(p / 100 * len(sorted_vals)) - 1)
    return sorted_vals[k]

def slo_report(records: list[tuple[str, float, int]],
               p99_ms: float = 500, max_err: float = 0.01) -> dict[str, dict]:
    lat: dict[str, list[float]] = defaultdict(list)
    errs: dict[str, int] = defaultdict(int)
    for endpoint, ms, status in records:
        lat[endpoint].append(ms)
        if status >= 500:              # 4xx is usually the client's fault
            errs[endpoint] += 1
    report = {}
    for ep, vals in lat.items():
        vals.sort()
        r = {f"p{p}": percentile(vals, p) for p in (50, 95, 99)}
        r["error_rate"] = errs[ep] / len(vals)
        r["breach"] = r["p99"] > p99_ms or r["error_rate"] > max_err
        report[ep] = r
    return report

if __name__ == "__main__":
    recs = [("/pay", float(i), 200) for i in range(1, 100)] + [("/pay", 900.0, 503)] * 2
    recs += [("/login", 50.0, 200)] * 50
    rep = slo_report(recs)
    for ep, r in rep.items():
        print(ep, r)
    assert rep["/pay"]["breach"] and not rep["/login"]["breach"]

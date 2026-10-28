from collections import defaultdict
from typing import TypedDict, Optional

class Span(TypedDict):
    span_id: str
    parent_id: Optional[str]
    service: str
    start: float
    end: float

def analyze(spans: list[Span]) -> tuple[list[str], str]:
    by_id = {s["span_id"]: s for s in spans}
    kids: dict[str, list[Span]] = defaultdict(list)
    roots = []
    for s in spans:
        if s["parent_id"] in by_id:
            kids[s["parent_id"]].append(s)
        else:
            roots.append(s)                     # root or orphan
    def critical(s: Span) -> list[str]:
        path = [s["service"]]
        if kids[s["span_id"]]:                  # child that ends last blocks parent
            last = max(kids[s["span_id"]], key=lambda c: c["end"])
            path += critical(last)
        return path
    self_time: dict[str, float] = defaultdict(float)
    for s in spans:
        # merge child intervals so parallel children are not double-counted
        iv = sorted((c["start"], c["end"]) for c in kids[s["span_id"]])
        covered, cur_s, cur_e = 0.0, None, None
        for a, b in iv:
            if cur_e is None or a > cur_e:
                if cur_e is not None: covered += cur_e - cur_s
                cur_s, cur_e = a, b
            else:
                cur_e = max(cur_e, b)
        if cur_e is not None: covered += cur_e - cur_s
        self_time[s["service"]] += (s["end"] - s["start"]) - covered
    root = max(roots, key=lambda r: r["end"] - r["start"])
    return critical(root), max(self_time, key=self_time.get)

if __name__ == "__main__":
    spans: list[Span] = [
        {"span_id": "1", "parent_id": None, "service": "gateway", "start": 0, "end": 100},
        {"span_id": "2", "parent_id": "1", "service": "auth", "start": 5, "end": 20},
        {"span_id": "3", "parent_id": "1", "service": "payment", "start": 10, "end": 95},
        {"span_id": "4", "parent_id": "3", "service": "db", "start": 15, "end": 40},
    ]
    path, hot = analyze(spans)
    print(path, hot)
    assert path == ["gateway", "payment", "db"] and hot == "payment"

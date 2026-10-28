# Topic: S5. Log Parsing (regex + hashmap counters + top-K)
# Section: 11. SRE/Platform Day-to-Day Scripting & Automation
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)
# Scenario (novice): Summarize logs by finding routes with the most server
# errors and their high-percentile response latency.
# Implementation (developer): Parse key-value fields with regex, aggregate
# counts and latency samples, then calculate p95 and top error routes.

import math
import re
from collections import Counter, defaultdict
 
KV = re.compile(r"(\w+)=(\S+)")
 
def pct(values, q):
    s = sorted(values)
    return s[max(0, math.ceil(q / 100 * len(s)) - 1)]
 
def summarize(lines, k=3):
    errors, lat = Counter(), defaultdict(list)
    for line in lines:
        f = dict(KV.findall(line))
        if "path" not in f:
            continue                # malformed: skip
        if f.get("status", "").startswith("5"):
            errors[f["path"]] += 1
        if f.get("latency_ms", "").isdigit():
            lat[f["path"]].append(int(f["latency_ms"]))
    p95 = {p: pct(v, 95) for p, v in lat.items()}
    return errors.most_common(k), p95
 
logs = [
    "ts=1 path=/pay status=503 latency_ms=800",
    "ts=2 path=/pay status=200 latency_ms=120",
    "ts=3 path=/cart status=500 latency_ms=90",
    "ts=4 path=/pay status=502 latency_ms=950",
    "corrupted line",
]
top, p95 = summarize(logs, k=2)
assert top == [("/pay", 2), ("/cart", 1)]
assert p95 == {"/pay": 950, "/cart": 90}
assert pct([1, 2, 3, 4], 50) == 2

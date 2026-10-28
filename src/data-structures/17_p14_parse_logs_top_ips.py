# Topic: P14. Parse Logs and Count Top IPs (hashmap)
# Section: 7. Logs & Sliding Windows
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)
# Scenario (novice): Read access logs to find the IP addresses making the
# most requests, optionally counting only server errors.
# Implementation (developer): Match log fields with a compiled regex, count
# valid records with Counter, and separately report malformed lines.

import re
from collections import Counter
 
LINE = re.compile(
    r'^(?P<ip>\d{1,3}(?:\.\d{1,3}){3}) \S+ \S+ '
    r'\[(?P<ts>[^\]]+)\] "(?P<method>\S+) (?P<path>\S+)'
    r'[^"]*" (?P<status>\d{3})')
 
def top_ips(lines, k=3, only_5xx=False):
    counts, bad = Counter(), 0
    for line in lines:
        m = LINE.match(line)
        if not m:
            bad += 1
            continue
        if only_5xx and not m["status"].startswith("5"):
            continue
        counts[m["ip"]] += 1
    return counts.most_common(k), bad
 
def mk(ip, status):
    return (f'{ip} - - [20/Oct/2026:10:00:00 -0700] '
            f'"GET /api HTTP/1.1" {status} 512')
 
logs = [mk("10.0.0.1", 200), mk("10.0.0.2", 503),
        mk("10.0.0.1", 500), "garbage line"]
assert top_ips(logs, 1) == ([("10.0.0.1", 2)], 1)
top, bad = top_ips(logs, 5, only_5xx=True)
assert sorted(top) == [("10.0.0.1", 1), ("10.0.0.2", 1)]

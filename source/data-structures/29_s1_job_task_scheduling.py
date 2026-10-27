# Topic: S1. Job / Task Scheduling (heap priority queue + intervals)
# Section: 11. SRE/Platform Day-to-Day Scripting & Automation
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)

import bisect
import heapq
 
def dispatch(jobs, workers):
    """jobs: (priority, name, duration); lower = more
    urgent. Returns [(name, worker, start, end)]."""
    pq = list(jobs)
    heapq.heapify(pq)
    free = [(0, w) for w in range(workers)]  # (free_at, id)
    plan = []
    while pq:
        _, name, dur = heapq.heappop(pq)
        t, w = heapq.heappop(free)
        plan.append((name, w, t, t + dur))
        heapq.heappush(free, (t + dur, w))
    return plan
 
def in_freeze(freezes, start, end):
    """freezes: sorted, merged [(s, e)]. True if
    [start, end) overlaps any freeze."""
    i = bisect.bisect_right(freezes, (start, float("inf")))
    if i and freezes[i - 1][1] > start:
        return True                 # earlier window covers
    return i < len(freezes) and freezes[i][0] < end
 
jobs = [(2, "scrub", 30), (0, "cve-patch", 10),
        (1, "reimage", 20)]
assert dispatch(jobs, 2) == [("cve-patch", 0, 0, 10),
                             ("reimage", 1, 0, 20),
                             ("scrub", 0, 10, 40)]
fz = [(10, 20), (30, 40)]
assert in_freeze(fz, 15, 16) and in_freeze(fz, 5, 11)
assert not in_freeze(fz, 20, 30)    # touching is OK
assert not in_freeze([], 0, 5)

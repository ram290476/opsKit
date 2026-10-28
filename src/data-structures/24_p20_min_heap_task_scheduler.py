# Topic: P20. Min-Heap Scheduler / Task Scheduler
# Section: 9. Specialized Structures: Trie, Scheduler Heap, Ring Buffer, Bloom Filter
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)
# Scenario (novice): Run tasks when they are due, including tasks that repeat,
# and calculate the shortest schedule with a required cooldown.
# Implementation (developer): Order scheduled tasks by run time in a min-heap
# with a sequence tie-breaker; compute cooldown length from task frequencies.

import heapq
import itertools
from collections import Counter
 
class Scheduler:
    def __init__(self):
        self.pq = []        # (run_at, seq, name, every)
        self.seq = itertools.count()
 
    def add(self, name, run_at, every=None):
        item = (run_at, next(self.seq), name, every)
        heapq.heappush(self.pq, item)
 
    def run_until(self, now):
        ran = []
        while self.pq and self.pq[0][0] <= now:
            t, _, name, every = heapq.heappop(self.pq)
            ran.append((t, name))
            if every:
                self.add(name, t + every, every)  # no drift
        return ran
 
def least_interval(tasks, n):
    counts = Counter(tasks).values()
    top = max(counts, default=0)
    n_top = sum(1 for c in counts if c == top)
    return max(len(tasks), (top - 1) * (n + 1) + n_top)
 
s = Scheduler()
s.add("backup", 10); s.add("health", 0, every=5)
assert s.run_until(10) == [(0, "health"), (5, "health"),
                           (10, "backup"), (10, "health")]
assert least_interval(list("AAABBB"), 2) == 8
assert least_interval(list("AAABBB"), 0) == 6
assert least_interval(list("AAAAAABCDEFG"), 2) == 16
assert least_interval([], 3) == 0

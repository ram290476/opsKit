# Topic: P10. Rate Limiter (token bucket, sliding window log, sliding window counter)
# Section: 6. Traffic: Rate Limiting, Consistent Hashing, Load Balancing
# Block: Sliding window log and sliding window counter
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)
# Scenario (novice): Limit requests over recent time so a fixed time boundary
# does not permit an unexpectedly large burst.
# Implementation (developer): Demonstrate an exact timestamp deque and a
# lower-memory counter that estimates traffic across adjacent windows.

import time
from collections import deque
 
class SlidingWindowLog:
    def __init__(self, limit, window, clock=time.monotonic):
        self.limit, self.window = limit, window
        self.clock = clock
        self.log = deque()          # request timestamps
 
    def allow(self):
        now = self.clock()
        while self.log and self.log[0] <= now - self.window:
            self.log.popleft()      # drop expired
        if len(self.log) < self.limit:
            self.log.append(now)
            return True
        return False
 
class SlidingWindowCounter:
    def __init__(self, limit, window, clock=time.monotonic):
        self.limit, self.window = limit, window
        self.clock = clock
        self.cur_start = None
        self.cur = self.prev = 0
 
    def allow(self):
        now = self.clock()
        start = now - (now % self.window)
        if start != self.cur_start:
            prev_start = start - self.window
            adjacent = self.cur_start == prev_start
            self.prev = self.cur if adjacent else 0
            self.cur, self.cur_start = 0, start
        weight = 1 - (now - start) / self.window
        if self.prev * weight + self.cur < self.limit:
            self.cur += 1
            return True
        return False
 
t = [0]
log = SlidingWindowLog(3, 10, clock=lambda: t[0])
assert [log.allow() for _ in range(4)] == \
    [True, True, True, False]
t[0] = 10                           # old entries expire
assert log.allow() is True
 
t = [0]
swc = SlidingWindowCounter(4, 10, clock=lambda: t[0])
assert [swc.allow() for _ in range(5)] == \
    [True, True, True, True, False]
t[0] = 10                           # est = 4*1.0 + 0
assert swc.allow() is False
t[0] = 15                           # est = 4*0.5 + cur
assert [swc.allow() for _ in range(3)] == \
    [True, True, False]

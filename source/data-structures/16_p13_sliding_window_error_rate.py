# Topic: P13. Sliding Window Log Analysis (error rate in the last N minutes)
# Section: 7. Logs & Sliding Windows
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)

from collections import deque
 
class ErrorRateWindow:
    def __init__(self, window=300):
        self.window = window
        self.events = deque()       # (ts, is_error)
        self.errors = 0
 
    def record(self, ts, is_error):
        self.events.append((ts, is_error))
        self.errors += int(is_error)
        self._evict(ts)
 
    def _evict(self, now):
        cutoff = now - self.window
        while self.events and self.events[0][0] <= cutoff:
            _, err = self.events.popleft()
            self.errors -= int(err)
 
    def rate(self, now):
        self._evict(now)
        n = len(self.events)
        return self.errors / n if n else 0.0
 
w = ErrorRateWindow(window=300)
for ts, err in [(0, False), (10, True), (20, False)]:
    w.record(ts, err)
assert abs(w.rate(20) - 1 / 3) < 1e-9
assert w.rate(305) == 0.5           # ts 0 expired
assert w.rate(400) == 0.0           # all expired

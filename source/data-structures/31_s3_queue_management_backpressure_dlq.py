# Topic: S3. Queue Management (deque, bounded queues, backpressure, DLQ)
# Section: 11. SRE/Platform Day-to-Day Scripting & Automation
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)

from collections import deque
 
class WorkQueue:
    def __init__(self, maxsize, max_attempts=3):
        self.q = deque()
        self.maxsize = maxsize
        self.max_attempts = max_attempts
        self.dlq = []
 
    def offer(self, msg):
        if len(self.q) >= self.maxsize:
            return False            # backpressure
        self.q.append((msg, 0))
        return True
 
    def work(self, handler):
        ok = 0
        while self.q:
            msg, attempts = self.q.popleft()
            try:
                handler(msg)
                ok += 1
            except Exception as exc:
                attempts += 1
                if attempts >= self.max_attempts:
                    self.dlq.append((msg, repr(exc)))
                else:
                    self.q.append((msg, attempts))  # retry
        return ok
 
def handler(msg):
    if msg == "poison":
        raise ValueError("bad payload")
 
wq = WorkQueue(maxsize=3)
assert [wq.offer(m) for m in ("a", "poison", "b", "c")] \
    == [True, True, True, False]
assert wq.work(handler) == 2
assert wq.dlq == [("poison", "ValueError('bad payload')")]
shed = deque(maxlen=2)
shed.extend([1, 2, 3])
assert list(shed) == [2, 3]         # oldest dropped

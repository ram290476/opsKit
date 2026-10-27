# Topic: P21. Circular Buffer / Ring Buffer for Metrics
# Section: 9. Specialized Structures: Trie, Scheduler Heap, Ring Buffer, Bloom Filter
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)

from collections import deque
 
class RingBuffer:
    def __init__(self, capacity):
        self.buf = [None] * capacity
        self.cap = capacity
        self.head = 0               # next write slot
        self.size = 0
        self.total = 0.0
 
    def push(self, x):
        if self.size == self.cap:
            self.total -= self.buf[self.head]  # overwrite
        else:
            self.size += 1
        self.buf[self.head] = x
        self.total += x
        self.head = (self.head + 1) % self.cap
 
    def items(self):                # oldest -> newest
        start = (self.head - self.size) % self.cap
        return [self.buf[(start + i) % self.cap]
                for i in range(self.size)]
 
    def mean(self):
        return self.total / self.size if self.size else 0.0
 
rb = RingBuffer(3)
for x in (1, 2, 3, 4):
    rb.push(x)
assert rb.items() == [2, 3, 4] and rb.mean() == 3.0
assert RingBuffer(2).mean() == 0.0
d = deque(maxlen=3)                 # Pythonic equivalent
d.extend([1, 2, 3, 4])
assert list(d) == [2, 3, 4]

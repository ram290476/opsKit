# Topic: P10. Rate Limiter (token bucket, sliding window log, sliding window counter)
# Section: 6. Traffic: Rate Limiting, Consistent Hashing, Load Balancing
# Block: Token bucket
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)
# Scenario (novice): Limit how quickly requests are accepted while still
# allowing a short burst after a quiet period.
# Implementation (developer): Refill tokens from elapsed monotonic time up to
# a capacity, then accept a request only if its token cost is available.

import time
 
class TokenBucket:
    def __init__(self, rate, capacity,
                 clock=time.monotonic):
        self.rate = rate            # tokens per second
        self.capacity = capacity    # max burst
        self.tokens = capacity
        self.clock = clock
        self.last = clock()
 
    def allow(self, cost=1):
        now = self.clock()
        elapsed = now - self.last
        self.tokens = min(self.capacity,
                          self.tokens + elapsed * self.rate)
        self.last = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False
 
t = [0.0]
tb = TokenBucket(rate=1, capacity=2, clock=lambda: t[0])
assert [tb.allow() for _ in range(3)] == [True, True, False]
t[0] = 1.0
assert tb.allow() is True and tb.allow() is False

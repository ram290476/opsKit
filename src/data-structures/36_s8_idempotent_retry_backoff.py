# Topic: S8. Idempotent Retry Handling (backoff + jitter, idempotency keys, TTL)
# Section: 11. SRE/Platform Day-to-Day Scripting & Automation
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)
# Scenario (novice): Retry temporary failures without overwhelming a service,
# and avoid repeating work for duplicate requests.
# Implementation (developer): Generate capped exponential backoff with jitter
# and cache idempotency results until their monotonic-clock TTL expires.

import random
import time
 
class TransientError(Exception):
    pass
 
def backoff_delays(n, base=0.1, cap=10.0, rng=random):
    for i in range(n):
        yield rng.uniform(0, min(cap, base * 2 ** i))
 
def call_with_retry(fn, attempts=5, sleep=time.sleep,
                    **kw):
    delays = backoff_delays(attempts - 1, **kw)
    for attempt in range(attempts):
        try:
            return fn()
        except TransientError:
            if attempt == attempts - 1:
                raise               # out of retries
            sleep(next(delays))
 
class IdempotencyStore:
    def __init__(self, ttl=3600, clock=time.monotonic):
        self.ttl, self.clock = ttl, clock
        self.done = {}              # key -> (result, exp)
 
    def run(self, key, fn):
        now = self.clock()
        hit = self.done.get(key)
        if hit and hit[1] > now:
            return hit[0]           # duplicate: replay
        result = fn()
        self.done[key] = (result, now + self.ttl)
        return result
 
calls, slept = [], []
def flaky():
    calls.append(1)
    if len(calls) < 3:
        raise TransientError("503")
    return "ok"
assert call_with_retry(flaky, sleep=slept.append) == "ok"
assert len(calls) == 3 and len(slept) == 2
assert all(0 <= s <= 0.1 * 2 ** i
           for i, s in enumerate(slept))
slept.clear()
def always_fail():
    raise TransientError("timeout")
try:
    call_with_retry(always_fail, attempts=3,
                    sleep=slept.append)
    raise AssertionError("expected TransientError")
except TransientError:
    assert len(slept) == 2          # no sleep after last
 
t, created = [0], []
store = IdempotencyStore(ttl=60, clock=lambda: t[0])
mk = lambda: created.append("vol") or f"vol-{len(created)}"
assert store.run("req-1", mk) == store.run("req-1", mk)
assert created == ["vol"]           # side effect once
t[0] = 61
assert store.run("req-1", mk) == "vol-2"   # TTL expired

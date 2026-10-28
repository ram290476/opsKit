# Topic: S9. Dedup / Caching with Hashmaps (TTL memoize, alert dedup)
# Section: 11. SRE/Platform Day-to-Day Scripting & Automation
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)
# Scenario (novice): Reuse recently computed results and avoid sending the
# same alert repeatedly during a short time window.
# Implementation (developer): Cache function results by arguments with TTL
# expiry, and deduplicate alerts by fingerprint and last-sent timestamp.

import functools
import time
 
def ttl_cache(ttl, clock=time.monotonic):
    def deco(fn):
        cache = {}
 
        @functools.wraps(fn)
        def wrapper(*args):
            now = clock()
            hit = cache.get(args)
            if hit and hit[1] > now:
                return hit[0]
            val = fn(*args)
            cache[args] = (val, now + ttl)
            return val
        return wrapper
    return deco
 
class AlertDeduper:
    def __init__(self, window=300):
        self.window = window
        self.last_sent = {}         # fingerprint -> ts
 
    def should_send(self, alert, now):
        fp = (alert["service"], alert["name"],
              alert.get("severity"))
        last = self.last_sent.get(fp)
        if last is not None and now - last < self.window:
            return False
        self.last_sent[fp] = now
        return True
 
t, lookups = [0], []
 
@ttl_cache(ttl=30, clock=lambda: t[0])
def resolve(name):
    lookups.append(name)
    return f"10.0.0.{len(lookups)}"
 
assert resolve("db") == resolve("db") == "10.0.0.1"
t[0] = 31
assert resolve("db") == "10.0.0.2" and len(lookups) == 2
 
dd = AlertDeduper(window=300)
a = {"service": "api", "name": "5xx", "severity": "P1",
     "host": "i-123"}
b = dict(a, host="i-456")           # same fingerprint
assert dd.should_send(a, 0) and not dd.should_send(b, 120)
assert dd.should_send(a, 301)
assert list(dict.fromkeys(["i-1", "i-2", "i-1"])) == \
    ["i-1", "i-2"]

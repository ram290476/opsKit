# Topic: S6. Health-Check Aggregation (hashmap + sliding window + quorum)
# Section: 11. SRE/Platform Day-to-Day Scripting & Automation
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)
# Scenario (novice): Decide whether a service is up, degraded, or down from
# recent health checks of its instances.
# Implementation (developer): Keep a bounded probe history per instance,
# apply a failure threshold, and aggregate healthy instances using quorum.

from collections import defaultdict, deque
 
class HealthAggregator:
    def __init__(self, window=5, fail_threshold=3,
                 quorum=0.5):
        self.fail_threshold = fail_threshold
        self.quorum = quorum
        self.probes = defaultdict(
            lambda: deque(maxlen=window))
 
    def record(self, service, instance, ok):
        self.probes[(service, instance)].append(ok)
 
    def healthy(self, key):
        fails = sum(1 for ok in self.probes[key] if not ok)
        return fails < self.fail_threshold
 
    def service_status(self):
        flags = defaultdict(list)
        for key in list(self.probes):
            flags[key[0]].append(self.healthy(key))
        status = {}
        for svc, fl in flags.items():
            up = sum(fl)
            if up == len(fl):
                status[svc] = "UP"
            elif up > len(fl) * self.quorum:
                status[svc] = "DEGRADED"
            else:
                status[svc] = "DOWN"
        return status
 
h = HealthAggregator(window=5, fail_threshold=3)
for i in ("i1", "i2", "i3"):
    for ok in (True, True, False, True, True):  # 1 blip
        h.record("api", i, ok)
assert h.service_status() == {"api": "UP"}
for _ in range(3):
    h.record("api", "i3", False)
assert h.service_status() == {"api": "DEGRADED"}  # 2 of 3
for _ in range(3):
    h.record("api", "i2", False)
assert h.service_status() == {"api": "DOWN"}      # 1 of 3

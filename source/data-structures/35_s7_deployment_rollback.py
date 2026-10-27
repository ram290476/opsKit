# Topic: S7. Deployment Rollback Logic (stack of versions + canary thresholds)
# Section: 11. SRE/Platform Day-to-Day Scripting & Automation
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)

class Deployer:
    def __init__(self, initial):
        self.history = [initial]    # stack; top = live
 
    @property
    def live(self):
        return self.history[-1]
 
    def deploy(self, version):
        self.history.append(version)
 
    def rollback(self, steps=1):
        if steps >= len(self.history):
            raise ValueError("no older version")
        del self.history[-steps:]
        return self.live
 
def canary_verdict(baseline, canary, max_ratio=1.5,
                   min_requests=500, abs_floor=0.001):
    """baseline/canary: (errors, requests)."""
    (be, br), (ce, cr) = baseline, canary
    if cr < min_requests:
        return "WAIT"               # not enough signal
    b_rate = be / br if br else 0.0
    limit = max(b_rate * max_ratio, abs_floor)
    return "ROLLBACK" if ce / cr > limit else "PROMOTE"
 
def rollout(dep, version, stages, metrics):
    dep.deploy(version)
    for pct in stages:
        verdict = canary_verdict(*metrics(pct))
        if verdict == "ROLLBACK":
            return "ROLLED_BACK", pct, dep.rollback()
        if verdict == "WAIT":
            return "HOLD", pct, dep.live
    return "PROMOTED", stages[-1], dep.live
 
d = Deployer("v1")
d.deploy("v2"); d.deploy("v3")
assert d.rollback() == "v2" and d.rollback() == "v1"
assert canary_verdict((10, 10000), (5, 1000)) == "ROLLBACK"
assert canary_verdict((10, 10000), (1, 1000)) == "PROMOTE"
assert canary_verdict((0, 10000), (1, 2000)) == "PROMOTE"
assert canary_verdict((0, 10000), (9, 100)) == "WAIT"
bad = {1: ((10, 1e4), (1, 1000)), 5: ((10, 1e4), (40, 5e3))}
assert rollout(d, "v4", [1, 5, 25], bad.get) == \
    ("ROLLED_BACK", 5, "v1")

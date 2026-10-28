# Topic: P12. Load Balancing Strategies
# Section: 6. Traffic: Rate Limiting, Consistent Hashing, Load Balancing
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)
# Scenario (novice): Choose which server should receive each new request.
# Implementation (developer): Compare rotating round-robin selection,
# smooth weighted round-robin scheduling, and least-active-connection tracking.

import itertools
import random
 
class RoundRobin:
    def __init__(self, backends):
        self._it = itertools.cycle(backends)
 
    def pick(self):
        return next(self._it)
 
class SmoothWeightedRR:
    def __init__(self, weights):        # {backend: w}
        self.weights = weights
        self.current = {b: 0 for b in weights}
        self.total = sum(weights.values())
 
    def pick(self):
        for b, w in self.weights.items():
            self.current[b] += w
        best = max(self.current, key=self.current.get)
        self.current[best] -= self.total
        return best
 
class LeastConnections:
    def __init__(self, backends):
        self.active = {b: 0 for b in backends}
 
    def acquire(self):
        b = min(self.active, key=self.active.get)
        self.active[b] += 1
        return b
 
    def release(self, b):
        self.active[b] -= 1
 
def power_of_two(backends, conns, rng=random):
    a, b = rng.sample(backends, 2)
    return a if conns[a] <= conns[b] else b
 
rr = RoundRobin(["a", "b"])
assert [rr.pick() for _ in range(3)] == ["a", "b", "a"]
w = SmoothWeightedRR({"a": 5, "b": 1, "c": 1})
assert "".join(w.pick() for _ in range(7)) == "aabacaa"
lc = LeastConnections(["a", "b"])
assert [lc.acquire() for _ in range(3)] == ["a", "b", "a"]
lc.release("a"); lc.release("a")
assert lc.acquire() == "a"
conns = {"x": 9, "y": 1}
assert power_of_two(["x", "y"], conns) == "y"

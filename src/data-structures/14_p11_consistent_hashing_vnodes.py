# Topic: P11. Consistent Hashing with Virtual Nodes (bisect ring)
# Section: 6. Traffic: Rate Limiting, Consistent Hashing, Load Balancing
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)
# Scenario (novice): Assign keys to servers so adding or removing a server
# moves only some keys instead of reshuffling them all.
# Implementation (developer): Place each server's virtual nodes on a sorted
# hash ring and use binary search to find the next owner for a key.

import bisect
import hashlib
 
def _h(key):
    digest = hashlib.md5(key.encode()).digest()
    return int.from_bytes(digest[:8], "big")
 
class HashRing:
    def __init__(self, nodes=(), vnodes=100):
        self.vnodes = vnodes
        self.ring = []              # sorted vnode hashes
        self.owner = {}             # hash -> node
        for n in nodes:
            self.add(n)
 
    def add(self, node):
        for i in range(self.vnodes):
            h = _h(f"{node}#{i}")
            bisect.insort(self.ring, h)
            self.owner[h] = node
 
    def remove(self, node):
        for i in range(self.vnodes):
            h = _h(f"{node}#{i}")
            self.ring.pop(bisect.bisect_left(self.ring, h))
            del self.owner[h]
 
    def get(self, key):
        if not self.ring:
            return None
        i = bisect.bisect(self.ring, _h(key))
        i %= len(self.ring)              # wrap around
        return self.owner[self.ring[i]]
 
ring = HashRing(["a", "b", "c"])
keys = [f"vm-{i}" for i in range(10000)]
before = {k: ring.get(k) for k in keys}
ring.add("d")
moved = [k for k in keys if ring.get(k) != before[k]]
assert all(ring.get(k) == "d" for k in moved)
assert 0.15 < len(moved) / len(keys) < 0.35
ring.remove("d")
assert all(ring.get(k) == before[k] for k in keys)
assert HashRing().get("x") is None

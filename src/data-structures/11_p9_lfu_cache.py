# Topic: P9. LFU Cache (brief)
# Section: 5. Caches (LRU / LFU)
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)
# Scenario (novice): Cache values and, when full, remove the value used least
# often; break frequency ties by removing the least recently used.
# Implementation (developer): Track values and frequencies in maps, with
# ordered frequency buckets and a minimum-frequency pointer.

from collections import defaultdict, OrderedDict
 
class LFUCache:
    def __init__(self, capacity):
        self.cap = capacity
        self.vals, self.freq = {}, {}
        self.buckets = defaultdict(OrderedDict)
        self.min_freq = 0
 
    def _touch(self, key):
        f = self.freq[key]
        del self.buckets[f][key]
        if not self.buckets[f]:
            del self.buckets[f]
            if self.min_freq == f:
                self.min_freq = f + 1
        self.freq[key] = f + 1
        self.buckets[f + 1][key] = None
 
    def get(self, key):
        if key not in self.vals:
            return -1
        self._touch(key)
        return self.vals[key]
 
    def put(self, key, value):
        if self.cap <= 0:
            return
        if key in self.vals:
            self.vals[key] = value
            self._touch(key)
            return
        if len(self.vals) >= self.cap:
            bucket = self.buckets[self.min_freq]
            old, _ = bucket.popitem(last=False)
            if not bucket:
                del self.buckets[self.min_freq]
            del self.vals[old], self.freq[old]
        self.vals[key] = value
        self.freq[key] = 1
        self.buckets[1][key] = None
        self.min_freq = 1
 
c = LFUCache(2)
c.put(1, 1); c.put(2, 2)
assert c.get(1) == 1
c.put(3, 3)                         # evicts 2 (freq 1)
assert c.get(2) == -1 and c.get(3) == 3
c.put(4, 4)                         # 1 and 3 tie: LRU is 1
assert (c.get(1), c.get(3), c.get(4)) == (-1, 3, 4)

# Topic: P22. Bloom Filter (concept + sketch)
# Section: 9. Specialized Structures: Trie, Scheduler Heap, Ring Buffer, Bloom Filter
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)

import hashlib
import math
 
class BloomFilter:
    def __init__(self, n_items, fp_rate=0.01):
        m = -n_items * math.log(fp_rate) / math.log(2) ** 2
        self.m = max(8, int(m))                 # bits
        k = self.m / n_items * math.log(2)
        self.k = max(1, round(k))               # hashes
        self.bits = bytearray((self.m + 7) // 8)
 
    def _positions(self, item):
        d = hashlib.sha256(item.encode()).digest()
        h1 = int.from_bytes(d[:8], "big")
        h2 = int.from_bytes(d[8:16], "big") | 1
        return [(h1 + i * h2) % self.m
                for i in range(self.k)]
 
    def add(self, item):
        for p in self._positions(item):
            self.bits[p // 8] |= 1 << (p % 8)
 
    def __contains__(self, item):
        return all(self.bits[p // 8] & (1 << (p % 8))
                   for p in self._positions(item))
 
bf = BloomFilter(1000, 0.01)
for i in range(1000):
    bf.add(f"key-{i}")
assert all(f"key-{i}" in bf for i in range(1000))  # no FN
fp = sum(f"other-{i}" in bf for i in range(10000)) / 10000
assert fp < 0.03

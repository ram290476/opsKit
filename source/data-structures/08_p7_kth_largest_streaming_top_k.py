# Topic: P7. Kth Largest / Streaming Top-K
# Section: 4. Heaps & Top-K
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)

import heapq
 
def kth_largest(nums, k):
    heap = nums[:k]
    heapq.heapify(heap)
    for x in nums[k:]:
        if x > heap[0]:
            heapq.heapreplace(heap, x)
    return heap[0]
 
class KthLargest:
    def __init__(self, k, nums=()):
        self.k, self.heap = k, []
        for x in nums:
            self.add(x)
 
    def add(self, val):
        if len(self.heap) < self.k:
            heapq.heappush(self.heap, val)
        elif val > self.heap[0]:
            heapq.heapreplace(self.heap, val)
        return self.heap[0]
 
assert kth_largest([3, 2, 1, 5, 6, 4], 2) == 5
assert kth_largest([3, 2, 3, 1, 2, 4, 5, 5, 6], 4) == 4
kl = KthLargest(3, [4, 5, 8, 2])
assert [kl.add(x) for x in (3, 5, 10, 9, 4)] == \
    [4, 5, 5, 8, 8]

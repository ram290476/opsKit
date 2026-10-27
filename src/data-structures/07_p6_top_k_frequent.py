# Topic: P6. Top K Frequent Elements (heap and bucket)
# Section: 4. Heaps & Top-K
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)

import heapq
from collections import Counter
 
def top_k_heap(nums, k):
    heap = []                       # (count, value), size k
    for val, cnt in Counter(nums).items():
        heapq.heappush(heap, (cnt, val))
        if len(heap) > k:
            heapq.heappop(heap)     # evict least frequent
    return [v for _, v in sorted(heap, reverse=True)]
 
def top_k_bucket(nums, k):
    buckets = [[] for _ in range(len(nums) + 1)]
    for val, cnt in Counter(nums).items():
        buckets[cnt].append(val)
    out = []
    for cnt in range(len(nums), 0, -1):
        for val in buckets[cnt]:
            out.append(val)
            if len(out) == k:
                return out
    return out
 
for f in (top_k_heap, top_k_bucket):
    assert f([1, 1, 1, 2, 2, 3], 2) == [1, 2]
    assert f([7], 1) == [7]
    assert f([], 3) == []
# one-liner you can mention: Counter(nums).most_common(k)

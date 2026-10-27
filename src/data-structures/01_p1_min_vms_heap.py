# Topic: P1. Minimum VMs / Minimum Platforms / Meeting Rooms II
# Section: 3. Intervals & Sweep Line
# Block: Option A: sort + min-heap (also tells you WHEN VMs free up)
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)

import heapq
 
def min_vms_heap(jobs):
    """jobs: list of (start, end). end == start is
    NOT an overlap, so a freed VM is reused."""
    ends = []                       # min-heap of end times
    for start, end in sorted(jobs):
        if ends and ends[0] <= start:
            heapq.heapreplace(ends, end)   # reuse a VM
        else:
            heapq.heappush(ends, end)      # new VM
    return len(ends)                # never shrinks = peak
 
assert min_vms_heap([(0, 30), (5, 10), (15, 20)]) == 2
assert min_vms_heap([(1, 5), (5, 10)]) == 1
assert min_vms_heap([(1, 2), (1, 2), (1, 2)]) == 3
assert min_vms_heap([]) == 0

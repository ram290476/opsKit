# Topic: P1. Minimum VMs / Minimum Platforms / Meeting Rooms II
# Section: 3. Intervals & Sweep Line
# Block: Option B: start/end sweep with a counter (peak overlap)
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)

def min_vms_sweep(jobs):
    starts = sorted(s for s, _ in jobs)
    ends = sorted(e for _, e in jobs)
    cur = peak = j = 0
    for s in starts:
        while j < len(ends) and ends[j] <= s:
            cur -= 1                # job finished: VM free
            j += 1
        cur += 1                    # this job takes a VM
        peak = max(peak, cur)
    return peak
 
def min_vms_events(jobs):
    events = []
    for s, e in jobs:
        events += [(s, 1), (e, -1)]
    events.sort()                   # (t,-1) before (t,+1)
    cur = peak = 0
    for _, delta in events:
        cur += delta
        peak = max(peak, cur)
    return peak
 
for f in (min_vms_sweep, min_vms_events):
    assert f([(0, 30), (5, 10), (15, 20)]) == 2
    assert f([(1, 5), (5, 10)]) == 1
    assert f([]) == 0

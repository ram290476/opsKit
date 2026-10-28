# Topic: P5. Non-overlapping Intervals (minimum removals)
# Section: 3. Intervals & Sweep Line
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)
# Scenario (novice): Find the fewest time ranges to remove so the remaining
# ranges do not overlap.
# Implementation (developer): Greedily keep intervals ordered by end time
# whenever they start at or after the last kept interval's end.

def erase_overlap_intervals(intervals):
    removed, prev_end = 0, float("-inf")
    for s, e in sorted(intervals, key=lambda x: x[1]):
        if s >= prev_end:
            prev_end = e            # keep it
        else:
            removed += 1            # overlaps: drop it
    return removed
 
assert erase_overlap_intervals(
    [[1, 2], [2, 3], [3, 4], [1, 3]]) == 1
assert erase_overlap_intervals(
    [[1, 2], [1, 2], [1, 2]]) == 2
assert erase_overlap_intervals([[1, 2], [2, 3]]) == 0
assert erase_overlap_intervals([]) == 0

# Topic: P4. Insert Interval
# Section: 3. Intervals & Sweep Line
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)

def insert(intervals, new):
    """intervals: sorted, non-overlapping."""
    out, i, n = [], 0, len(intervals)
    s, e = new
    while i < n and intervals[i][1] < s:     # before
        out.append(intervals[i])
        i += 1
    while i < n and intervals[i][0] <= e:    # overlap
        s = min(s, intervals[i][0])
        e = max(e, intervals[i][1])
        i += 1
    out.append([s, e])
    out.extend(intervals[i:])                 # after
    return out
 
assert insert([[1, 3], [6, 9]], [2, 5]) == [[1, 5], [6, 9]]
assert insert([[1, 2], [3, 5], [6, 7], [8, 10], [12, 16]],
              [4, 8]) == [[1, 2], [3, 10], [12, 16]]
assert insert([], [5, 7]) == [[5, 7]]
assert insert([[1, 5]], [6, 8]) == [[1, 5], [6, 8]]

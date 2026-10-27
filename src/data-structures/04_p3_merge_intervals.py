# Topic: P3. Merge Intervals
# Section: 3. Intervals & Sweep Line
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)

def merge(intervals):
    out = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:     # overlaps/touches
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out
 
assert merge([[1, 3], [2, 6], [8, 10], [15, 18]]) == \
    [[1, 6], [8, 10], [15, 18]]
assert merge([[1, 4], [4, 5]]) == [[1, 5]]
assert merge([[1, 4], [2, 3]]) == [[1, 4]]     # contained
assert merge([]) == []

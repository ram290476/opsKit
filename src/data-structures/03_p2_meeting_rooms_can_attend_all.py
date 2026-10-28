# Topic: P2. Meeting Rooms I (can one VM run every job?)
# Section: 3. Intervals & Sweep Line
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)
# Scenario (novice): Decide whether one person or VM can handle every meeting
# without being scheduled for two at once.
# Implementation (developer): Sort intervals by start time and compare each
# meeting with its successor; touching endpoints are allowed.

def can_attend_all(meetings):
    meetings = sorted(meetings)
    for (s1, e1), (s2, e2) in zip(meetings, meetings[1:]):
        if s2 < e1:                 # e1 == s2 is fine
            return False
    return True
 
assert can_attend_all([(0, 30), (5, 10)]) is False
assert can_attend_all([(7, 10), (2, 4), (4, 6)]) is True
assert can_attend_all([]) is True

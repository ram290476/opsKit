# Topic: P23. Two-Sum / Hashmap Basics
# Section: 10. Hashmap & Stack Fundamentals
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)

from collections import Counter, defaultdict
 
def two_sum(nums, target):
    seen = {}                       # value -> index
    for i, x in enumerate(nums):
        if target - x in seen:
            return [seen[target - x], i]
        seen[x] = i
    return []
 
assert two_sum([2, 7, 11, 15], 9) == [0, 1]
assert two_sum([3, 3], 6) == [0, 1]
assert two_sum([1, 2], 7) == []
 
# Idioms: group, count, dedupe (order-preserving)
hosts = [("h1", "us-east-1a"), ("h2", "us-east-1b"),
         ("h3", "us-east-1a")]
by_az = defaultdict(list)
for h, az in hosts:
    by_az[az].append(h)
assert by_az["us-east-1a"] == ["h1", "h3"]
assert Counter(az for _, az in hosts)["us-east-1a"] == 2
assert list(dict.fromkeys([3, 1, 3, 2, 1])) == [3, 1, 2]

# Topic: P18. Union-Find (network partitions)
# Section: 8. Graphs: Topological Sort, BFS/DFS, Dijkstra, Union-Find
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)
# Scenario (novice): Group hosts into connected network partitions based on
# links between them.
# Implementation (developer): Use disjoint-set union with path halving and
# union by size, then collect hosts by representative.

class UnionFind:
    def __init__(self, nodes):
        self.parent = {n: n for n in nodes}
        self.size = {n: 1 for n in nodes}
        self.count = len(self.parent)   # components
 
    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]          # path halving
        return x
 
    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False                # redundant link
        if self.size[ra] < self.size[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra            # union by size
        self.size[ra] += self.size[rb]
        self.count -= 1
        return True
 
def partitions(hosts, links):
    uf = UnionFind(hosts)
    for a, b in links:
        uf.union(a, b)
    groups = {}
    for h in hosts:
        groups.setdefault(uf.find(h), []).append(h)
    return sorted(groups.values())
 
links = [(1, 2), (2, 3), (4, 5)]
assert partitions([1, 2, 3, 4, 5], links) == \
    [[1, 2, 3], [4, 5]]
uf = UnionFind("abc")
assert uf.union("a", "b") and uf.union("b", "c")
assert uf.union("a", "c") is False   # redundant
assert uf.count == 1

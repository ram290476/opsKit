# Topic: P16. BFS/DFS on Service Graphs (blast radius)
# Section: 8. Graphs: Topological Sort, BFS/DFS, Dijkstra, Union-Find
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)

from collections import defaultdict, deque
 
def reverse(graph):                 # {svc: [deps]}
    rev = defaultdict(list)
    for svc, deps in graph.items():
        for d in deps:
            rev[d].append(svc)
    return rev
 
def blast_radius(graph, failed, max_hops=None):
    callers = reverse(graph)
    dist = {failed: 0}
    q = deque([failed])
    while q:
        s = q.popleft()
        if max_hops is not None and dist[s] == max_hops:
            continue
        for up in callers.get(s, []):
            if up not in dist:
                dist[up] = dist[s] + 1
                q.append(up)
    del dist[failed]
    return dist
 
def reachable_dfs(graph, start):
    seen, stack = {start}, [start]
    while stack:
        for nxt in graph.get(stack.pop(), []):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen - {start}
 
g = {"web": ["api"], "api": ["db"], "worker": ["db"],
     "db": []}
assert blast_radius(g, "db") == \
    {"api": 1, "worker": 1, "web": 2}
assert blast_radius(g, "db", max_hops=1) == \
    {"api": 1, "worker": 1}
assert reachable_dfs(g, "web") == {"api", "db"}

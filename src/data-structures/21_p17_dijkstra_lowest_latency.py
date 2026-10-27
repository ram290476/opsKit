# Topic: P17. Dijkstra (brief): lowest-latency path
# Section: 8. Graphs: Topological Sort, BFS/DFS, Dijkstra, Union-Find
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)

import heapq
 
def dijkstra(graph, src):
    """graph: {u: [(v, latency_ms)]}, weights >= 0."""
    dist = {src: 0}
    pq = [(0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, float("inf")):
            continue                # stale entry
        for v, w in graph.get(u, []):
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return dist
 
g = {"A": [("B", 5), ("C", 1)], "C": [("B", 2), ("D", 7)],
     "B": [("D", 1)]}
assert dijkstra(g, "A") == {"A": 0, "B": 3, "C": 1, "D": 4}
assert dijkstra({}, "Z") == {"Z": 0}

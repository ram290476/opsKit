# Topic: P15. Dependency Ordering / Topological Sort (deploy order, cycle detection)
# Section: 8. Graphs: Topological Sort, BFS/DFS, Dijkstra, Union-Find
# Block: DFS three-color cycle finder (returns the actual cycle)
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)

def find_cycle(graph):
    """graph: {node: [deps]}. Returns a cycle or None."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color, path = {}, []
 
    def dfs(u):
        color[u] = GRAY
        path.append(u)
        for v in graph.get(u, []):
            c = color.get(v, WHITE)
            if c == GRAY:                 # back-edge
                return path[path.index(v):] + [v]
            if c == WHITE:
                found = dfs(v)
                if found:
                    return found
        path.pop()
        color[u] = BLACK
        return None
 
    for n in graph:
        if color.get(n, WHITE) == WHITE:
            found = dfs(n)
            if found:
                return found
    return None
 
g = {"a": ["b"], "b": ["c"], "c": ["a"], "d": []}
assert find_cycle(g) == ["a", "b", "c", "a"]
assert find_cycle({"a": ["b"], "b": []}) is None

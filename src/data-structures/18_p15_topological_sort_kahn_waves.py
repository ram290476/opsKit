# Topic: P15. Dependency Ordering / Topological Sort (deploy order, cycle detection)
# Section: 8. Graphs: Topological Sort, BFS/DFS, Dijkstra, Union-Find
# Block: Kahn's algorithm with parallel waves
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)
# Scenario (novice): Work out which services can be deployed first when some
# services depend on others, and report dependency cycles.
# Implementation (developer): Use Kahn's indegree algorithm to emit parallel
# deployment waves; if nodes remain, raise an error for the cycle.

from collections import defaultdict
 
def deploy_waves(services, deps):
    """deps: (svc, depends_on) pairs."""
    indeg = {s: 0 for s in services}
    users = defaultdict(list)       # dep -> dependents
    for svc, dep in deps:
        users[dep].append(svc)
        indeg[svc] += 1
    wave = [s for s in services if indeg[s] == 0]
    waves, seen = [], 0
    while wave:
        waves.append(wave)
        seen += len(wave)
        nxt = []
        for s in wave:
            for u in users[s]:
                indeg[u] -= 1
                if indeg[u] == 0:
                    nxt.append(u)
        wave = nxt
    if seen != len(services):
        stuck = [s for s in services if indeg[s] > 0]
        raise ValueError(f"dependency cycle among {stuck}")
    return waves
 
svcs = ["web", "api", "db", "cache"]
deps = [("api", "db"), ("api", "cache"), ("web", "api")]
assert deploy_waves(svcs, deps) == \
    [["db", "cache"], ["api"], ["web"]]
try:
    deploy_waves(["a", "b"], [("a", "b"), ("b", "a")])
    raise AssertionError("cycle not detected")
except ValueError as e:
    assert "cycle" in str(e)

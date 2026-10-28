# Topic: P19. Trie for Prefix / Route Matching
# Section: 9. Specialized Structures: Trie, Scheduler Heap, Ring Buffer, Bloom Filter
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)
# Scenario (novice): Send a request path to the backend registered for its
# most specific matching route prefix.
# Implementation (developer): Store path segments in a trie, support wildcard
# segment lookup, and retain the deepest backend match.

class TrieNode:
    __slots__ = ("children", "backend")
 
    def __init__(self):
        self.children = {}
        self.backend = None
 
class RouteTrie:
    def __init__(self):
        self.root = TrieNode()
 
    @staticmethod
    def _parts(path):
        return [p for p in path.split("/") if p]
 
    def add(self, prefix, backend):
        node = self.root
        for part in self._parts(prefix):
            if part not in node.children:
                node.children[part] = TrieNode()
            node = node.children[part]
        node.backend = backend
 
    def match(self, path):
        node, best = self.root, self.root.backend
        for part in self._parts(path):
            nxt = node.children.get(part) or \
                node.children.get("*")
            if nxt is None:
                break
            node = nxt
            if node.backend is not None:
                best = node.backend
        return best
 
r = RouteTrie()
r.add("/", "web"); r.add("/api", "api")
r.add("/api/v1/users", "users")
r.add("/api/*/health", "hc")
assert r.match("/api/v1/users/42") == "users"
assert r.match("/api/v2/x") == "api"
assert r.match("/api/v9/health") == "hc"
assert r.match("/static/a.css") == "web"
assert RouteTrie().match("/x") is None

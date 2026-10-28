# Topic: P8. LRU Cache (OrderedDict and hashmap + doubly linked list)
# Section: 5. Caches (LRU / LFU)
# Block: Version 2: hashmap + doubly linked list (what interviewers usually want)
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)
# Scenario (novice): Build a cache that keeps recently used values and removes
# the least recently used value when capacity is reached.
# Implementation (developer): Combine a key-to-node hashmap with a doubly
# linked list so lookup, recency updates, and eviction are constant-time.

class Node:
    __slots__ = ("key", "val", "prev", "next")
 
    def __init__(self, key=None, val=None):
        self.key, self.val = key, val
        self.prev = self.next = None
 
class LRUCacheDLL:
    def __init__(self, capacity):
        self.cap = capacity
        self.map = {}                       # key -> Node
        self.head, self.tail = Node(), Node()  # sentinels
        self.head.next = self.tail
        self.tail.prev = self.head
 
    def _remove(self, node):
        node.prev.next = node.next
        node.next.prev = node.prev
 
    def _add_front(self, node):
        node.prev, node.next = self.head, self.head.next
        self.head.next.prev = node
        self.head.next = node
 
    def get(self, key):
        node = self.map.get(key)
        if node is None:
            return -1
        self._remove(node)
        self._add_front(node)
        return node.val
 
    def put(self, key, value):
        if key in self.map:
            self._remove(self.map[key])
        node = Node(key, value)
        self.map[key] = node
        self._add_front(node)
        if len(self.map) > self.cap:
            lru = self.tail.prev
            self._remove(lru)
            del self.map[lru.key]
 
for cls in (LRUCache, LRUCacheDLL):
    c = cls(2)
    c.put(1, 1); c.put(2, 2)
    assert c.get(1) == 1
    c.put(3, 3)                     # evicts 2
    assert c.get(2) == -1
    c.put(4, 4)                     # evicts 1
    assert (c.get(1), c.get(3), c.get(4)) == (-1, 3, 4)

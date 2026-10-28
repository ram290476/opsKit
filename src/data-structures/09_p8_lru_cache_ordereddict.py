# Topic: P8. LRU Cache (OrderedDict and hashmap + doubly linked list)
# Section: 5. Caches (LRU / LFU)
# Block: Version 1: OrderedDict (say this first, then offer to build it yourself)
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)
# Scenario (novice): Cache recent results and discard the item that has gone
# unused for the longest time when the cache is full.
# Implementation (developer): Use OrderedDict to move accessed or updated keys
# to the newest position and evict from the oldest end.

from collections import OrderedDict
 
class LRUCache:
    def __init__(self, capacity):
        self.cap = capacity
        self.data = OrderedDict()
 
    def get(self, key):
        if key not in self.data:
            return -1
        self.data.move_to_end(key)  # mark most recent
        return self.data[key]
 
    def put(self, key, value):
        if key in self.data:
            self.data.move_to_end(key)
        self.data[key] = value
        if len(self.data) > self.cap:
            self.data.popitem(last=False)   # evict LRU

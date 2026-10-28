# Data Structures Interview Questions: Python Samples

Every Python code sample from **Data Structures Interview Questions - Platform and SRE Roles** (prepared Oct 20, 2026), in the order it appears in the document. Each sample is in its own file.

**Source document:** `/workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx` (PDF render: `Data_Structures_Interview_Questions_Platform_SRE.pdf` in the same folder). The original was not modified.

## Why these patterns matter for SRE work

These aren't just interview puzzles. Each pattern below is something you'll use when running production systems.

- **Heaps and priority queues** (`01`, `07`, `08`, `21`, `24`, `29`): Schedulers, job runners and alert routers all need to pull the next most urgent or earliest-deadline item quickly. A min-heap gives you that in O(log n) per operation, which is how cron-like task schedulers, retry queues and Dijkstra-style lowest-latency routing work.
- **Hash maps for caching and dedup** (`09`, `10`, `11`, `27`, `33`, `34`, `36`, `37`): O(1) lookups power LRU/LFU caches, idempotency keys that stop a retried request from charging twice, and alert dedup that keeps one noisy failure from paging ten times. Hash map plus doubly linked list is the standard way to build an LRU eviction policy.
- **Interval sort-and-sweep** (`01`–`06`, `29`): Sort start and end events, then sweep through them, to answer capacity questions. These include how many VMs or rooms you need at peak, whether maintenance windows overlap, and how to merge or insert change-freeze periods. It's the core of capacity planning and change-calendar conflict checks.
- **Running min/max tracking** (`02`, `04`, `05`, `06`, `11`, `15`, `24`): Keeping a running peak or floor in one pass is how monitoring checks thresholds, like peak concurrency, worst latency in a window, or the lowest free capacity, without storing every data point.
- **TTL caches** (`36`, `37`, and `TTLCache` in `wrappers.py`): Entries that expire on their own model DNS and config caching, idempotency windows, and alert suppression ("don't re-fire this alert for 10 minutes"). Passing the clock in makes expiry testable without waiting for real time.
- **Top-k** (`07`, `08`, `17`, `33`, and `TopK` in `wrappers.py`): Finding the busiest IPs, noisiest endpoints or most frequent errors in a log stream is hot-spot detection. A size-k heap does it in O(n log k) memory-light passes, which matters when the log won't fit in RAM.

## How these were extracted

In the document, every code sample is a one-cell table set in Consolas. All 37 such tables were extracted with python-docx in the order they appear. There is no other monospace text, no code-styled paragraph and no text box. Each file begins with a short comment header (topic, section, source). The code below the header is copied exactly. Blank lines inside the samples are a single space, as in the .docx.

## Files

| # | File | Topic / question | Block |
|---|------|------------------|-------|
| 1 | `01_p1_min_vms_heap.py` | P1. Minimum VMs / Minimum Platforms / Meeting Rooms II | Option A: sort + min-heap (also tells you WHEN VMs free up) |
| 2 | `02_p1_min_vms_sweep_events.py` | P1. Minimum VMs / Minimum Platforms / Meeting Rooms II | Option B: start/end sweep with a counter (peak overlap) |
| 3 | `03_p2_meeting_rooms_can_attend_all.py` | P2. Meeting Rooms I (can one VM run every job?) |  |
| 4 | `04_p3_merge_intervals.py` | P3. Merge Intervals |  |
| 5 | `05_p4_insert_interval.py` | P4. Insert Interval |  |
| 6 | `06_p5_non_overlapping_intervals.py` | P5. Non-overlapping Intervals (minimum removals) |  |
| 7 | `07_p6_top_k_frequent.py` | P6. Top K Frequent Elements (heap and bucket) |  |
| 8 | `08_p7_kth_largest_streaming_top_k.py` | P7. Kth Largest / Streaming Top-K |  |
| 9 | `09_p8_lru_cache_ordereddict.py` | P8. LRU Cache (OrderedDict and hashmap + doubly linked list) | Version 1: OrderedDict (say this first, then offer to build it yourself) |
| 10 | `10_p8_lru_cache_hashmap_dll.py` | P8. LRU Cache (OrderedDict and hashmap + doubly linked list) | Version 2: hashmap + doubly linked list (what interviewers usually want) |
| 11 | `11_p9_lfu_cache.py` | P9. LFU Cache (brief) |  |
| 12 | `12_p10_rate_limiter_token_bucket.py` | P10. Rate Limiter (token bucket, sliding window log, sliding window counter) | Token bucket |
| 13 | `13_p10_rate_limiter_sliding_window.py` | P10. Rate Limiter (token bucket, sliding window log, sliding window counter) | Sliding window log and sliding window counter |
| 14 | `14_p11_consistent_hashing_vnodes.py` | P11. Consistent Hashing with Virtual Nodes (bisect ring) |  |
| 15 | `15_p12_load_balancing_strategies.py` | P12. Load Balancing Strategies |  |
| 16 | `16_p13_sliding_window_error_rate.py` | P13. Sliding Window Log Analysis (error rate in the last N minutes) |  |
| 17 | `17_p14_parse_logs_top_ips.py` | P14. Parse Logs and Count Top IPs (hashmap) |  |
| 18 | `18_p15_topological_sort_kahn_waves.py` | P15. Dependency Ordering / Topological Sort (deploy order, cycle detection) | Kahn's algorithm with parallel waves |
| 19 | `19_p15_dfs_three_color_cycle_finder.py` | P15. Dependency Ordering / Topological Sort (deploy order, cycle detection) | DFS three-color cycle finder (returns the actual cycle) |
| 20 | `20_p16_bfs_dfs_blast_radius.py` | P16. BFS/DFS on Service Graphs (blast radius) |  |
| 21 | `21_p17_dijkstra_lowest_latency.py` | P17. Dijkstra (brief): lowest-latency path |  |
| 22 | `22_p18_union_find_partitions.py` | P18. Union-Find (network partitions) |  |
| 23 | `23_p19_trie_prefix_route_matching.py` | P19. Trie for Prefix / Route Matching |  |
| 24 | `24_p20_min_heap_task_scheduler.py` | P20. Min-Heap Scheduler / Task Scheduler |  |
| 25 | `25_p21_ring_buffer_metrics.py` | P21. Circular Buffer / Ring Buffer for Metrics |  |
| 26 | `26_p22_bloom_filter.py` | P22. Bloom Filter (concept + sketch) |  |
| 27 | `27_p23_two_sum_hashmap.py` | P23. Two-Sum / Hashmap Basics |  |
| 28 | `28_p24_valid_parentheses_config_validation.py` | P24. Valid Parentheses / Stack-based Config Validation |  |
| 29 | `29_s1_job_task_scheduling.py` | S1. Job / Task Scheduling (heap priority queue + intervals) |  |
| 30 | `30_s2_batch_processing_chunking.py` | S2. Batch Processing (chunking + generators) |  |
| 31 | `31_s3_queue_management_backpressure_dlq.py` | S3. Queue Management (deque, bounded queues, backpressure, DLQ) |  |
| 32 | `32_s4_config_parsing_validation.py` | S4. Config Parsing / Validation (dicts, nested merge, schema) |  |
| 33 | `33_s5_log_parsing_regex_topk.py` | S5. Log Parsing (regex + hashmap counters + top-K) |  |
| 34 | `34_s6_health_check_aggregation.py` | S6. Health-Check Aggregation (hashmap + sliding window + quorum) |  |
| 35 | `35_s7_deployment_rollback.py` | S7. Deployment Rollback Logic (stack of versions + canary thresholds) |  |
| 36 | `36_s8_idempotent_retry_backoff.py` | S8. Idempotent Retry Handling (backoff + jitter, idempotency keys, TTL) |  |
| 37 | `37_s9_dedup_ttl_caching.py` | S9. Dedup / Caching with Hashmaps (TTL memoize, alert dedup) |  |

## Compile / run status

- `python3 -m py_compile` (Python 3.13.5): all 37 files compile.
- Running each file on its own: 36 of 37 pass their built-in asserts. `10_p8_lru_cache_hashmap_dll.py` raises `NameError: LRUCache` when run alone, because its tests reuse the `LRUCache` class defined in the previous sample (`09_p8_lru_cache_ordereddict.py`). It was left unchanged to keep the code exactly as in the document.

## Pattern analysis and shared wrappers

- [`ANALYSIS.md`](ANALYSIS.md): the recurring cross-cutting patterns across all 37 samples, ranked by how many samples use each, with sample lists, notes, a proposed wrapper API and a refactor map. The counts come from an AST scan you can rerun with `python tools/analyze_patterns.py`.
- [`wrappers.py`](wrappers.py): the three highest-value wrappers, implemented with the standard library only: `FakeClock` (time injection), `TTLCache` / `ttl_cache` (TTL + LRU cache, dedup, idempotent replay) and `TopK` / `top_k` (bounded top-k heap). Run `python wrappers.py` for the usage demo.
- [`tests/test_wrappers.py`](tests/test_wrappers.py): unit tests, plus equivalence tests that check the wrappers against the original sample classes. Run them with `python tests/test_wrappers.py` or `pytest tests/`.

The 37 sample files are unchanged. The wrappers show how the samples *could* be refactored.
See also the [AIOps/SRE mock-interview solutions](aiops-mock-interview/README.md).

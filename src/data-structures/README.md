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

In the document, every code sample is a one-cell table set in Consolas. All 37 such tables were extracted with python-docx in the order they appear. There is no other monospace text, no code-styled paragraph and no text box. Each file begins with a short comment header containing its topic, section, and source, followed by a novice-friendly scenario summary and a developer-focused implementation summary. The sample code follows these comments. Blank lines inside the samples are a single space, as in the .docx.

## Files

| # | File | Scenario | Implementation |
|---|------|----------|----------------|
| 1 | `01_p1_min_vms_heap.py` | Find the fewest virtual machines needed to run jobs that may overlap in time. | Sort jobs by start time and track VM release times in a min-heap; reuse the earliest-free VM when possible. |
| 2 | `02_p1_min_vms_sweep_events.py` | Find the fewest virtual machines needed when jobs can run at the same time. | Sweep sorted start/end events, processing ends before starts at equal times, and track the peak concurrent job count. |
| 3 | `03_p2_meeting_rooms_can_attend_all.py` | Decide whether one person or VM can handle every meeting without being scheduled for two at once. | Sort intervals by start time and compare each meeting with its successor; touching endpoints are allowed. |
| 4 | `04_p3_merge_intervals.py` | Combine overlapping or touching time ranges into a shorter list of ranges that covers the same time. | Sort by start, then merge each interval into the last output interval when their boundaries overlap or touch. |
| 5 | `05_p4_insert_interval.py` | Add one time range to an already sorted, non-overlapping list while combining any ranges it intersects. | Copy earlier intervals, expand the new interval across overlaps, then append it and the untouched later intervals. |
| 6 | `06_p5_non_overlapping_intervals.py` | Find the fewest time ranges to remove so the remaining ranges do not overlap. | Greedily keep intervals ordered by end time whenever they start at or after the last kept interval's end. |
| 7 | `07_p6_top_k_frequent.py` | Find the k values that occur most often in a list. | Compare a size-k min-heap approach with frequency-indexed buckets built from a Counter. |
| 8 | `08_p7_kth_largest_streaming_top_k.py` | Keep track of the kth-largest value, including as new numbers arrive one at a time. | Maintain a min-heap of at most k largest values; its root is the kth-largest once the heap contains k values. |
| 9 | `09_p8_lru_cache_ordereddict.py` | Cache recent results and discard the item that has gone unused for the longest time when the cache is full. | Use OrderedDict to move accessed or updated keys to the newest position and evict from the oldest end. |
| 10 | `10_p8_lru_cache_hashmap_dll.py` | Build a cache that keeps recently used values and removes the least recently used value when capacity is reached. | Combine a key-to-node hashmap with a doubly linked list so lookup, recency updates, and eviction are constant-time. |
| 11 | `11_p9_lfu_cache.py` | Cache values and, when full, remove the value used least often; break frequency ties by removing the least recently used. | Track values and frequencies in maps, with ordered frequency buckets and a minimum-frequency pointer. |
| 12 | `12_p10_rate_limiter_token_bucket.py` | Limit how quickly requests are accepted while still allowing a short burst after a quiet period. | Refill tokens from elapsed monotonic time up to a capacity, then accept a request only if its token cost is available. |
| 13 | `13_p10_rate_limiter_sliding_window.py` | Limit requests over recent time so a fixed time boundary does not permit an unexpectedly large burst. | Demonstrate an exact timestamp deque and a lower-memory counter that estimates traffic across adjacent windows. |
| 14 | `14_p11_consistent_hashing_vnodes.py` | Assign keys to servers so adding or removing a server moves only some keys instead of reshuffling them all. | Place each server's virtual nodes on a sorted hash ring and use binary search to find the next owner for a key. |
| 15 | `15_p12_load_balancing_strategies.py` | Choose which server should receive each new request. | Compare round-robin, smooth weighted round robin, least-connections tracking, and the power-of-two choices strategy. |
| 16 | `16_p13_sliding_window_error_rate.py` | Calculate what share of recent requests or events failed. | Keep timestamped events in a deque, maintain an error count as old events expire, and compute the current-window ratio. |
| 17 | `17_p14_parse_logs_top_ips.py` | Read access logs to find the IP addresses making the most requests, optionally counting only server errors. | Match log fields with a compiled regex, count valid records with Counter, and separately report malformed lines. |
| 18 | `18_p15_topological_sort_kahn_waves.py` | Work out which services can be deployed first when some services depend on others, and report dependency cycles. | Use Kahn's indegree algorithm to emit parallel deployment waves; if nodes remain, raise an error for the cycle. |
| 19 | `19_p15_dfs_three_color_cycle_finder.py` | Find an actual loop in a set of dependency links. | Run depth-first search with unvisited, active, and complete colors; a link to an active node identifies the cycle path. |
| 20 | `20_p16_bfs_dfs_blast_radius.py` | See which services may be affected if one service fails, and optionally limit the result to nearby dependency levels. | Reverse dependency edges and run BFS for hop-distance results; also provide iterative DFS reachability. |
| 21 | `21_p17_dijkstra_lowest_latency.py` | Find the lowest total network latency from one service to every reachable service. | Use Dijkstra's algorithm with a min-heap; edge weights must be non-negative, and outdated heap entries are skipped. |
| 22 | `22_p18_union_find_partitions.py` | Group hosts into connected network partitions based on links between them. | Use disjoint-set union with path halving and union by size, then collect hosts by representative. |
| 23 | `23_p19_trie_prefix_route_matching.py` | Send a request path to the backend registered for its most specific matching route prefix. | Store path segments in a trie, support wildcard segment lookup, and retain the deepest backend match. |
| 24 | `24_p20_min_heap_task_scheduler.py` | Run tasks when they are due, including tasks that repeat, and calculate the shortest schedule with a required cooldown. | Order scheduled tasks by run time in a min-heap with a sequence tie-breaker; compute cooldown length from task frequencies. |
| 25 | `25_p21_ring_buffer_metrics.py` | Keep only the newest measurements and calculate their average without storing an ever-growing history. | Write into a fixed-size circular array and maintain a running total as old values are overwritten. |
| 26 | `26_p22_bloom_filter.py` | Quickly check whether an item might have been seen before, using much less memory than storing every item. | Set multiple deterministic bit positions per item; membership can have false positives but never false negatives. |
| 27 | `27_p23_two_sum_hashmap.py` | Find two numbers that add to a target, and see common hashmap tasks such as grouping, counting, and ordered deduplication. | Store previously seen values and indices to solve two-sum in one pass; demonstrate defaultdict, Counter, and dict order. |
| 28 | `28_p24_valid_parentheses_config_validation.py` | Check that brackets are balanced, including in config text where bracket characters inside quoted strings should be ignored. | Use a stack to match bracket types and retain opening locations so mismatches can be reported with line and column. |
| 29 | `29_s1_job_task_scheduling.py` | Assign prioritized jobs to workers and check whether a job's time range conflicts with a deployment freeze. | Dispatch from a priority heap to workers ordered by availability, and binary-search sorted merged freeze intervals. |
| 30 | `30_s2_batch_processing_chunking.py` | Process a large or streaming set of hosts in manageable groups and stop if too many operations fail. | Yield chunks lazily with islice, process each batch, and compare the cumulative failure ratio with a threshold. |
| 31 | `31_s3_queue_management_backpressure_dlq.py` | Handle incoming work without accepting more than the queue can hold, retry failures, and retain repeatedly failing messages. | Bound a deque for backpressure, requeue up to a retry limit, then record failed messages and errors in a dead-letter queue. |
| 32 | `32_s4_config_parsing_validation.py` | Combine default settings with overrides and report missing or incorrectly typed configuration values. | Recursively merge nested mappings, then walk a schema to collect validation errors, including bool-versus-int handling. |
| 33 | `33_s5_log_parsing_regex_topk.py` | Summarize logs by finding routes with the most server errors and their high-percentile response latency. | Parse key-value fields with regex, aggregate counts and latency samples, then calculate p95 and top error routes. |
| 34 | `34_s6_health_check_aggregation.py` | Decide whether a service is up, degraded, or down from recent health checks of its instances. | Keep a bounded probe history per instance, apply a failure threshold, and aggregate healthy instances using quorum. |
| 35 | `35_s7_deployment_rollback.py` | Track deployed versions so a release can be rolled back when a gradual canary rollout shows too many errors. | Store deployment history as a stack and compare canary error rates with a baseline, request minimum, and absolute floor. |
| 36 | `36_s8_idempotent_retry_backoff.py` | Retry temporary failures without overwhelming a service, and avoid repeating work for duplicate requests. | Generate capped exponential backoff with jitter and cache idempotency results until their monotonic-clock TTL expires. |
| 37 | `37_s9_dedup_ttl_caching.py` | Reuse recently computed results and avoid sending the same alert repeatedly during a short time window. | Cache function results by arguments with TTL expiry, and deduplicate alerts by fingerprint and last-sent timestamp. |

## Compile / run status

- `python3 -m py_compile` (Python 3.13.5): all 37 files compile.
- Running each file on its own: 36 of 37 pass their built-in asserts. `10_p8_lru_cache_hashmap_dll.py` raises `NameError: LRUCache` when run alone, because its tests reuse the `LRUCache` class defined in the previous sample (`09_p8_lru_cache_ordereddict.py`). It was left unchanged to keep the code exactly as in the document.

## Pattern analysis and shared wrappers

- [`ANALYSIS.md`](ANALYSIS.md): the recurring cross-cutting patterns across all 37 samples, ranked by how many samples use each, with sample lists, notes, a proposed wrapper API and a refactor map. The counts come from an AST scan you can rerun with `python tools/analyze_patterns.py`.
- [`wrappers.py`](wrappers.py): the three highest-value wrappers, implemented with the standard library only: `FakeClock` (time injection), `TTLCache` / `ttl_cache` (TTL + LRU cache, dedup, idempotent replay) and `TopK` / `top_k` (bounded top-k heap). Run `python wrappers.py` for the usage demo.
- [`tests/test_wrappers.py`](tests/test_wrappers.py): unit tests, plus equivalence tests that check the wrappers against the original sample classes. Run them with `python tests/test_wrappers.py` or `pytest tests/`.

The 37 samples remain standalone; their headers now summarize each scenario for learners and the implementation approach for developers. The wrappers show how the samples *could* be refactored.
See also the [AIOps/SRE mock-interview solutions](aiops-mock-interview/README.md).

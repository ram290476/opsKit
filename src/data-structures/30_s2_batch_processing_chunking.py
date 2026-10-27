# Topic: S2. Batch Processing (chunking + generators)
# Section: 11. SRE/Platform Day-to-Day Scripting & Automation
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)

from itertools import islice
 
def chunked(iterable, size):
    """Yield lists of up to `size` items, lazily."""
    it = iter(iterable)
    while batch := list(islice(it, size)):
        yield batch
 
def process_hosts(hosts, action, batch_size=50,
                  max_fail_ratio=0.1):
    done, failed = [], []
    for batch in chunked(hosts, batch_size):
        for h in batch:
            (done if action(h) else failed).append(h)
        seen = len(done) + len(failed)
        if len(failed) > max_fail_ratio * seen:
            raise RuntimeError(f"halted after {seen} hosts,"
                               f" {len(failed)} failed")
    return done, failed
 
assert list(chunked(range(7), 3)) == [[0, 1, 2], [3, 4, 5],
                                      [6]]
assert list(chunked([], 3)) == []
hosts = (f"h{i}" for i in range(100))    # generator
done, failed = process_hosts(hosts, lambda h: h != "h7",
                             batch_size=20)
assert len(done) == 99 and failed == ["h7"]
try:
    process_hosts(range(10), lambda h: h % 2, batch_size=4)
    raise AssertionError("should have halted")
except RuntimeError as e:
    assert "halted after 4" in str(e)

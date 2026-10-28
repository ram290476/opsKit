from collections import deque
from typing import Iterable

def detect_spikes(timestamps: Iterable[float], threshold: int,
                  window: float = 60.0) -> list[tuple[float, int]]:
    """Sliding window: return (window_start, count) whenever count > threshold."""
    q: deque[float] = deque()
    spikes: list[tuple[float, int]] = []
    in_spike = False
    for ts in sorted(timestamps):          # sort handles small out-of-order input
        q.append(ts)
        while q[0] <= ts - window:          # evict events older than window
            q.popleft()
        if len(q) > threshold and not in_spike:
            spikes.append((q[0], len(q)))
            in_spike = True
        elif len(q) <= threshold:
            in_spike = False
    return spikes

if __name__ == "__main__":
    ts = [0, 5, 10, 70, 71, 72, 73, 74, 75, 200]
    result = detect_spikes(ts, threshold=4)
    print(result)
    assert result == [(70, 5)]

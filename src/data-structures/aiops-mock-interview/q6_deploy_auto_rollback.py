import time
from typing import Callable

def watch_deploy(check_health: Callable[[], bool], rollback: Callable[[], None],
                 interval: float = 10, duration: float = 120, max_fail: int = 3,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> str:
    deadline = clock() + duration
    fails = 0
    while clock() < deadline:
        ok = check_health()
        fails = 0 if ok else fails + 1   # consecutive failures only
        if not ok: print(f"unhealthy, consecutive_fails={fails}")
        if fails >= max_fail:
            rollback()
            return "rolled_back"
        sleep(interval)
    return "healthy"

class FakeClock:
    def __init__(self) -> None: self.t = 0.0
    def now(self) -> float: return self.t
    def sleep(self, s: float) -> None: self.t += s

if __name__ == "__main__":
    c = FakeClock()
    seq = iter([True, False, True, False, False, False] + [True] * 20)
    calls: list[str] = []
    r = watch_deploy(lambda: next(seq), lambda: calls.append("rb"),
                     clock=c.now, sleep=c.sleep)
    assert r == "rolled_back" and calls == ["rb"]
    c2 = FakeClock()
    assert watch_deploy(lambda: True, lambda: None, clock=c2.now, sleep=c2.sleep) == "healthy"
    print("ok, simulated seconds:", c2.t)

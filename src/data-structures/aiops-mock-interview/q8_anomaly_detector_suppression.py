import statistics
from collections import deque, defaultdict

class AnomalyDetector:
    def __init__(self, window: int = 30, z: float = 3.0, cooldown: float = 600,
                 maintenance: dict[str, list[tuple[float, float]]] | None = None):
        self.win: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=window))
        self.window, self.z, self.cooldown = window, z, cooldown
        self.last_alert: dict[str, float] = {}
        self.maint = maintenance or {}

    def in_maintenance(self, host: str, ts: float) -> bool:
        return any(a <= ts <= b for a, b in self.maint.get(host, []))

    def observe(self, host: str, ts: float, cpu: float) -> bool:
        w = self.win[host]
        alert = False
        if len(w) == self.window:
            mu, sd = statistics.fmean(w), statistics.pstdev(w)
            score = (cpu - mu) / sd if sd > 0 else 0.0
            if (score > self.z and not self.in_maintenance(host, ts)
                    and ts - self.last_alert.get(host, -1e18) >= self.cooldown):
                self.last_alert[host] = ts
                alert = True
        w.append(cpu)          # anomaly still enters baseline; could exclude it
        return alert

if __name__ == "__main__":
    d = AnomalyDetector(maintenance={"web-2": [(2000, 2400)]})
    alerts = []
    for i in range(40):
        ts = i * 60
        for host in ("web-1", "web-2"):
            cpu = 40 + (i % 3)
            if i in (35, 36): cpu = 95          # spike; 36 suppressed by cooldown
            if d.observe(host, ts, cpu): alerts.append((host, ts))
    print(alerts)
    assert alerts == [("web-1", 2100)]       # web-2 in maintenance window

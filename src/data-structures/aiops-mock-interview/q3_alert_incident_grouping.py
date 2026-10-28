from dataclasses import dataclass
from typing import TypedDict

class Alert(TypedDict):
    service: str
    alert_name: str
    ts: int
    severity: int  # 1=low .. 4=critical

@dataclass
class Incident:
    service: str
    first: int
    last: int
    max_sev: int
    count: int
    root_alert: str

def group_alerts(alerts: list[Alert], gap: int = 300) -> list[Incident]:
    open_: dict[str, Incident] = {}
    closed: list[Incident] = []
    for a in sorted(alerts, key=lambda a: a["ts"]):
        inc = open_.get(a["service"])
        if inc and a["ts"] - inc.last <= gap:
            inc.last, inc.count = a["ts"], inc.count + 1
            inc.max_sev = max(inc.max_sev, a["severity"])
        else:
            if inc:
                closed.append(inc)      # flush the closed incident
            open_[a["service"]] = Incident(a["service"], a["ts"], a["ts"],
                                           a["severity"], 1, a["alert_name"])
    return sorted(closed + list(open_.values()), key=lambda i: i.first)

if __name__ == "__main__":
    alerts: list[Alert] = [
        {"service": "db-svc", "alert_name": "DBDown", "ts": 0, "severity": 4},
        {"service": "db-svc", "alert_name": "HighLatency", "ts": 120, "severity": 2},
        {"service": "api", "alert_name": "5xx", "ts": 60, "severity": 3},
        {"service": "db-svc", "alert_name": "DBDown", "ts": 1000, "severity": 3},
    ]
    incs = group_alerts(alerts)
    for i in incs:
        print(i)
    assert len(incs) == 3 and incs[0].count == 2 and incs[0].max_sev == 4

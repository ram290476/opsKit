import asyncio, random, time
from dataclasses import dataclass, field

@dataclass(order=True)
class Event:
    severity: int                                # 4=critical, 1=low
    alert: str = field(compare=False)
    resource: str = field(compare=False)

async def restart_pod(r: str) -> None: await _flaky()
async def scale_up(r: str) -> None: await _flaky()
async def clear_cache(r: str) -> None: await _flaky()
async def _flaky() -> None:
    await asyncio.sleep(0.01)
    if random.random() < 0.4:
        raise RuntimeError("runbook failed")

RUNBOOKS = {"PodCrashLoop": restart_pod, "HighCPU": scale_up, "StaleCache": clear_cache}
dlq: list[Event] = []
last_run: dict[str, float] = {}                  # per-resource cooldown
COOLDOWN = 60.0

async def produce(q: asyncio.Queue, ev: Event) -> None:
    if q.full() and ev.severity < 3:
        print("shed low-sev", ev.alert); return  # shed, never critical
    await q.put(ev)                              # block (backpressure)

async def remediate(ev: Event, attempts: int = 3) -> None:
    for n in range(attempts):
        try:
            await RUNBOOKS[ev.alert](ev.resource); return
        except Exception:
            await asyncio.sleep(0.01 * 2 ** n + random.uniform(0, 0.01))
    dlq.append(ev); print("PAGE on-call:", ev.alert, ev.resource)

async def worker(q: asyncio.Queue) -> None:
    while True:
        ev = await q.get()
        try:
            key = f"{ev.alert}:{ev.resource}"    # idempotency key
            if time.monotonic() - last_run.get(key, -1e9) >= COOLDOWN:
                last_run[key] = time.monotonic()
                await remediate(ev)
        finally:
            q.task_done()                        # ack after processing

async def main() -> None:
    random.seed(7)
    q: asyncio.Queue = asyncio.Queue(maxsize=5)
    workers = [asyncio.create_task(worker(q)) for _ in range(3)]
    evs = [Event(4, "PodCrashLoop", "pod-a")] * 3 + [
        Event(2, "HighCPU", f"node-{i}") for i in range(6)] + [Event(1, "StaleCache", "redis")]
    for ev in evs:
        await produce(q, ev)
    await q.join()
    for w in workers: w.cancel()
    print("ran:", sorted(last_run), "dlq:", len(dlq))

if __name__ == "__main__":
    asyncio.run(main())

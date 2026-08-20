"""In-process generation-job registry. Single operator, low volume — daemon threads, no broker.
Progress is DB-derived (the caller passes a done_fn), so a restart loses only the 'running' flag,
never produced work. A durable queue is an if-scale item, intentionally not built here."""
import threading
import uuid

JOBS: dict = {}
_LOCK = threading.Lock()
_CAP = 50


def start(kind: str, round_id: str, stage: str, total: int, fn, meta=None) -> str:
    job_id = uuid.uuid4().hex[:12]
    rec = {"job_id": job_id, "kind": kind, "round_id": round_id, "stage": stage,
           "status": "running", "total": total, "done": 0, "error": None}
    if meta:
        rec.update(meta)
    with _LOCK:
        JOBS[job_id] = rec
        if len(JOBS) > _CAP:                       # evict oldest finished jobs
            for k in [k for k, v in list(JOBS.items()) if v["status"] != "running"][: len(JOBS) - _CAP]:
                JOBS.pop(k, None)

    def _run():
        try:
            fn()
            rec["status"] = "done"
        except Exception as e:                     # noqa: BLE001
            rec["status"] = "error"; rec["error"] = str(e)
    threading.Thread(target=_run, daemon=True).start()
    return job_id


def find_running(kind: str, round_id: str, stage: str):
    with _LOCK:
        for rec in JOBS.values():
            if rec["status"] == "running" and rec["kind"] == kind and rec["round_id"] == round_id and rec["stage"] == stage:
                return dict(rec)
    return None


def status(job_id: str, done_fn=None):
    rec = JOBS.get(job_id)
    if rec is None:
        return None
    out = dict(rec)
    if done_fn is not None:                        # live DB-derived progress (authoritative)
        try:
            out["done"] = int(done_fn(rec))
        except Exception:                          # noqa: BLE001
            pass
    elif out["status"] == "done":                  # no probe given: a finished job produced all of them
        out["done"] = out["total"]
    return out

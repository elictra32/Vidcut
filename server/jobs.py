"""Background jobs with progress snapshots and cancellation."""
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from core.media import Cancelled
from server.errors import from_exception, payload

TERMINAL = ("done", "error", "cancelled")


class JobRunner:
    def __init__(self, workers: int = 2, proxy_workers: int = 1):
        self._pool = ThreadPoolExecutor(max_workers=workers)
        # preview proxies can run for tens of minutes; they get their own pool so they never starve other jobs
        self._proxy_pool = ThreadPoolExecutor(max_workers=proxy_workers)
        self._jobs: dict[str, dict] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._cond = threading.Condition()

    def submit(self, fn, name: str, pool: str = "default") -> str:
        jid = uuid.uuid4().hex[:12]
        cancel = threading.Event()
        with self._cond:
            self._jobs[jid] = {"id": jid, "name": name, "state": "queued", "percent": 0.0,
                               "message": "", "result": None, "error": None, "_v": 0}
            self._cancel[jid] = cancel
        (self._proxy_pool if pool == "proxy" else self._pool).submit(self._run, jid, fn, cancel)
        return jid

    def active(self) -> int:
        with self._cond:
            return sum(1 for j in self._jobs.values() if j["state"] not in TERMINAL)

    def _update(self, jid, **kw):
        with self._cond:
            self._jobs[jid].update(kw)
            self._jobs[jid]["_v"] += 1
            self._cond.notify_all()

    def _run(self, jid, fn, cancel):
        if cancel.is_set():
            self._update(jid, state="cancelled")
            return
        self._update(jid, state="running")

        def progress(p, msg=""):
            self._update(jid, percent=float(p), message=msg)

        try:
            result = fn(progress, cancel)
            self._update(jid, state="done", percent=1.0, result=result)
        except Cancelled:
            self._update(jid, state="cancelled")
        except Exception as e:  # noqa: BLE001 - surfaced to the UI as a Thai error
            self._update(jid, state="error", error=payload(from_exception(e)))

    def get(self, jid: str) -> dict | None:
        with self._cond:
            j = self._jobs.get(jid)
            return None if j is None else {k: v for k, v in j.items() if k != "_v"}

    def events(self, jid: str):
        """Yield a snapshot whenever the job changes, ending after a terminal state."""
        last = -1
        while True:
            with self._cond:
                j = self._jobs.get(jid)
                if j is None:
                    return
                if j["_v"] == last:
                    self._cond.wait(timeout=15)
                snap = {k: v for k, v in self._jobs[jid].items() if k != "_v"}
                last = self._jobs[jid]["_v"]
            yield snap
            if snap["state"] in TERMINAL:
                return

    def cancel(self, jid: str) -> bool:
        ev = self._cancel.get(jid)
        if ev is None:
            return False
        ev.set()
        return True

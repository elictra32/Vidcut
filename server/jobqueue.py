"""A persistent queue of long jobs (exports, episode batches). Items run one after another in the order shown; each
carries a frozen copy of the project from when it was queued, so later edits don't change what gets rendered. The queue is
saved after every change, so closing the app loses nothing: an item that was running is put back and run again."""
import json
import os
import threading
import time
import uuid

from core.media import Cancelled
from server.errors import from_exception, payload

TERMINAL = ("done", "error", "cancelled")
FILENAME = "queue.json"
PUBLIC_HIDDEN = ("project",)


class JobQueue:
    def __init__(self, home: str, runners: dict, busy=lambda: False, poll: float = 1.0):
        self.path = os.path.join(home, FILENAME)
        self.runners = runners  # kind -> fn(project_dict, params, progress, cancel) -> result dict
        self.busy = busy        # True while other (interactive) jobs are running: the queue waits its turn
        self.poll = poll
        self.items: list[dict] = []
        self.paused = False
        self._cancel: dict[str, threading.Event] = {}
        self._cond = threading.Condition()
        self._thread: threading.Thread | None = None
        self._stop = False
        self._load()

    # ---- persistence --------------------------------------------------------------------------
    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        self.paused = bool(data.get("paused", False))
        for it in data.get("items", []):
            if it.get("state") == "running":  # the app was closed mid-job: run it again from the start
                it.update(state="queued", percent=0.0, message="Restarted after the app was closed", restarted=True)
            if it.get("state") == "queued" and not it.get("project"):
                it.update(state="error", error={"message": "This queued job lost its saved project", "hint": "Queue it again"})
            self.items.append(it)

    def _save(self) -> None:  # call with the lock held
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"paused": self.paused, "items": self.items}, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    # ---- the public list ------------------------------------------------------------------------
    def snapshot(self) -> dict:
        with self._cond:
            items = [{k: v for k, v in it.items() if k not in PUBLIC_HIDDEN} for it in self.items]
            return {"items": items, "paused": self.paused, "running": any(i["state"] == "running" for i in items)}

    def _find(self, item_id: str) -> dict | None:
        return next((i for i in self.items if i["id"] == item_id), None)

    # ---- commands -------------------------------------------------------------------------------
    def add(self, kind: str, label: str, params: dict, project: dict) -> dict:
        if kind not in self.runners:
            raise KeyError(kind)
        item = {"id": uuid.uuid4().hex[:10], "kind": kind, "label": label, "params": params, "project": project,
                "state": "queued", "percent": 0.0, "message": "", "result": None, "error": None, "created": time.time()}
        with self._cond:
            self.items.append(item)
            self._save()
            self._cond.notify_all()
        return {k: v for k, v in item.items() if k not in PUBLIC_HIDDEN}

    def cancel(self, item_id: str) -> bool:
        with self._cond:
            it = self._find(item_id)
            if it is None or it["state"] in TERMINAL:
                return False
            if it["state"] == "queued":
                it.update(state="cancelled", project=None)
                self._save()
            else:
                self._cancel[item_id].set()
            self._cond.notify_all()
            return True

    def remove(self, item_id: str) -> bool:
        with self._cond:
            it = self._find(item_id)
            if it is None or it["state"] == "running":
                return False
            self.items.remove(it)
            self._save()
            return True

    def move(self, item_id: str, delta: int) -> bool:
        """Move a waiting item up (-1) or down (+1) among the waiting ones."""
        with self._cond:
            it = self._find(item_id)
            if it is None or it["state"] != "queued":
                return False
            waiting = [i for i in self.items if i["state"] == "queued"]
            k = waiting.index(it) + delta
            if not 0 <= k < len(waiting):
                return False
            other = waiting[k]
            a, b = self.items.index(it), self.items.index(other)
            self.items[a], self.items[b] = self.items[b], self.items[a]
            self._save()
            return True

    def set_paused(self, paused: bool) -> None:
        with self._cond:
            self.paused = paused
            self._save()
            self._cond.notify_all()

    def clear_finished(self) -> int:
        with self._cond:
            before = len(self.items)
            self.items = [i for i in self.items if i["state"] not in TERMINAL]
            self._save()
            return before - len(self.items)

    # ---- the worker -----------------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="vidcut-queue", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()

    def _next(self) -> dict | None:
        return next((i for i in self.items if i["state"] == "queued"), None)

    def _loop(self) -> None:
        while True:
            with self._cond:
                while not self._stop and (self.paused or self._next() is None):
                    self._cond.wait(timeout=5)
                if self._stop:
                    return
            if self.busy():  # an interactive job is rendering: wait rather than fight it for the CPU
                time.sleep(self.poll)
                continue
            with self._cond:
                it = self._next()
                if it is None or self.paused:
                    continue
                cancel = threading.Event()
                self._cancel[it["id"]] = cancel
                it.update(state="running", started=time.time(), percent=0.0, message="")
                self._save()
            self._run(it, cancel)

    def _run(self, it: dict, cancel: threading.Event) -> None:
        def progress(p, msg=""):
            with self._cond:  # not saved on every tick: a restart re-runs the item from the start anyway
                it.update(percent=float(p), message=msg)

        try:
            result = self.runners[it["kind"]](it["project"], it["params"], progress, cancel)
            outcome = {"state": "done", "percent": 1.0, "result": result}
        except Cancelled:
            outcome = {"state": "cancelled"}
        except Exception as e:  # noqa: BLE001 - shown in the queue list
            outcome = {"state": "error", "error": payload(from_exception(e))}
        with self._cond:
            it.update(outcome, finished=time.time(), project=None)  # the frozen project is no longer needed
            self._cancel.pop(it["id"], None)
            self._save()
            self._cond.notify_all()

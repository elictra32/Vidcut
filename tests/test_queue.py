import json
import os
import threading
import time

import pytest

from server.jobqueue import JobQueue


def wait_for(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class Gate:
    """A runner that blocks until released, so the tests control when each item finishes."""
    def __init__(self):
        self.started, self.release, self.order = threading.Event(), threading.Event(), []

    def run(self, project, params, progress, cancel):
        self.order.append(params["n"])
        progress(0.5, "halfway")
        self.started.set()
        while not self.release.is_set():
            if cancel.is_set():
                from core.media import Cancelled
                raise Cancelled()
            time.sleep(0.01)
        return {"n": params["n"]}


def states(q):
    return {i["params"]["n"]: i["state"] for i in q.snapshot()["items"]}


def test_items_run_one_at_a_time_in_order_and_finish(tmp_path):
    g = Gate()
    q = JobQueue(str(tmp_path), {"export": g.run}, poll=0.01)
    q.start()
    for n in (1, 2, 3):
        q.add("export", f"job {n}", {"n": n}, {"x": n})
    assert g.started.wait(5)
    assert states(q) == {1: "running", 2: "queued", 3: "queued"}
    g.release.set()
    assert wait_for(lambda: set(states(q).values()) == {"done"})
    assert g.order == [1, 2, 3]
    snap = q.snapshot()["items"]
    assert all("project" not in i for i in snap) and snap[0]["result"] == {"n": 1}
    q.stop()


def test_waiting_items_can_be_reordered_cancelled_and_removed(tmp_path):
    g = Gate()
    q = JobQueue(str(tmp_path), {"export": g.run}, poll=0.01)
    q.start()
    ids = [q.add("export", f"job {n}", {"n": n}, {})["id"] for n in (1, 2, 3, 4)]
    assert g.started.wait(5)                       # 1 is running
    assert q.move(ids[3], -1) and q.move(ids[3], -1)   # 4 jumps ahead of 3 and 2
    assert [i["params"]["n"] for i in q.snapshot()["items"]] == [1, 4, 2, 3]
    assert not q.move(ids[0], 1)                   # a running item can't be moved
    assert q.cancel(ids[1]) and states(q)[2] == "cancelled"
    assert not q.remove(ids[0])                    # running: cancel it first
    assert q.remove(ids[1]) and 2 not in states(q)
    g.release.set()
    assert wait_for(lambda: states(q) == {1: "done", 4: "done", 3: "done"})
    assert g.order == [1, 4, 3]
    assert q.clear_finished() == 3 and q.snapshot()["items"] == []
    q.stop()


def test_a_running_item_can_be_cancelled(tmp_path):
    g = Gate()
    q = JobQueue(str(tmp_path), {"export": g.run}, poll=0.01)
    q.start()
    item = q.add("export", "a", {"n": 1}, {})
    q.add("export", "b", {"n": 2}, {})
    assert g.started.wait(5)
    assert q.cancel(item["id"])
    assert wait_for(lambda: states(q)[1] == "cancelled")
    g.release.set()
    assert wait_for(lambda: states(q)[2] == "done")
    q.stop()


def test_pause_holds_back_the_next_item(tmp_path):
    g = Gate()
    q = JobQueue(str(tmp_path), {"export": g.run}, poll=0.01)
    q.set_paused(True)
    q.start()
    q.add("export", "a", {"n": 1}, {})
    time.sleep(0.3)
    assert states(q) == {1: "queued"} and not g.started.is_set()
    q.set_paused(False)
    assert g.started.wait(5)
    g.release.set()
    assert wait_for(lambda: states(q) == {1: "done"})
    q.stop()


def test_failures_are_recorded_and_the_queue_carries_on(tmp_path):
    def boom(project, params, progress, cancel):
        if params["n"] == 1:
            raise RuntimeError("disk full")
        return {"ok": True}
    q = JobQueue(str(tmp_path), {"export": boom}, poll=0.01)
    q.start()
    q.add("export", "a", {"n": 1}, {})
    q.add("export", "b", {"n": 2}, {})
    assert wait_for(lambda: states(q) == {1: "error", 2: "done"})
    assert q.snapshot()["items"][0]["error"]["message"]
    q.stop()


def test_the_queue_is_saved_and_resumes_after_a_restart(tmp_path):
    g = Gate()
    q = JobQueue(str(tmp_path), {"export": g.run}, poll=0.01)
    q.start()
    q.add("export", "a", {"n": 1}, {"proj": 1})
    q.add("export", "b", {"n": 2}, {"proj": 2})
    q.add("export", "c", {"n": 3}, {"proj": 3})
    assert g.started.wait(5)
    saved = json.loads(open(os.path.join(str(tmp_path), "queue.json"), encoding="utf-8").read())
    assert [i["state"] for i in saved["items"]] == ["running", "queued", "queued"] and saved["items"][1]["project"] == {"proj": 2}
    # "close the app" while 'a' is running: a new queue object reads the same file
    g2 = Gate()
    g2.release.set()
    q2 = JobQueue(str(tmp_path), {"export": g2.run}, poll=0.01)
    first = q2.snapshot()["items"][0]
    assert first["state"] == "queued" and first["restarted"] and "closed" in first["message"]
    q2.start()
    assert wait_for(lambda: states(q2) == {1: "done", 2: "done", 3: "done"})
    assert g2.order == [1, 2, 3]  # the interrupted item ran again, from the start
    q2.stop()
    g.release.set()
    q.stop()


def test_it_waits_while_an_interactive_job_is_busy(tmp_path):
    busy = {"v": True}
    ran = []
    q = JobQueue(str(tmp_path), {"export": lambda p, params, pr, c: ran.append(1) or {}}, busy=lambda: busy["v"], poll=0.01)
    q.start()
    q.add("export", "a", {"n": 1}, {})
    time.sleep(0.3)
    assert not ran
    busy["v"] = False
    assert wait_for(lambda: ran)
    q.stop()


def test_unknown_kind_is_refused(tmp_path):
    q = JobQueue(str(tmp_path), {})
    with pytest.raises(KeyError):
        q.add("nope", "x", {}, {})

"""Background jobs (scan, build, installs) with pollable progress."""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from typing import Callable


class Job:
    def __init__(self, kind: str, label: str, steps: list[str]):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.label = label
        self.steps = steps
        self.step = 0
        self.state = "running"          # running | done | failed
        self.error = ""
        self.log: list[str] = []
        self.result: dict = {}
        self.started = time.time()

    def advance_to(self, index: int) -> None:
        self.step = max(self.step, min(index, len(self.steps)))

    def line(self, text: str) -> None:
        self.log.append(text.rstrip())
        del self.log[:-400]

    def as_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "label": self.label, "steps": self.steps,
            "step": self.step, "state": self.state, "error": self.error,
            "log": self.log[-40:], "result": self.result,
        }


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def start(kind: str, label: str, steps: list[str], fn: Callable[[Job], dict | None]) -> Job:
    job = Job(kind, label, steps)
    with _lock:
        _jobs[job.id] = job

    def run() -> None:
        try:
            job.result = fn(job) or {}
            job.step = len(job.steps)
            job.state = "done"
        except UserFacingError as exc:
            job.error = str(exc)
            job.state = "failed"
        except Exception as exc:  # surface unexpected failures instead of hanging the UI
            job.error = "發生未預期的錯誤：%s" % exc
            job.line(traceback.format_exc())
            job.state = "failed"

    threading.Thread(target=run, name="job-" + job.id, daemon=True).start()
    return job


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def running(kind_prefix: str = "") -> list[Job]:
    return [j for j in _jobs.values() if j.state == "running" and j.kind.startswith(kind_prefix)]


class UserFacingError(Exception):
    """An error whose message is written for the person using the app."""

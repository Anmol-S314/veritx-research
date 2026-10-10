"""veritx_dse.product.jobs — the smallest reliable local job mechanism.

Rationale: docs/decisions/modules/product.md
"""
from __future__ import annotations

import logging
import json
import os
import signal
import subprocess
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from veritx_dse.application.errors import ControlPlaneError, ErrorCode
from veritx_dse.core.errors import Refusal
from veritx_dse.product.store import ProductStore, _new_id, utcnow

log = logging.getLogger("veritx.product.jobs")

TERMINAL_STATES = frozenset(
    {"COMPLETED", "REFUSED", "FAILED", "CANCELLED"})

_REFUSAL_CODES = frozenset({
    ErrorCode.INVALID_INTENT,
    ErrorCode.UNSUPPORTED_SEMANTICS,
    ErrorCode.LOWERING_UNSUPPORTED,
    ErrorCode.EVIDENCE_INVALID,
    ErrorCode.POLICY_REJECTED,
    ErrorCode.NO_FEASIBLE_DESIGN,
    ErrorCode.COMPARISON_INCOMPATIBLE,
})

JobFn = Callable[[Callable[[str], None]], tuple[str, dict[str, Any]]]


class JobManager:
    def __init__(self, store: ProductStore, *, max_workers: int = 2) -> None:
        self._store = store
        self._pool = ThreadPoolExecutor(max_workers=max_workers,
                                        thread_name_prefix="veritx-job")
        self._lock = threading.RLock()
        self._processes: dict[str, subprocess.Popen] = {}
        self._process_jobs: dict[str, str] = {}

    def shutdown(self) -> None:
        for job_id, project_id in list(self._process_jobs.items()):
            self.cancel(project_id, job_id)
        self._pool.shutdown(wait=False, cancel_futures=True)

    def recover_interrupted(self, project_id: str) -> None:
        """Mark non-terminal jobs from a previous process as FAILED."""
        for job in self._store.list_jobs(project_id):
            if job.get("state") not in TERMINAL_STATES:
                self._store.update_job(
                    project_id, job["job_id"], state="FAILED",
                    error_code=ErrorCode.INTERNAL_ERROR.value,
                    error_message="interrupted by gateway restart",
                    result=None)

    def submit_process(self, project_id: str, *, kind: str,
                       draft_hash: str, prepare: Callable[[str], tuple[list[str], Path]],
                       publish: Callable[[dict[str, Any]], dict[str, Any]],
                       timeout_s: int = 300) -> dict[str, Any]:
        """Only the parent publishes. Cancellation wins before publication."""
        with self._lock, self._store._locked():
            active = [j for j in self._store.list_jobs(project_id)
                      if j.get("kind") == kind and j.get("state") not in TERMINAL_STATES]
            if active:
                raise ControlPlaneError(ErrorCode.CONFLICT,
                    f"a {kind.lower()} job is already active for this project")
            job_id = _new_id("job")
            command, output = prepare(job_id)
            now = utcnow()
            job = {"schema_version": 1, "job_id": job_id,
                   "project_id": project_id, "kind": kind, "revision_id": None,
                   "draft_design_hash": draft_hash, "cancellable": True,
                   "state": "QUEUED", "submitted_at": now, "updated_at": now,
                   "error_code": None, "error_message": None, "result": None}
            self._store.create_job(project_id, job)
            self._process_jobs[job_id] = project_id
            self._pool.submit(self._run_process, project_id, job_id,
                              command, output, publish, timeout_s)
            return job

    def _run_process(self, project_id, job_id, command, output, publish, timeout_s):
        try:
            with self._lock:
                state = self._store.load_job(project_id, job_id)["state"]
                if state in TERMINAL_STATES or state == "CANCELLING":
                    return
                self._store.update_job(project_id, job_id, state="PREPARING")
                with (output.parent / "worker.log").open("wb") as log_file:
                    process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                        stdout=log_file, stderr=subprocess.STDOUT, start_new_session=True)
                self._processes[job_id] = process
                self._store.update_job(project_id, job_id, state="RUNNING")
            try:
                code = process.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                self._kill_group(process)
                raise ControlPlaneError(ErrorCode.EXECUTION_TIMEOUT,
                    f"job exceeded its {timeout_s}-second deadline")
            with self._lock:
                current = self._store.load_job(project_id, job_id)
                if current["state"] in TERMINAL_STATES or current["state"] == "CANCELLING":
                    return
                if not output.is_file() or output.stat().st_size > 32 * 1024 * 1024:
                    raise RuntimeError("worker output missing or exceeds 32 MiB")
                result = json.loads(output.read_text())
                if code != 0 or result.get("error"):
                    error = result.get("error") or {}
                    raise ControlPlaneError(ErrorCode(error.get("code", "INTERNAL_ERROR")),
                        error.get("message", "worker failed; inspect its local log"))
                published = publish(result)
                self._store.update_job(project_id, job_id, state="COMPLETED",
                    result=published, error_code=None, error_message=None)
        except Exception as exc:
            with self._lock:
                job = self._store.load_job(project_id, job_id)
                if job["state"] in TERMINAL_STATES or job["state"] == "CANCELLING":
                    return
                if isinstance(exc, ControlPlaneError):
                    code, message = exc.code.value, exc.message
                    state = "REFUSED" if exc.code in _REFUSAL_CODES or exc.code == ErrorCode.STALE_REVIEW else "FAILED"
                else:
                    log.exception("process job %s failed", job_id)
                    code, message, state = "INTERNAL_ERROR", "worker failed; inspect its local log", "FAILED"
                self._store.update_job(project_id, job_id, state=state,
                    error_code=code, error_message=message, result=None)
        finally:
            with self._lock:
                self._processes.pop(job_id, None)
                self._process_jobs.pop(job_id, None)

    @staticmethod
    def _kill_group(process):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait()

    def cancel(self, project_id: str, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._store.load_job(project_id, job_id)
            if not job.get("cancellable"):
                raise ControlPlaneError(ErrorCode.CONFLICT, "this job is not cancellable")
            if job["state"] in TERMINAL_STATES or job["state"] == "CANCELLING":
                return job
            self._store.update_job(project_id, job_id, state="CANCELLING")
            process = self._processes.get(job_id)
        if process is not None:
            self._kill_group(process)
        with self._lock:
            return self._store.update_job(project_id, job_id, state="CANCELLED",
                                          result=None, error_code=None, error_message=None)

    def submit(self, project_id: str, *, kind: str, revision_id: str,
               fn: JobFn) -> dict[str, Any]:
        job = {
            "schema_version": 1,
            "job_id": _new_id("job"),
            "project_id": project_id,
            "kind": kind,
            "revision_id": revision_id,
            "state": "QUEUED",
            "submitted_at": utcnow(),
            "updated_at": utcnow(),
            "error_code": None,
            "error_message": None,
            "result": None,
        }
        self._store.create_job(project_id, job)
        self._pool.submit(self._run, project_id, job["job_id"], fn)
        return job

    def _run(self, project_id: str, job_id: str, fn: JobFn) -> None:
        def progress(state: str) -> None:
            self._store.update_job(project_id, job_id, state=state)
        try:
            progress("PREPARING")
            state, result = fn(progress)
            self._store.update_job(
                project_id, job_id, state=state, result=result,
                error_code=None, error_message=None)
        except ControlPlaneError as exc:
            state = "REFUSED" if exc.code in _REFUSAL_CODES else "FAILED"
            log.info("job %s refused: %s", job_id, exc)
            self._store.update_job(
                project_id, job_id, state=state,
                error_code=exc.code.value, error_message=exc.message,
                result=None)
        except Refusal as exc:
            state = "REFUSED" if exc.code in _REFUSAL_CODES else "FAILED"
            log.info("job %s refused: %s", job_id, exc)
            self._store.update_job(
                project_id, job_id, state=state,
                error_code=exc.code, error_message=exc.message,
                result=None)
        except Exception as exc:  # noqa: BLE001 - programmer failure
            log.exception("job %s failed unexpectedly", job_id)
            self._store.update_job(
                project_id, job_id, state="FAILED",
                error_code=ErrorCode.INTERNAL_ERROR.value,
                error_message=f"{type(exc).__name__}: {exc}", result=None)


__all__ = ["JobManager", "TERMINAL_STATES"]

"""veritx_dse.product.jobs — the smallest reliable local job mechanism.

No Redis, no Celery, no broker. A persistent job record on disk plus an
in-process worker pool. The state machine is explicit:

    QUEUED -> PREPARING -> RUNNING -> FINALIZING -> COMPLETED
                                                   REFUSED
                                                   FAILED
                                                   CANCELLED

Typed control-plane refusals map to REFUSED; an unexpected programmer
failure maps to FAILED and is logged — it is never reported as an invalid
user input. Jobs left non-terminal by a gateway restart are explicitly
marked FAILED("interrupted by gateway restart") on startup; they are never
left permanently RUNNING.
"""
from __future__ import annotations

import logging
import threading
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

#: A job function returns ``(job_state, result)``. ``job_state`` is one of
#: COMPLETED / REFUSED; ``result`` is a small linkage object (run_id /
#: optimization_id), never a scientific payload.
JobFn = Callable[[Callable[[str], None]], tuple[str, dict[str, Any]]]


class JobManager:
    def __init__(self, store: ProductStore, *, max_workers: int = 2) -> None:
        self._store = store
        self._pool = ThreadPoolExecutor(max_workers=max_workers,
                                        thread_name_prefix="veritx-job")
        self._lock = threading.Lock()

    def shutdown(self) -> None:
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
            # A core Refusal (semantic refusal, never approximated silently)
            # is NOT a ControlPlaneError. Without this branch it fell through
            # to the generic handler and was reported as INTERNAL_ERROR/FALSE
            # FAILED, telling the operator something broke when in fact no
            # science was attempted.
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

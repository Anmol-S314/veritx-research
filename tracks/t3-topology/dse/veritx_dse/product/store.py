"""veritx_dse.product.store — filesystem-backed product resources.

One directory per project. All writes are atomic AND crash-durable (temp
file + fsync + rename + parent-directory fsync) and serialized by a
process lock plus an advisory inter-process ``flock``, so a crash cannot
leave a half-written resource and two gateway processes cannot allocate
the same revision id. No database is introduced: the durable form is JSON
on disk.

Durability note: the inter-process lock is advisory ``flock`` on
``<root>/.store.lock``. It is correct for a single shared filesystem; it
does not make the store a distributed database. The gateway is expected
to run one worker (the default) — the lock makes two workers safe, not
many-host deployments.

Layout::

    <root>/projects/<project_id>/
        project.json
        draft.json
        revisions/<revision_id>.json
        runs/<run_id>/run.json
        runs/<run_id>/bundle/...        (the durable RunBundle)
        jobs/<job_id>.json
        optimizations/<optimization_id>.json

The store owns identity generation and persistence only. It never derives
a scientific value.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from veritx_dse.application.errors import ControlPlaneError, ErrorCode


class ProductStoreError(ControlPlaneError):
    """A product resource is missing, corrupt or in conflict."""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class ProductStore:
    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._tls = threading.local()

    # ── locking ───────────────────────────────────────────────────────

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Reentrant (per-thread) process + inter-process exclusive lock."""
        with self._lock:
            depth = getattr(self._tls, "depth", 0)
            if depth:
                self._tls.depth = depth + 1
                try:
                    yield
                finally:
                    self._tls.depth = depth
                return
            handle = open(self.root / ".store.lock", "a+")
            fcntl.flock(handle, fcntl.LOCK_EX)
            self._tls.depth = 1
            try:
                yield
            finally:
                self._tls.depth = 0
                fcntl.flock(handle, fcntl.LOCK_UN)
                handle.close()

    # ── primitives ────────────────────────────────────────────────────

    def _fsync_dir(self, directory: Path) -> None:
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _atomic_write(self, path: Path, document: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
            # fsync the parent so the rename itself is durable.
            self._fsync_dir(path.parent)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _read(self, path: Path, what: str) -> dict[str, Any]:
        if not path.is_file():
            raise ProductStoreError(
                ErrorCode.NOT_FOUND, f"no such {what}: {path.name}",
                operation="read")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProductStoreError(
                ErrorCode.EVIDENCE_INVALID,
                f"{what} {path.name} is unreadable: {exc}",
                operation="read") from exc
        if not isinstance(document, dict):
            raise ProductStoreError(
                ErrorCode.EVIDENCE_INVALID,
                f"{what} {path.name} is not a JSON object",
                operation="read")
        return document

    # ── paths ─────────────────────────────────────────────────────────

    def project_dir(self, project_id: str) -> Path:
        if "/" in project_id or "\\" in project_id or project_id in (".", ".."):
            raise ProductStoreError(
                ErrorCode.INVALID_INTENT, f"invalid project id {project_id!r}")
        return self.root / "projects" / project_id

    def run_bundle_dir(self, project_id: str, run_id: str) -> Path:
        return self.project_dir(project_id) / "runs" / run_id / "bundle"

    # ── projects ──────────────────────────────────────────────────────

    def create_project(self, *, name: str, draft_doc: dict[str, Any],
                       workload_id: str, source: str) -> dict[str, Any]:
        with self._locked():
            project_id = _new_id("p")
            now = utcnow()
            project = {
                "schema_version": 1,
                "project_id": project_id,
                "name": name,
                "created_at": now,
                "updated_at": now,
                "active_revision_id": None,
                "revision_ids": [],
                "run_ids": [],
                "optimization_ids": [],
                "job_ids": [],
            }
            draft = {
                "schema_version": 1,
                "project_id": project_id,
                "updated_at": now,
                "workload_id": workload_id,
                "source": source,
                "request": draft_doc,
            }
            self._atomic_write(self.project_dir(project_id) / "project.json",
                               project)
            self._atomic_write(self.project_dir(project_id) / "draft.json",
                               draft)
            return project

    def list_projects(self) -> list[dict[str, Any]]:
        base = self.root / "projects"
        if not base.is_dir():
            return []
        projects = []
        for child in sorted(base.iterdir()):
            path = child / "project.json"
            if path.is_file():
                projects.append(self._read(path, "project"))
        return projects

    def load_project(self, project_id: str) -> dict[str, Any]:
        return self._read(self.project_dir(project_id) / "project.json",
                          "project")

    def save_project(self, project: dict[str, Any]) -> None:
        with self._locked():
            project["updated_at"] = utcnow()
            self._atomic_write(
                self.project_dir(project["project_id"]) / "project.json",
                project)

    def rename_project(self, project_id: str, name: str) -> dict[str, Any]:
        with self._locked():
            project = self.load_project(project_id)
            project["name"] = name
            project["updated_at"] = utcnow()
            self._atomic_write(self.project_dir(project_id) / "project.json",
                               project)
            return project

    def delete_project(self, project_id: str) -> None:
        """Remove a project and all of its resources.

        Irreversible. Refuses to touch anything outside the projects root.
        Jobs still running against the project are in-process; the caller
        (gateway) is responsible for not deleting a project mid-job.
        """
        with self._locked():
            target = self.project_dir(project_id)
            base = (self.root / "projects").resolve()
            resolved = target.resolve()
            if base != resolved and base not in resolved.parents:
                raise ProductStoreError(
                    ErrorCode.INVALID_INTENT,
                    f"refusing to delete outside the projects root: {target}")
            if not (target / "project.json").is_file():
                raise ProductStoreError(
                    ErrorCode.NOT_FOUND, f"no such project: {project_id}",
                    operation="delete_project", resource_id=project_id)
            shutil.rmtree(target)

    # ── draft ─────────────────────────────────────────────────────────

    def load_draft(self, project_id: str) -> dict[str, Any]:
        return self._read(self.project_dir(project_id) / "draft.json", "draft")

    def save_draft(self, project_id: str, request_doc: dict[str, Any],
                   design_hash: str | None = None) -> dict[str, Any]:
        with self._locked():
            draft = self.load_draft(project_id)
            draft["request"] = request_doc
            if design_hash is not None:
                draft["design_hash"] = design_hash
            draft["updated_at"] = utcnow()
            self._atomic_write(
                self.project_dir(project_id) / "draft.json", draft)
            return draft

    def put_draft(self, project_id: str,
                  draft: dict[str, Any]) -> dict[str, Any]:
        """Replace the whole draft record (workload identity + request)."""
        with self._locked():
            draft = dict(draft)
            draft["project_id"] = project_id
            draft["updated_at"] = utcnow()
            self._atomic_write(
                self.project_dir(project_id) / "draft.json", draft)
            return draft

    # ── revisions ─────────────────────────────────────────────────────

    def allocate_revision(self, project_id: str) -> int:
        """Allocate the next project-scoped revision sequence atomically.

        The sequence lives on the project record and is incremented under
        the exclusive lock, so two concurrent compiles can never choose
        the same revision id. The caller builds ``<project>-r<NN>`` from
        the returned sequence and then calls :meth:`create_revision`.
        """
        with self._locked():
            project = self.load_project(project_id)
            sequence = int(project.get("revision_seq", 0)) + 1
            project["revision_seq"] = sequence
            self.save_project(project)
            return sequence

    def create_revision(self, project_id: str, revision: dict[str, Any]) -> dict[str, Any]:
        with self._locked():
            path = self.project_dir(project_id) / "revisions" / (
                revision["revision_id"] + ".json")
            self._atomic_write(path, revision)
            project = self.load_project(project_id)
            project["revision_ids"].append(revision["revision_id"])
            project["active_revision_id"] = revision["revision_id"]
            self.save_project(project)
            return revision

    def load_revision(self, project_id: str, revision_id: str) -> dict[str, Any]:
        path = self.project_dir(project_id) / "revisions" / (
            revision_id + ".json")
        return self._read(path, "revision")

    def list_revisions(self, project_id: str) -> list[dict[str, Any]]:
        project = self.load_project(project_id)
        return [self.load_revision(project_id, rid)
                for rid in project.get("revision_ids", [])]

    def find_revision_project(self, revision_id: str) -> str | None:
        base = self.root / "projects"
        if not base.is_dir():
            return None
        for child in sorted(base.iterdir()):
            if (child / "revisions" / f"{revision_id}.json").is_file():
                return child.name
        return None

    def load_revision_global(self, revision_id: str) -> tuple[str, dict[str, Any]]:
        pid = self.find_revision_project(revision_id)
        if pid is None:
            raise ProductStoreError(
                ErrorCode.NOT_FOUND, f"no such revision: {revision_id}",
                operation="load_revision", resource_id=revision_id)
        return pid, self.load_revision(pid, revision_id)

    # ── runs ──────────────────────────────────────────────────────────

    def create_run(self, project_id: str, run: dict[str, Any]) -> dict[str, Any]:
        with self._locked():
            path = self.project_dir(project_id) / "runs" / run["run_id"] / "run.json"
            self._atomic_write(path, run)
            project = self.load_project(project_id)
            if run["run_id"] not in project["run_ids"]:
                project["run_ids"].append(run["run_id"])
            self.save_project(project)
            return run

    def load_run(self, project_id: str, run_id: str) -> dict[str, Any]:
        path = self.project_dir(project_id) / "runs" / run_id / "run.json"
        return self._read(path, "run")

    def list_runs(self, project_id: str | None = None,
                  revision_id: str | None = None) -> list[dict[str, Any]]:
        projects = ([self.load_project(project_id)] if project_id is not None
                    else self.list_projects())
        runs: list[dict[str, Any]] = []
        for project in projects:
            pid = project["project_id"]
            for run_id in project.get("run_ids", []):
                path = self.project_dir(pid) / "runs" / run_id / "run.json"
                if path.is_file():
                    runs.append(self._read(path, "run"))
        if revision_id is not None:
            runs = [r for r in runs if r.get("revision_id") == revision_id]
        return runs

    def find_run_project(self, run_id: str) -> str | None:
        base = self.root / "projects"
        if not base.is_dir():
            return None
        for child in sorted(base.iterdir()):
            if (child / "runs" / run_id / "run.json").is_file():
                return child.name
        return None

    # ── jobs ──────────────────────────────────────────────────────────

    def create_job(self, project_id: str, job: dict[str, Any]) -> dict[str, Any]:
        with self._locked():
            path = self.project_dir(project_id) / "jobs" / (job["job_id"] + ".json")
            self._atomic_write(path, job)
            project = self.load_project(project_id)
            project["job_ids"].append(job["job_id"])
            self.save_project(project)
            return job

    def load_job(self, project_id: str, job_id: str) -> dict[str, Any]:
        return self._read(self.project_dir(project_id) / "jobs" / (job_id + ".json"),
                          "job")

    def update_job(self, project_id: str, job_id: str,
                   **fields: Any) -> dict[str, Any]:
        with self._locked():
            job = self.load_job(project_id, job_id)
            job.update(fields)
            job["updated_at"] = utcnow()
            self._atomic_write(
                self.project_dir(project_id) / "jobs" / (job_id + ".json"), job)
            return job

    def find_job_project(self, job_id: str) -> str | None:
        base = self.root / "projects"
        if not base.is_dir():
            return None
        for child in sorted(base.iterdir()):
            if (child / "jobs" / f"{job_id}.json").is_file():
                return child.name
        return None

    def list_jobs(self, project_id: str | None = None) -> list[dict[str, Any]]:
        projects = ([self.load_project(project_id)] if project_id is not None
                    else self.list_projects())
        jobs = []
        for project in projects:
            pid = project["project_id"]
            for job_id in project.get("job_ids", []):
                path = self.project_dir(pid) / "jobs" / (job_id + ".json")
                if path.is_file():
                    jobs.append(self._read(path, "job"))
        return jobs

    # ── optimizations ─────────────────────────────────────────────────

    def create_optimization(self, project_id: str,
                            optimization: dict[str, Any]) -> dict[str, Any]:
        with self._locked():
            oid = optimization["optimization_id"]
            self._atomic_write(
                self.project_dir(project_id) / "optimizations" / (oid + ".json"),
                optimization)
            project = self.load_project(project_id)
            project["optimization_ids"].append(oid)
            self.save_project(project)
            return optimization

    def load_optimization(self, project_id: str, oid: str) -> dict[str, Any]:
        return self._read(
            self.project_dir(project_id) / "optimizations" / (oid + ".json"),
            "optimization")

    def find_optimization_project(self, oid: str) -> str | None:
        base = self.root / "projects"
        if not base.is_dir():
            return None
        for child in sorted(base.iterdir()):
            if (child / "optimizations" / f"{oid}.json").is_file():
                return child.name
        return None


__all__ = ["ProductStore", "ProductStoreError", "utcnow"]

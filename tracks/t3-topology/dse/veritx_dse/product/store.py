"""veritx_dse.product.store — filesystem-backed product resources.

Rationale: docs/decisions/modules/product.md
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

    def project_dir(self, project_id: str) -> Path:
        if "/" in project_id or "\\" in project_id or project_id in (".", ".."):
            raise ProductStoreError(
                ErrorCode.INVALID_INTENT, f"invalid project id {project_id!r}")
        return self.root / "projects" / project_id

    def run_bundle_dir(self, project_id: str, run_id: str) -> Path:
        return self.project_dir(project_id) / "runs" / run_id / "bundle"

    def serving_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "serving"

    def create_serving(self, project_id: str,
                       experiment: dict[str, Any]) -> dict[str, Any]:
        with self._locked():
            project = self.load_project(project_id)
            serving_id = experiment["serving_id"]
            project.setdefault("serving_ids", []).append(serving_id)
            project["updated_at"] = utcnow()
            self._atomic_write(
                self.serving_dir(project_id) / f"{serving_id}.json",
                experiment)
            self._atomic_write(
                self.project_dir(project_id) / "project.json", project)
            return experiment

    def save_serving_binding(self, project_id: str,
                             binding: dict[str, Any]) -> dict[str, Any]:
        """Persist the explicit serving binding for a project.

        A catalog count is NOT readiness: an experiment is runnable only
        when bound. The binding supplies serving inputs (cluster config,
        trace, request count, overrides); the design still comes from the
        revision being evaluated.
        """
        with self._locked():
            self.load_project(project_id)
            self._atomic_write(
                self.project_dir(project_id) / "serving-binding.json",
                binding)
            return binding

    def load_serving_binding(self, project_id: str) -> dict[str, Any] | None:
        path = self.project_dir(project_id) / "serving-binding.json"
        if not path.is_file():
            return None
        import json as _json
        return _json.loads(path.read_text(encoding="utf-8"))

    def clear_serving_binding(self, project_id: str) -> None:
        with self._locked():
            self.load_project(project_id)
            path = self.project_dir(project_id) / "serving-binding.json"
            if path.is_file():
                path.unlink()

    def update_serving(self, project_id: str, serving_id: str,
                       **fields: Any) -> None:
        with self._locked():
            self.load_project(project_id)
            path = self.serving_dir(project_id) / f"{serving_id}.json"
            if not path.is_file():
                raise ProductStoreError(
                    ErrorCode.NOT_FOUND,
                    f"no such serving experiment: {serving_id}")
            doc = json.loads(path.read_text(encoding="utf-8"))
            doc.update(fields)
            self._atomic_write(path, doc)

    def load_serving(self, project_id: str,
                     serving_id: str) -> dict[str, Any]:
        path = self.serving_dir(project_id) / f"{serving_id}.json"
        if not path.is_file():
            raise ProductStoreError(
                ErrorCode.NOT_FOUND,
                f"no such serving experiment: {serving_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_serving(self, project_id: str) -> list[dict[str, Any]]:
        directory = self.serving_dir(project_id)
        if not directory.is_dir():
            return []
        out = []
        for path in sorted(directory.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            evidence = doc.get("evidence") or {}
            out.append({
                "serving_id": doc.get("serving_id"),
                "state": doc.get("state"),
                "workload_id": doc.get("workload_id"),
                "created_at": doc.get("created_at"),
                "request_count": evidence.get("request_count"),
                "rounds": evidence.get("rounds"),
                "reusable": evidence.get("reusable"),
            })
        return out

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
                "latest_attempt_revision_id": None,
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

    def create_revision(self, project_id: str, revision: dict[str, Any],
                          *, promote: bool = False) -> dict[str, Any]:
        """Record a compile attempt and optionally promote it to active.

Rationale: docs/decisions/modules/product.md
        """
        with self._locked():
            path = self.project_dir(project_id) / "revisions" / (
                revision["revision_id"] + ".json")
            self._atomic_write(path, revision)
            project = self.load_project(project_id)
            project["revision_ids"].append(revision["revision_id"])
            project["latest_attempt_revision_id"] = revision["revision_id"]
            if promote:
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

    def find_serving_project(self, serving_id: str) -> str | None:
        base = self.root / "projects"
        if not base.is_dir():
            return None
        for child in sorted(base.iterdir()):
            if (child / "serving" / f"{serving_id}.json").is_file():
                return child.name
        return None

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

    def create_synthesis(self, project_id: str,
                         synthesis: dict[str, Any]) -> dict[str, Any]:
        with self._locked():
            sid = synthesis["synthesis_id"]
            self._atomic_write(
                self.project_dir(project_id) / "syntheses" / (sid + ".json"),
                synthesis)
            try:
                project = self.load_project(project_id)
                ids = project.get("synthesis_ids") or []
                if sid not in ids:
                    project["synthesis_ids"] = [*ids, sid]
                    self.save_project(project)
            except Exception:
                pass
            return synthesis

    def load_synthesis(self, project_id: str, sid: str) -> dict[str, Any]:
        return self._read(
            self.project_dir(project_id) / "syntheses" / (sid + ".json"),
            "synthesis")

    def find_synthesis_project(self, sid: str) -> str | None:
        base = self.root / "projects"
        if not base.is_dir():
            return None
        for child in sorted(base.iterdir()):
            if (child / "syntheses" / f"{sid}.json").is_file():
                return child.name
        return None

    def list_syntheses(self, project_id: str) -> list[dict[str, Any]]:
        directory = self.project_dir(project_id) / "syntheses"
        if not directory.is_dir():
            return []
        out = []
        for child in sorted(directory.glob("*.json")):
            try:
                out.append(self._read(child, "synthesis"))
            except Exception:
                continue
        return out

    def _candidates_dir(self) -> Path:
        directory = self.root / "candidates"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def create_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        with self._locked():
            cid = candidate["candidate_id"]
            self._atomic_write(
                self._candidates_dir() / (cid + ".json"), candidate)
            return candidate

    def load_candidate(self, candidate_id: str) -> dict[str, Any]:
        return self._read(
            self._candidates_dir() / (candidate_id + ".json"),
            "candidate")

    def update_candidate(self, candidate_id: str,
                         **fields: Any) -> dict[str, Any]:
        with self._locked():
            record = self.load_candidate(candidate_id)
            record.update(fields)
            record["updated_at"] = utcnow()
            self._atomic_write(
                self._candidates_dir() / (candidate_id + ".json"),
                record)
            return record

    def list_candidates(self) -> list[dict[str, Any]]:
        directory = self.root / "candidates"
        if not directory.is_dir():
            return []
        out = []
        for child in sorted(directory.glob("*.json")):
            try:
                out.append(self._read(child, "candidate"))
            except Exception:
                continue
        return out

__all__ = ["ProductStore", "ProductStoreError", "utcnow"]

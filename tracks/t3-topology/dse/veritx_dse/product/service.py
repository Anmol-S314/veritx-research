"""veritx_dse.product.service — the product state machine over canonical views.

One owner per concept:

    ProjectView      linkage only (no scientific fields)
    RevisionView     envelope around DesignView + CompilationView
    RunView          envelope around EvaluationView + RequirementReport
    JobView          linkage only
    OptimizationView envelope around OptimizationStudyView

The service parses product input, loads resources, invokes the canonical
application services and projects their views. It derives no route, counts
no packet, decides no Pareto membership and invents no qualification.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from veritx_dse.application.errors import ControlPlaneError, ErrorCode, intent_error
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.product_evaluator import evaluate_product
from veritx_dse.application.views import (
    compilation_view, design_view, topology_view,
)
from veritx_dse.core.paths import REPO
from veritx_dse.core.run_bundle import (
    RunBundleError, finalize_run_bundle, verify_run_bundle,
)
from veritx_dse.core.runs import new_run_id
from veritx_dse.product.jobs import TERMINAL_STATES, JobManager
from veritx_dse.product.store import ProductStore, _new_id, utcnow

#: v3 workload templates shipped with the product. The catalog exposes
#: exactly these canonical request documents; it authors no workload.
_WORKLOAD_TEMPLATES: tuple[tuple[str, str, str, str], ...] = (
    (
        "llama-dense-8b-64tiles",
        "tracks/t3-topology/examples/llama_dense_64tiles-v3.json",
        "Llama Dense 8B · 64 tiles",
        "dense transformer, TP8 collective over a 64-tile mesh",
    ),
    (
        "dense-1b-16tiles",
        "tracks/t3-topology/examples/dense_1b_16tiles-v3.json",
        "Dense 1B · 16 tiles",
        "decode-heavy dense transformer, TP4 allreduce over a 16-tile mesh",
    ),
    (
        "dense-4b-32tiles-conc4",
        "tracks/t3-topology/examples/dense_4b_32tiles_conc4-v3.json",
        "Dense 4B · 32 tiles · concentrated",
        "prefill-heavy dense transformer, DP allgather over a concentrated "
        "mesh (4 tiles per router)",
    ),
    (
        "moe-8x7b-64tiles",
        "tracks/t3-topology/examples/moe_8x7b_64tiles-v3.json",
        "MoE 8×7B · 64 tiles",
        "mixture-of-experts serving, TP allreduce + EP alltoall over a "
        "64-tile mesh",
    ),
)

_RUN_STATUS = {
    "EVALUATED": "EVALUATED",
    "BACKEND_UNAVAILABLE": "BACKEND_UNAVAILABLE",
    "UNSUPPORTED": "UNSUPPORTED",
    "FAILED": "FAILED",
    "INVALID": "INVALID",
}


class ProductServiceError(ControlPlaneError):
    """A product resource or product operation failed."""


class BackendUnavailable(ControlPlaneError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.EXECUTION_FAILED, message,
                         operation="backend")


@dataclass(frozen=True)
class ProductConfig:
    projects_root: Path
    booksim_bin: Path | None = None
    #: Exact network clock (Hz). Must be an int/Fraction: the evaluator
    #: refuses a float as a wall-time authority.
    network_clock_hz: int = 1_000_000_000
    timeout_s: int = 600
    repo_root: Path = REPO


#: Computed identity fields are engine-owned. A client may round-trip
#: them, but they are dropped before parsing so a user edit never has to
#: recompute a hash the engine owns (mirrors derive_compile_request).
_COMPUTED_IDENTITY_FIELDS = ("design_hash", "guardrail_hash")


def parse_request_doc(document: Any):
    """Parse a canonical product request document (v2 or v3)."""
    from veritx_dse.model.compile_model import CompileRequest, CompileRequestV3
    if not isinstance(document, dict):
        raise intent_error("request must be a JSON object")
    doc = {k: v for k, v in document.items()
           if k not in _COMPUTED_IDENTITY_FIELDS}
    schema_version = doc.get("schema_version")
    try:
        if schema_version == 3:
            return CompileRequestV3.from_dict(doc)
        if schema_version == 2:
            return CompileRequest.from_dict(doc)
    except ValueError as exc:
        raise intent_error(f"request document is invalid: {exc}") from exc
    raise intent_error(
        f"unsupported request schema_version {schema_version!r} "
        f"(expected 2 or 3)")


def canonical_request_doc(request: Any) -> dict[str, Any]:
    doc = request.to_dict()
    for field in _COMPUTED_IDENTITY_FIELDS:
        doc.pop(field, None)
    return doc


def _view_hash(value: str) -> str:
    """Self-describing identity, matching DesignView/CompilationView."""
    return value if value.startswith("sha256:") else "sha256:" + value


class ProductService:
    def __init__(self, config: ProductConfig,
                 store: ProductStore | None = None) -> None:
        self.config = config
        self.store = store or ProductStore(config.projects_root)
        self.jobs = JobManager(self.store)
        for project in self.store.list_projects():
            self.jobs.recover_interrupted(project["project_id"])

    # ── catalog ───────────────────────────────────────────────────────

    def workload_catalog(self) -> dict[str, Any]:
        workloads = []
        for workload_id, rel, display_name, description in _WORKLOAD_TEMPLATES:
            path = self.config.repo_root / rel
            if not path.is_file():
                continue
            document = json.loads(path.read_text(encoding="utf-8"))
            request = parse_request_doc(document)
            wl = request.workload
            entry: dict[str, Any] = {
                "workload_id": workload_id,
                "display_name": display_name,
                "description": description,
                "source": rel,
                "content_digest": request.design_hash(),
                "model_family": getattr(wl.model_family, "value",
                                        wl.model_family),
                "model_name": getattr(wl, "model_name", None),
                "serving_mode": getattr(wl.serving_mode, "value",
                                        wl.serving_mode),
                "parallelism": {"tp": wl.tp, "pp": wl.pp,
                                "ep": wl.ep, "dp": wl.dp},
                "collectives": [self._collective_view(c)
                                for c in getattr(wl, "collectives", ())],
                "agents": [{"kind": getattr(a.kind, "value", a.kind),
                            "count": a.count} for a in request.agents],
                "noc": self._noc_view(request),
                "request": canonical_request_doc(request),
            }
            workloads.append(entry)
        return {"contract_version": 1, "workloads": workloads}

    def fabric_presets(self) -> dict[str, Any]:
        from veritx_dse.application.compile_intent import (
            get_preset, preset_names,
        )
        presets = []
        for name in preset_names():
            preset = get_preset(name)
            presets.append({
                "preset_id": preset.name,
                "name": preset.name,
                "description": preset.description,
            })
        return {"contract_version": 1, "presets": presets}

    @staticmethod
    def _collective_view(collective: Any) -> dict[str, Any]:
        return {
            "kind": getattr(collective.kind, "value", collective.kind),
            "dimension": getattr(collective.dimension, "value",
                                 collective.dimension),
            "payload_bytes": collective.payload_bytes,
            "traffic_class": getattr(collective, "traffic_class", None),
        }

    @staticmethod
    def _noc_view(request: Any) -> dict[str, Any]:
        noc = request.noc_config
        return {
            "topology_family": getattr(noc.topology_family, "value",
                                       noc.topology_family),
            "radix": noc.radix,
            "concentration": noc.concentration,
            "link_width": noc.link_width,
            "rcu_enabled": noc.rcu_enabled,
            "arbitration": noc.arbitration,
        }

    # ── projects + draft ──────────────────────────────────────────────

    def create_project(self, *, name: str,
                       workload_id: str | None = None) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip():
            raise intent_error("project name must be a non-empty string")
        catalog = self.workload_catalog()["workloads"]
        if not catalog:
            raise ProductServiceError(
                ErrorCode.NOT_FOUND,
                "no workload templates are available on this tree")
        chosen = None
        if workload_id is not None:
            chosen = next((w for w in catalog
                           if w["workload_id"] == workload_id), None)
            if chosen is None:
                raise intent_error(
                    f"unknown workload {workload_id!r}; known: "
                    f"{[w['workload_id'] for w in catalog]}")
        chosen = chosen or catalog[0]
        project = self.store.create_project(
            name=name.strip(), draft_doc=chosen["request"],
            workload_id=chosen["workload_id"], source=chosen["source"])
        request = parse_request_doc(chosen["request"])
        self.store.save_draft(project["project_id"], chosen["request"],
                              design_hash=_view_hash(request.design_hash()))
        return self.project_view(project["project_id"])

    @staticmethod
    def _revision_promotable(revision: dict[str, Any]) -> bool:
        """Only a COMPILED revision with a PASS certificate may go active.

        A refused attempt (INVALID/UNSUPPORTED, or a FAIL certificate) is
        recorded as the latest attempt but must never displace the last
        usable revision.
        """
        compilation = revision.get("compilation") or {}
        certificate = revision.get("certificate") or {}
        return (compilation.get("status") == "COMPILED"
                and certificate.get("overall") == "PASS")

    def _ensure_revision_pointers(self, project_id: str) -> dict[str, Any]:
        """Backfill and repair the active/latest revision pointers.

        Projects persisted before the split carry only
        ``active_revision_id``: the latest revision id becomes the latest
        attempt, and a non-promotable active revision steps back to the
        newest promotable one (or None) so a refused attempt can never
        masquerade as the certified fabric. Persists only when a pointer
        actually changes.
        """
        project = self.store.load_project(project_id)
        revision_ids = project.get("revision_ids", [])
        changed = False
        if (project.get("latest_attempt_revision_id") is None
                and revision_ids):
            project["latest_attempt_revision_id"] = revision_ids[-1]
            changed = True
        active_id = project.get("active_revision_id")
        if active_id is not None:
            try:
                active = self.store.load_revision(project_id, active_id)
            except Exception:
                active = None
            if active is None or not self._revision_promotable(active):
                fallback = None
                for rid in reversed(revision_ids):
                    if rid == active_id:
                        continue
                    try:
                        candidate = self.store.load_revision(
                            project_id, rid)
                    except Exception:
                        continue
                    if self._revision_promotable(candidate):
                        fallback = rid
                        break
                project["active_revision_id"] = fallback
                changed = True
        if changed:
            self.store.save_project(project)
        return project

    def project_view(self, project_id: str) -> dict[str, Any]:
        project = self._ensure_revision_pointers(project_id)
        draft = self.store.load_draft(project_id)
        revisions = self.store.list_revisions(project_id)
        active_id = project.get("active_revision_id")
        active = next((r for r in revisions
                       if r["revision_id"] == active_id), None)
        latest_id = project.get("latest_attempt_revision_id")
        latest = next((r for r in revisions
                       if r["revision_id"] == latest_id), None)
        runs = self.store.list_runs(project_id)
        jobs = self.store.list_jobs(project_id)
        optimizations = [self.store.load_optimization(project_id, oid)
                         for oid in project.get("optimization_ids", [])]
        dirty = active is None or (
            draft.get("design_hash") != active.get("design_hash"))
        flow = self._flow(active, dirty, runs, jobs, latest,
                          draft.get("design_hash"))
        latest_active_run = next(
            (r for r in reversed(runs)
             if r.get("revision_id") == active_id), None)
        return {
            "contract_version": 1,
            "project": {
                "project_id": project["project_id"],
                "name": project["name"],
                "created_at": project["created_at"],
                "updated_at": project["updated_at"],
            },
            "active_revision_id": active_id,
            "active_revision": (None if active is None
                                else self.revision_view(active)),
            "latest_attempt_revision_id": latest_id,
            "latest_attempt": (None if latest is None
                               else self._revision_summary(latest)),
            "latest_active_run": (None if latest_active_run is None
                                  else self._run_summary(latest_active_run)),
            "draft": {
                "dirty": dirty,
                "based_on_revision_id": active_id,
                "workload_id": draft.get("workload_id"),
                "source": draft.get("source"),
                "design_hash": draft.get("design_hash"),
                "updated_at": draft.get("updated_at"),
            },
            "revisions": [self._revision_summary(r) for r in revisions],
            "runs": [self._run_summary(r) for r in runs],
            "optimizations": [
                {"optimization_id": o["optimization_id"],
                 "base_revision_id": o["base_revision_id"],
                 "created_at": o["created_at"],
                 "candidate_count": len(o["study"].get("candidates", [])),
                 "pareto_count": len(o["study"].get("pareto_ids", [])),
                 "selected_candidate_id":
                     o["study"].get("selected_candidate_id")}
                for o in optimizations],
            "flow": flow,
        }

    def list_projects(self) -> dict[str, Any]:
        return {"contract_version": 1,
                "projects": [self.project_view(p["project_id"])
                             for p in self.store.list_projects()]}

    def rename_project(self, project_id: str, name: str) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip():
            raise intent_error("project name must be a non-empty string")
        self.store.load_project(project_id)
        project = self.store.rename_project(project_id, name.strip())
        return self.project_view(project["project_id"])

    def delete_project(self, project_id: str) -> dict[str, Any]:
        self.store.load_project(project_id)
        active = [j for j in self.store.list_jobs(project_id)
                  if j.get("state") not in TERMINAL_STATES]
        if active:
            raise ProductServiceError(
                ErrorCode.CONFLICT,
                f"project {project_id} has {len(active)} job(s) in progress; "
                "wait for them to finish before deleting",
                operation="delete_project", resource_id=project_id)
        self.store.delete_project(project_id)
        return {"contract_version": 1, "deleted": True,
                "project_id": project_id}

    def draft_view(self, project_id: str) -> dict[str, Any]:
        project = self._ensure_revision_pointers(project_id)
        draft = self.store.load_draft(project_id)
        active_id = project.get("active_revision_id")
        active = None
        if active_id is not None:
            active = self.store.load_revision(project_id, active_id)
        dirty = active is None or (
            draft.get("design_hash") != active.get("design_hash"))
        return {
            "contract_version": 1,
            "project_id": project_id,
            "workload_id": draft.get("workload_id"),
            "source": draft.get("source"),
            "updated_at": draft.get("updated_at"),
            "design_hash": draft.get("design_hash"),
            "dirty": dirty,
            "active_revision_id": active_id,
            "latest_attempt_revision_id":
                project.get("latest_attempt_revision_id"),
            "request": draft.get("request"),
        }

    def put_draft(self, project_id: str, request_doc: Any) -> dict[str, Any]:
        request = parse_request_doc(request_doc)
        self.store.save_draft(project_id, canonical_request_doc(request),
                              design_hash=_view_hash(request.design_hash()))
        return self.draft_view(project_id)

    def select_workload(self, project_id: str,
                        workload_id: str) -> dict[str, Any]:
        """Make a catalog workload the project's draft (a real user action).

        The draft request and its workload identity/source move together;
        the previous compiled revision is untouched, so the draft becomes
        dirty until recompiled.
        """
        self.store.load_project(project_id)
        catalog = self.workload_catalog()["workloads"]
        entry = next((w for w in catalog if w["workload_id"] == workload_id),
                     None)
        if entry is None:
            raise intent_error(
                f"unknown workload {workload_id!r}; known: "
                f"{[w['workload_id'] for w in catalog]}")
        request = parse_request_doc(entry["request"])
        draft = self.store.load_draft(project_id)
        draft["workload_id"] = entry["workload_id"]
        draft["source"] = entry["source"]
        draft["request"] = canonical_request_doc(request)
        draft["design_hash"] = _view_hash(request.design_hash())
        self.store.put_draft(project_id, draft)
        return self.draft_view(project_id)

    # ── compile ───────────────────────────────────────────────────────

    def compile_draft(self, project_id: str) -> dict[str, Any]:
        self._ensure_revision_pointers(project_id)  # 404 if unknown
        draft = self.store.load_draft(project_id)
        request = parse_request_doc(draft.get("request"))
        canonical_doc = canonical_request_doc(request)
        compilation = FabricCompiler().compile(request)
        design = design_view(
            request, compilation if compilation.status == "COMPILED" else None)
        comp_view = compilation_view(compilation)
        certificate = None
        if compilation.certificate is not None:
            certificate = {
                "certificate_id": compilation.certificate.certificate_id(),
                "overall": compilation.certificate.overall,
                "obligations": [o.to_dict()
                                for o in compilation.certificate.obligations],
            }
        sequence = self.store.allocate_revision(project_id)
        revision_id = f"{project_id}-r{sequence:02d}"
        revision = {
            "schema_version": 1,
            "revision_id": revision_id,
            "display_name": f"r{sequence:02d}",
            "project_id": project_id,
            "created_at": utcnow(),
            "design_hash": _view_hash(request.design_hash()),
            "request": canonical_doc,
            "design": design,
            "compilation": comp_view,
            "certificate": certificate,
        }
        # Materialized graph captured at certification time: the shape
        # Studio draws is frozen with the revision, never re-derived later
        # (re-derivation would let the drawn graph drift from the proof).
        materialized = topology_view(compilation, revision_id=revision_id)
        if materialized is not None:
            revision["topology"] = materialized
        self.store.create_revision(
            project_id, revision,
            promote=self._revision_promotable(revision))
        return self.revision_view(revision)

    # ── revisions ─────────────────────────────────────────────────────

    def revision_view(self, revision: dict[str, Any]) -> dict[str, Any]:
        return {
            "contract_version": 1,
            "revision_id": revision["revision_id"],
            "display_name": revision["display_name"],
            "project_id": revision["project_id"],
            "created_at": revision["created_at"],
            "design_hash": revision["design_hash"],
            "design": revision["design"],
            "compilation": revision["compilation"],
            "certificate": revision["certificate"],
        }

    def get_revision(self, revision_id: str) -> dict[str, Any]:
        _pid, revision = self.store.load_revision_global(revision_id)
        return self.revision_view(revision)

    def get_revision_topology(self, revision_id: str) -> dict[str, Any]:
        """The materialized fabric graph a revision was certified against.

        Revisions persisted before this projection existed re-derive it
        from their own immutable request and are checked against the
        topology_hash the certificate already recorded — a mismatch is an
        EVIDENCE_INVALID, never a silently redrawn fabric.
        """
        _pid, revision = self.store.load_revision_global(revision_id)
        view = revision.get("topology")
        if view is None:
            compilation = revision.get("compilation") or {}
            if compilation.get("status") != "COMPILED":
                raise ProductServiceError(
                    ErrorCode.CONFLICT,
                    "this revision did not compile, so it has no "
                    "materialized topology",
                    operation="get_revision_topology",
                    resource_id=revision_id)
            rederived = topology_view(
                FabricCompiler().compile(
                    parse_request_doc(revision["request"])),
                revision_id=revision_id)
            expected = (compilation.get("artifact_hashes") or {}).get(
                "topology_hash")
            if rederived is None or (
                    expected is not None
                    and rederived["topology_hash"].split(":", 1)[-1]
                    != str(expected).split(":", 1)[-1]):
                raise ProductServiceError(
                    ErrorCode.EVIDENCE_INVALID,
                    "re-derived topology does not match the recorded "
                    "topology_hash for this revision",
                    operation="get_revision_topology",
                    resource_id=revision_id)
            view = rederived
        return view

    @staticmethod
    def _revision_summary(revision: dict[str, Any]) -> dict[str, Any]:
        compilation = revision.get("compilation") or {}
        certificate = revision.get("certificate") or {}
        return {
            "revision_id": revision["revision_id"],
            "display_name": revision["display_name"],
            "created_at": revision["created_at"],
            "design_hash": revision["design_hash"],
            "compilation_status": compilation.get("status"),
            "certificate_overall": certificate.get("overall"),
            "error": compilation.get("error"),
        }

    # ── jobs ──────────────────────────────────────────────────────────

    def job_view(self, job: dict[str, Any]) -> dict[str, Any]:
        return {
            "contract_version": 1,
            "job_id": job["job_id"],
            "project_id": job["project_id"],
            "kind": job["kind"],
            "revision_id": job["revision_id"],
            "state": job["state"],
            "submitted_at": job["submitted_at"],
            "updated_at": job["updated_at"],
            "error_code": job.get("error_code"),
            "error_message": job.get("error_message"),
            "result": job.get("result"),
        }

    def get_job(self, job_id: str) -> dict[str, Any]:
        pid = self.store.find_job_project(job_id)
        if pid is None:
            raise ProductServiceError(
                ErrorCode.NOT_FOUND, f"no such job: {job_id}",
                operation="get_job", resource_id=job_id)
        return self.job_view(self.store.load_job(pid, job_id))

    # ── evaluate ──────────────────────────────────────────────────────

    def _require_backend(self) -> Path:
        binary = self.config.booksim_bin
        if binary is None or not Path(binary).is_file():
            raise BackendUnavailable(
                "no qualified backend configured (set VERITX_BOOKSIM_BIN)")
        return Path(binary).resolve()

    def submit_evaluation(self, revision_id: str) -> dict[str, Any]:
        pid, revision = self.store.load_revision_global(revision_id)
        # A run must execute certified semantics: refused attempts
        # (INVALID/UNSUPPORTED) and FAIL certificates can never be
        # evaluated, so the UI cannot accidentally run the latest attempt
        # when it is not the usable revision.
        if not self._revision_promotable(revision):
            compilation = revision.get("compilation") or {}
            raise ProductServiceError(
                ErrorCode.CONFLICT,
                f"revision {revision_id} is not evaluable "
                f"(compilation={compilation.get('status')}, "
                "certificate="
                f"{(revision.get('certificate') or {}).get('overall')}); "
                f"reason: {compilation.get('error') or 'not certified'}",
                operation="submit_evaluation", resource_id=revision_id)
        binary = self._require_backend()
        job = self.jobs.submit(
            pid, kind="EVALUATION", revision_id=revision_id,
            fn=lambda progress: self._run_evaluation(
                pid, revision, binary, progress))
        return self.job_view(job)

    def _check_compilation_parity(self, revision: dict[str, Any],
                                    request: Any) -> None:
        """Refuse when a recompiled request drifts from the stored revision.

        A Run must execute exactly the immutable compilation the revision
        records — not a re-derived one. Recompiling the stored request and
        demanding exact identity over every recorded artifact hash turns
        compiler drift (or a mutated request) into a refused job instead
        of a silently re-derived execution.
        """
        recorded = ((revision.get("compilation") or {})
                    .get("artifact_hashes"))
        if not recorded:
            raise ProductServiceError(
                ErrorCode.EVIDENCE_INVALID,
                f"revision {revision.get('revision_id')} records no "
                "compile-artifact identities, so no run can prove it "
                "executes the stored compilation",
                operation="compilation_parity",
                resource_id=revision.get("revision_id"))
        recompiled = compilation_view(FabricCompiler().compile(request))
        if recompiled.get("status") != "COMPILED":
            raise ProductServiceError(
                ErrorCode.EVIDENCE_INVALID,
                f"revision {revision.get('revision_id')} no longer "
                f"recompiles ({recompiled.get('status')}: "
                f"{recompiled.get('error')}) — refusing a run against "
                "drifted compiler semantics",
                operation="compilation_parity",
                resource_id=revision.get("revision_id"))
        fresh = recompiled.get("artifact_hashes") or {}
        if fresh != recorded:
            drifted = sorted(
                {*recorded, *fresh} - {
                    k for k in recorded
                    if k in fresh and fresh[k] == recorded[k]})
            raise ProductServiceError(
                ErrorCode.EVIDENCE_INVALID,
                f"revision {revision.get('revision_id')} recompiles to "
                f"different artifacts (drifted: {drifted}) — refusing a "
                "run that would not execute the stored compilation",
                operation="compilation_parity",
                resource_id=revision.get("revision_id"))

    def _run_evaluation(self, project_id: str, revision: dict[str, Any],
                        binary: Path, progress) -> tuple[str, dict[str, Any]]:
        request = parse_request_doc(revision["request"])
        self._check_compilation_parity(revision, request)
        run_id = new_run_id()
        bundle_dir = self.store.run_bundle_dir(project_id, run_id)
        progress("RUNNING")
        product = evaluate_product(
            request, binary=binary,
            network_clock_hz=self.config.network_clock_hz,
            timeout_s=self.config.timeout_s,
            run_dir=bundle_dir, repo_root=self.config.repo_root)
        evaluation = (None if product.outcome is None
                      else product.outcome.to_view_dict())
        outcome = product.outcome
        bundle_id = None
        if product.status == "EVALUATED":
            progress("FINALIZING")
            manifest = finalize_run_bundle(bundle_dir)
            bundle_id = "sha256:" + manifest["bundle_id"]
        run = {
            "schema_version": 1,
            "run_id": run_id,
            "project_id": project_id,
            "revision_id": revision["revision_id"],
            "design_hash": revision["design_hash"],
            # The identity gate above recompiled the stored request and
            # matched every recorded artifact hash before executing.
            "compilation_parity": "MATCHED",
            "display_name": self._run_display_name(revision),
            "backend": None if outcome is None else outcome.backend,
            "status": _RUN_STATUS.get(product.status, product.status),
            # Carried from the canonical evaluator. FabricEvaluator only
            # reaches EVALUATED after a pinned producer, admitted evidence
            # and a reloaded/verified chain, so EVALUATED *is* the
            # certified outcome; the basis is recorded for auditability.
            "qualification": ("QUALIFIED" if product.status == "EVALUATED"
                              else None),
            "qualification_basis": (
                "canonical FabricEvaluator EVALUATED (pinned producer, "
                "admitted + reload-verified evidence)" if product.status
                == "EVALUATED" else None),
            "requirements_pass": product.requirements_pass,
            "started_at": utcnow(),
            "completed_at": utcnow(),
            "bundle_id": bundle_id,
            "evaluation": evaluation,
            "requirements": product.requirement_report,
            "producer": (None if outcome is None or
                         outcome.producer_identity is None else {
                             "backend": outcome.backend,
                             "producer_identity": outcome.producer_identity,
                             "config_hash": outcome.backend_config_hash,
                             "input_hash": outcome.backend_input_hash}),
            "evidence": (None if outcome is None or
                         outcome.evidence_id is None else {
                             "evidence_id": outcome.evidence_id,
                             "raw_evidence_digest": outcome.raw_evidence_digest,
                             "stats_digest": outcome.stats_digest,
                             "run_bundle": bundle_id}),
            "reason": product.reason,
        }
        self.store.create_run(project_id, run)
        state = "COMPLETED" if product.status == "EVALUATED" else "REFUSED"
        return state, {"run_id": run_id}

    @staticmethod
    def _run_display_name(revision: dict[str, Any]) -> str:
        design = revision.get("design") or {}
        wl = design.get("workload") or {}
        noc = design.get("noc_guided") or {}
        model = wl.get("model_name") or wl.get("model_family") or "workload"
        topology = noc.get("topology_family") or "fabric"
        width = noc.get("link_width")
        width_text = f" · {width}b" if width is not None else ""
        return f"{model} · {topology}{width_text}"

    # ── runs ──────────────────────────────────────────────────────────

    def list_runs(self, *, project_id: str | None = None,
                  revision_id: str | None = None) -> dict[str, Any]:
        runs = self.store.list_runs(project_id=project_id,
                                    revision_id=revision_id)
        return {"contract_version": 1,
                "runs": [self._run_summary(r) for r in runs]}

    @staticmethod
    def _run_summary(run: dict[str, Any]) -> dict[str, Any]:
        evaluation = run.get("evaluation") or {}
        metrics = evaluation.get("metrics") or {}
        return {
            "run_id": run["run_id"],
            "display_name": run.get("display_name"),
            "project_id": run["project_id"],
            "revision_id": run["revision_id"],
            "design_hash": run.get("design_hash"),
            "backend": run.get("backend"),
            "status": run.get("status"),
            "qualification": run.get("qualification"),
            "requirements_pass": run.get("requirements_pass"),
            "started_at": run.get("started_at"),
            "completed_at": run.get("completed_at"),
            "bundle_id": run.get("bundle_id"),
            "workload_id": evaluation.get("workload_id"),
            "completion_cycles": metrics.get("completion_cycles"),
        }

    def _verify_run_bundle(self, run: dict[str, Any]) -> dict[str, Any] | None:
        """Re-verify the durable RunBundle before any trust read.

        A finalized bundle is the evidence authority: every read of a run,
        its evidence or its artifacts recomputes the content identity and
        refuses when the bundle is missing, tampered, or no longer matches
        the run record. Returns the verification summary, or None when the
        run has no bundle (e.g. a refused evaluation).
        """
        recorded = run.get("bundle_id")
        if recorded is None:
            return None
        bundle_dir = self.store.run_bundle_dir(run["project_id"], run["run_id"])
        try:
            summary = verify_run_bundle(bundle_dir)
        except RunBundleError as exc:
            raise ProductServiceError(
                ErrorCode.EVIDENCE_INVALID,
                f"run bundle failed verification: {exc}",
                operation="verify_run_bundle",
                resource_id=run["run_id"]) from exc
        computed = "sha256:" + summary["bundle_id"]
        if computed != recorded:
            raise ProductServiceError(
                ErrorCode.EVIDENCE_INVALID,
                f"run {run['run_id']} records bundle_id {recorded} but the "
                f"bundle content hashes to {computed} — refusing a tampered "
                "run bundle",
                operation="verify_run_bundle", resource_id=run["run_id"])
        return summary

    def get_run(self, run_id: str) -> dict[str, Any]:
        pid = self.store.find_run_project(run_id)
        if pid is None:
            raise ProductServiceError(
                ErrorCode.NOT_FOUND, f"no such run: {run_id}",
                operation="get_run", resource_id=run_id)
        run = self.store.load_run(pid, run_id)
        self._verify_run_bundle(run)
        return self._run_view(run)

    def _run_view(self, run: dict[str, Any]) -> dict[str, Any]:
        return {
            "contract_version": 1,
            "run_id": run["run_id"],
            "display_name": run.get("display_name"),
            "project_id": run["project_id"],
            "revision_id": run["revision_id"],
            "design_hash": run.get("design_hash"),
            "backend": run.get("backend"),
            "status": run.get("status"),
            "qualification": run.get("qualification"),
            "qualification_basis": run.get("qualification_basis"),
            "requirements_pass": run.get("requirements_pass"),
            "started_at": run.get("started_at"),
            "completed_at": run.get("completed_at"),
            "bundle_id": run.get("bundle_id"),
            "evaluation": run.get("evaluation"),
            "requirements": run.get("requirements"),
            "producer": run.get("producer"),
            "evidence": run.get("evidence"),
            "reason": run.get("reason"),
        }

    def run_evidence(self, run_id: str) -> dict[str, Any]:
        pid = self.store.find_run_project(run_id)
        if pid is None:
            raise ProductServiceError(
                ErrorCode.NOT_FOUND, f"no such run: {run_id}",
                operation="run_evidence", resource_id=run_id)
        run = self.store.load_run(pid, run_id)
        self._verify_run_bundle(run)
        bundle_dir = self.store.run_bundle_dir(pid, run_id)
        documents: dict[str, Any] = {}
        artifacts: list[dict[str, Any]] = []
        if bundle_dir.is_dir():
            for path in sorted(bundle_dir.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(bundle_dir).as_posix()
                artifacts.append({"path": rel,
                                  "size_bytes": path.stat().st_size})
                if path.suffix == ".json" and rel != "checksums.json":
                    try:
                        documents[rel] = json.loads(
                            path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
        return {
            "contract_version": 1,
            "run_id": run_id,
            "bundle_id": run.get("bundle_id"),
            "status": run.get("status"),
            "qualification": run.get("qualification"),
            "producer": run.get("producer"),
            "evidence": run.get("evidence"),
            "artifacts": artifacts,
            "documents": documents,
        }

    def run_artifacts(self,         run_id: str) -> dict[str, Any]:
        pid = self.store.find_run_project(run_id)
        if pid is None:
            raise ProductServiceError(
                ErrorCode.NOT_FOUND, f"no such run: {run_id}",
                operation="run_artifacts", resource_id=run_id)
        run = self.store.load_run(pid, run_id)
        self._verify_run_bundle(run)
        bundle_dir = self.store.run_bundle_dir(pid, run_id)
        files: dict[str, Any] = {}
        checksums = bundle_dir / "checksums.json"
        if checksums.is_file():
            try:
                files = json.loads(checksums.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                files = {}
        return {"contract_version": 1, "run_id": run_id,
                "bundle": files}

    # ── optimization ──────────────────────────────────────────────────

    def submit_optimization(self, revision_id: str,
                            body: dict[str, Any]) -> dict[str, Any]:
        pid, revision = self.store.load_revision_global(revision_id)
        definition_doc = self._parse_definition(body)
        binary = self._require_backend()
        job = self.jobs.submit(
            pid, kind="OPTIMIZATION", revision_id=revision_id,
            fn=lambda progress: self._run_optimization(
                pid, revision, binary, definition_doc, progress))
        return self.job_view(job)

    @staticmethod
    def _parse_definition(body: dict[str, Any]) -> dict[str, Any]:
        try:
            domain = [{"name": d["name"], "values": list(d["values"])}
                      for d in body.get("domain", [])]
            objectives = [{"metric": o["metric"], "direction": o["direction"]}
                          for o in body.get(
                              "objectives",
                              [{"metric": "completion_cycles",
                                "direction": "MIN"}])]
            constraints = [{"metric": c["metric"], "op": c["op"],
                            "threshold": c["threshold"]}
                           for c in body.get("constraints", [])]
            method = body.get("method", "grid")
            selection = body.get("selection")
            seed = body.get("seed")
        except (KeyError, TypeError) as exc:
            raise intent_error(f"malformed optimization definition: {exc}") from exc
        if not domain:
            raise intent_error("optimization requires a non-empty domain")
        return {"domain": domain, "objectives": objectives,
                "constraints": constraints, "method": method,
                "selection": selection, "seed": seed}

    def _run_optimization(self, project_id: str, revision: dict[str, Any],
                          binary: Path, definition_doc: dict[str, Any],
                          progress) -> tuple[str, dict[str, Any]]:
        from veritx_dse.model.compile_model import CompileRequestV3
        from veritx_dse.optimization.definition import (
            Constraint, DomainParam, Objective, OptimizationDefinition,
        )
        from veritx_dse.optimization.result import (
            CertifiedBackendConfig, Optimizer,
        )
        request = parse_request_doc(revision["request"])
        if not isinstance(request, CompileRequestV3):
            raise ProductServiceError(
                ErrorCode.UNSUPPORTED_SEMANTICS,
                "certified optimization requires a v3 design request",
                operation="optimize")
        try:
            definition = OptimizationDefinition(
                domain=tuple(DomainParam(d["name"], tuple(d["values"]))
                             for d in definition_doc["domain"]),
                objectives=tuple(Objective(o["metric"], o["direction"])
                                 for o in definition_doc["objectives"]),
                constraints=tuple(Constraint(c["metric"], c["op"],
                                             c["threshold"])
                                  for c in definition_doc["constraints"]),
                method=definition_doc["method"])
        except (KeyError, TypeError, ValueError) as exc:
            raise intent_error(
                f"optimization definition is invalid: {exc}") from exc
        run_root = (self.store.project_dir(project_id) / "optimizations"
                    / "_runs" / _new_id("run"))
        progress("RUNNING")
        study = Optimizer().optimize_certified(
            request, definition,
            backend_config=CertifiedBackendConfig(
                binary=str(binary),
                network_clock_hz=self.config.network_clock_hz,
                timeout_s=self.config.timeout_s,
                run_root=str(run_root), repo_root=str(self.config.repo_root)))
        view = study.to_study_view()
        optimization_id = _new_id("opt")
        runs = self.store.list_runs(project_id=project_id)
        by_result: dict[str, str] = {}
        for run in runs:
            evaluation = run.get("evaluation") or {}
            result_id = evaluation.get("performance_result_id")
            if result_id:
                by_result[result_id] = run["run_id"]
        candidate_runs = []
        for candidate in view.get("candidates", []):
            evaluation_ids = candidate.get("evaluation_ids") or {}
            result_id = evaluation_ids.get("performance_result_id")
            run_id = by_result.get(result_id)
            candidate_runs.append({
                "candidate_id": candidate["candidate_id"],
                "performance_result_id": result_id,
                "requirement_report_id":
                    evaluation_ids.get("requirement_report_id"),
                "run_id": run_id,
                # A candidate execution is its own resource unless it was
                # independently registered as a Product Run. It is NOT a
                # verified RunBundle by default.
                "evidence_kind": ("product-run" if run_id
                                  else "optimization-candidate"),
                "evaluation_status": candidate.get("evaluation_status"),
                "evaluation_authority": candidate.get("evaluation_authority"),
            })
        optimization = {
            "schema_version": 1,
            "optimization_id": optimization_id,
            "project_id": project_id,
            "base_revision_id": revision["revision_id"],
            "created_at": utcnow(),
            "study": view,
            "candidate_runs": candidate_runs,
            "candidate_evidence_note": (
                "Candidate evidence lives in the certified optimization "
                "study (performance_result_id / requirement_report_id). A "
                "candidate is linked to a Product Run only when an existing "
                "verified run registered the same performance_result_id; "
                "otherwise its evidence_kind is 'optimization-candidate' and "
                "run_id is null."),
            "selected_candidate_id": view.get("selected_candidate_id"),
        }
        self.store.create_optimization(project_id, optimization)
        return "COMPLETED", {"optimization_id": optimization_id}

    def get_optimization(self, optimization_id: str) -> dict[str, Any]:
        pid = self.store.find_optimization_project(optimization_id)
        if pid is None:
            raise ProductServiceError(
                ErrorCode.NOT_FOUND,
                f"no such optimization: {optimization_id}",
                operation="get_optimization", resource_id=optimization_id)
        opt = self.store.load_optimization(pid, optimization_id)
        return {
            "contract_version": 1,
            "optimization_id": opt["optimization_id"],
            "project_id": opt["project_id"],
            "base_revision_id": opt["base_revision_id"],
            "created_at": opt["created_at"],
            "study": opt["study"],
            "candidate_runs": opt["candidate_runs"],
            "candidate_evidence_note": opt.get("candidate_evidence_note"),
            "selected_candidate_id": opt["selected_candidate_id"],
        }

    # ── compare ───────────────────────────────────────────────────────

    def compare(self, a_run_id: str, b_run_id: str) -> dict[str, Any]:
        a = self.get_run(a_run_id)
        b = self.get_run(b_run_id)
        compatibility = self._compare_compatibility(a, b)
        a_metrics = (a.get("evaluation") or {}).get("metrics") or {}
        b_metrics = (b.get("evaluation") or {}).get("metrics") or {}
        keys = sorted(set(a_metrics) | set(b_metrics))

        def numeric(value: Any) -> bool:
            return (value is not None and isinstance(value, (int, float))
                    and not isinstance(value, bool))

        rows = []
        for key in keys:
            av = a_metrics.get(key)
            bv = b_metrics.get(key)
            rows.append({
                "key": key,
                "a": av,
                "b": bv,
                # Comparable only when the scenarios are compatible AND
                # both sides actually measured the quantity. Same key is
                # not enough.
                "comparable": (compatibility["compatible"]
                               and numeric(av) and numeric(bv)),
            })
        return {
            "contract_version": 1,
            "a": self._compare_side(a),
            "b": self._compare_side(b),
            "compatibility": compatibility,
            "rows": rows,
            "note": ("No automatic winner. Rows are marked comparable only "
                     "when both runs share a workload identity, a backend "
                     "and a QUALIFIED evidence chain, and both measured the "
                     "quantity; tradeoffs are shown as-is."),
        }

    @staticmethod
    def _compare_compatibility(a: dict[str, Any],
                               b: dict[str, Any]) -> dict[str, Any]:
        """The explicit compatibility gate. Same metric key is not enough."""
        a_eval = a.get("evaluation") or {}
        b_eval = b.get("evaluation") or {}
        a_workload = a_eval.get("workload_id")
        b_workload = b_eval.get("workload_id")
        same_workload = (a_workload is not None
                         and a_workload == b_workload)
        a_backend = a.get("backend")
        b_backend = b.get("backend")
        same_backend = (a_backend is not None and a_backend == b_backend)
        both_qualified = (a.get("qualification") == "QUALIFIED"
                          and b.get("qualification") == "QUALIFIED")
        reasons: list[str] = []
        if not same_workload:
            reasons.append(
                "different or missing workload identity "
                f"({a_workload!r} vs {b_workload!r})")
        if not same_backend:
            reasons.append(
                f"different or missing backend ({a_backend!r} vs "
                f"{b_backend!r})")
        if not both_qualified:
            reasons.append("at least one run has no QUALIFIED evidence chain")
        return {
            "compatible": same_workload and same_backend and both_qualified,
            "same_workload": same_workload,
            "same_backend": same_backend,
            "both_qualified": both_qualified,
            "metric_units": ("not carried by EvaluationView v1; metrics are "
                             "raw backend quantities"),
            "reasons": reasons,
        }

    def _compare_side(self, run: dict[str, Any]) -> dict[str, Any]:
        project_id = run["project_id"]
        revision = self.store.load_revision(project_id, run["revision_id"])
        design = revision.get("design") or {}
        return {
            "run_id": run["run_id"],
            "display_name": run.get("display_name"),
            "revision_id": run["revision_id"],
            "design_hash": run.get("design_hash"),
            "backend": run.get("backend"),
            "status": run.get("status"),
            "qualification": run.get("qualification"),
            "workload_id": (run.get("evaluation") or {}).get("workload_id"),
            "noc": design.get("noc_guided"),
            "locked_derived": design.get("locked_derived"),
            "requirements_pass": run.get("requirements_pass"),
        }

    # ── flow ──────────────────────────────────────────────────────────

    @staticmethod
    def _latest_refusal(latest: dict[str, Any] | None) -> str | None:
        """The refusal reason when the latest attempt is not usable."""
        if latest is None:
            return None
        compilation = latest.get("compilation") or {}
        certificate = latest.get("certificate") or {}
        if (compilation.get("status") == "COMPILED"
                and certificate.get("overall") == "PASS"):
            return None
        return (compilation.get("error")
                or "compilation was not successful")

    @classmethod
    def _flow(cls, active: dict[str, Any] | None, dirty: bool,
              runs: list[dict[str, Any]],
              jobs: list[dict[str, Any]],
              latest: dict[str, Any] | None = None,
              draft_hash: str | None = None) -> dict[str, Any]:
        if active is None:
            refusal = cls._latest_refusal(latest)
            if refusal is not None:
                return {"state": "REFUSED", "next_action": "EDIT_DRAFT",
                        "reason": refusal}
            return {"state": "DRAFT" if not dirty else "DIRTY",
                    "next_action": "COMPILE",
                    "reason": "no compiled revision yet"}
        active_runs = [r for r in runs
                       if r.get("revision_id") == active["revision_id"]]
        active_jobs = [j for j in jobs
                       if j.get("revision_id") == active["revision_id"]]
        evaluating = [j for j in active_jobs
                      if j["kind"] == "EVALUATION"
                      and j["state"] not in ("COMPLETED", "REFUSED",
                                             "FAILED", "CANCELLED")]
        optimizing = [j for j in active_jobs
                      if j["kind"] == "OPTIMIZATION"
                      and j["state"] not in ("COMPLETED", "REFUSED",
                                             "FAILED", "CANCELLED")]
        compilation = active.get("compilation") or {}
        certificate = active.get("certificate") or {}
        if compilation.get("status") != "COMPILED":
            return {"state": "REFUSED", "next_action": "EDIT_DRAFT",
                    "reason": compilation.get("error")
                    or "compilation was not successful"}
        if dirty:
            # The draft still equals a refused attempt: recompiling would
            # reproduce the refusal, so the next action is fixing the
            # design, not compiling again.
            if (latest is not None and draft_hash is not None
                    and draft_hash == latest.get("design_hash")):
                refusal = cls._latest_refusal(latest)
                if refusal is not None:
                    return {"state": "REFUSED",
                            "next_action": "EDIT_DRAFT",
                            "reason": refusal}
            return {"state": "DIRTY", "next_action": "COMPILE",
                    "reason": "draft has uncompiled changes"}
        if certificate.get("overall") != "PASS":
            return {"state": "COMPILED", "next_action": "INSPECT_VERIFY",
                    "reason": "certificate is not PASS"}
        if optimizing:
            return {"state": "OPTIMIZING", "next_action": "WAIT",
                    "reason": f"optimization {optimizing[-1]['job_id']}"}
        if evaluating:
            return {"state": "EVALUATING", "next_action": "WAIT",
                    "reason": f"evaluation {evaluating[-1]['job_id']}"}
        evaluated = [r for r in active_runs
                     if r.get("status") == "EVALUATED"]
        if evaluated:
            return {"state": "EVALUATED",
                    "next_action": "COMPARE_OR_OPTIMIZE",
                    "reason": f"latest run {evaluated[-1]['run_id']}"}
        failed = [r for r in active_runs
                  if r.get("status") in ("FAILED", "INVALID",
                                         "UNSUPPORTED")]
        if failed:
            return {"state": "EVALUATION_FAILED",
                    "next_action": "RUN_EVALUATION",
                    "reason": failed[-1].get("reason")}
        return {"state": "VERIFIED", "next_action": "RUN_EVALUATION",
                "reason": "certificate PASS"}


__all__ = [
    "BackendUnavailable", "ProductConfig", "ProductService",
    "ProductServiceError", "parse_request_doc",
]

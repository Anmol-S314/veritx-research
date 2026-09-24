"""Layer 5: metamorphic invariants.

Transform the experiment without changing its physics, then assert the
physics did not move. These catch hidden state and accidental coupling
that ordinary tests miss. The invariant is PHYSICS (completion, packet
and flit counts, VC count), not identity: a non-physical field is allowed
to move the compiled-artifact hash (the artifact is bound to the whole
design intent) but must never move the simulated network.
"""
from __future__ import annotations

import copy
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .fabric import _request_doc, build


@dataclass(frozen=True)
class MetaResult:
    name: str
    invariant: str
    passed: bool
    detail: str
    observations: dict[str, Any] = field(default_factory=dict)


def _exec(built, binary: Path, run_dir: Path, seed: int = 0) -> dict:
    from veritx_dse.backend.booksim_execution import execute_prepared_booksim
    shutil.rmtree(run_dir, ignore_errors=True)
    record = execute_prepared_booksim(
        prepared=built.prepared, binary=binary, run_dir=run_dir,
        timeout=60, seed=seed)
    return {"stats": record.evidence.stats,
            "evidence_id": record.evidence.evidence_id(),
            "prepared_id": built.prepared.prepared_id(),
            "fabric_hash": built.bundle.resolved_fabric.resolved_fabric_hash,
            "packets": built.packets, "flits": built.flits,
            "vcs": built.prepared.num_vcs}


def _physics(run: dict) -> tuple:
    return (run["stats"]["completion_cycles"], run["packets"],
            run["flits"], run["vcs"])


def _reverse_keys(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _reverse_keys(obj[k]) for k in reversed(list(obj))}
    if isinstance(obj, list):
        return [_reverse_keys(x) for x in obj]
    return obj


def run_metamorphic(binary: Path, work_root: Path,
                    experiment: str = "V01-single-p2p-2x2.json"
                    ) -> list[MetaResult]:
    from .spec import ExperimentSpec
    root = Path(__file__).resolve().parents[1]
    spec = ExperimentSpec.load(root / "experiments" / experiment)
    work_root = Path(work_root)
    base_doc = _request_doc(spec)
    base = build(spec)
    base_run = _exec(base, binary, work_root / "meta-base")
    base_physics = _physics(base_run)
    results: list[MetaResult] = []

    # M1 — JSON key order must not move identity or physics
    reordered = build(spec, request_doc=_reverse_keys(copy.deepcopy(base_doc)))
    run = _exec(reordered, binary, work_root / "meta-reorder")
    ok = (run["prepared_id"] == base_run["prepared_id"]
          and _physics(run) == base_physics)
    results.append(MetaResult(
        "M1_request_key_reorder",
        "identity and physics unchanged under JSON key reordering",
        ok,
        ("prepared_id and physics identical" if ok else
         f"moved: prepared {run['prepared_id'][:12]} vs "
         f"{base_run['prepared_id'][:12]}, physics "
         f"{_physics(run)} vs {base_physics}")))

    # M2-M5 — non-physical fields must not move physics
    def set_ceiling(doc):
        doc["requirements"][0]["latency_ceiling_cycles"] = 1.0

    def set_output(doc):
        doc["noc_config"]["output_formats"] = ["json", "systemc"]

    def rename(doc):
        doc["workload"]["model_name"] = "renamed"

    def dup_requirement(doc):
        doc["requirements"].append(dict(doc["requirements"][0]))

    for name, mutate in (("M2_requirement_threshold", set_ceiling),
                         ("M3_output_format", set_output),
                         ("M4_model_rename", rename),
                         ("M5_duplicate_requirement", dup_requirement)):
        doc = copy.deepcopy(base_doc)
        try:
            mutate(doc)
            variant = build(spec, request_doc=doc)
            run = _exec(variant, binary, work_root / f"meta-{name}")
        except Exception as exc:  # noqa: BLE001
            results.append(MetaResult(
                name, "non-physical field does not move physics", False,
                f"variant refused: {type(exc).__name__}: {exc}"))
            continue
        ok = _physics(run) == base_physics
        results.append(MetaResult(
            name, "non-physical field does not move physics", ok,
            ("physics identical" if ok else
             f"physics moved: {_physics(run)} vs {base_physics}"),
            {"identity_moved": run["fabric_hash"] != base_run["fabric_hash"]}))

    # M6 — a seed is a per-run input, not prepared identity, and must not
    # move trace-driven physics
    seeded = _exec(base, binary, work_root / "meta-seed", seed=8)
    ok = (seeded["prepared_id"] == base_run["prepared_id"]
          and _physics(seeded) == base_physics)
    results.append(MetaResult(
        "M6_seed_change", "seed does not move prepared identity or physics",
        ok,
        ("prepared_id and physics identical" if ok else "seed moved them")))

    # M7 — the same input run twice is the same science
    again = _exec(base, binary, work_root / "meta-repeat")
    ok = (again["evidence_id"] == base_run["evidence_id"]
          and again["stats"] == base_run["stats"])
    results.append(MetaResult(
        "M7_repeat_run", "two runs of one input share evidence identity",
        ok,
        ("evidence_id and stats identical" if ok else
         "evidence identity moved between identical runs")))

    # M8 — the run directory is not part of scientific identity
    moved = _exec(base, binary, work_root / "meta-elsewhere")
    ok = moved["evidence_id"] == base_run["evidence_id"]
    results.append(MetaResult(
        "M8_run_dir_independence",
        "moving the run directory does not move scientific identity",
        ok,
        ("evidence_id identical" if ok else
         "evidence_id changed with the run directory")))

    return results

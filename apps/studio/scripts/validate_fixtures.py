#!/usr/bin/env python3
"""Validate every Studio fixture against the frozen contracts.

For each apps/studio/fixtures/*.json (except the generator itself):
  1. Each non-null view validates against contracts/srota/v1/*.schema.json
     (Draft 2020-12, local files only — no network).
  2. Cross-view linkage: design_hash consistent across design/compilation/
     evaluation/requirements; optimization.base_design_hash matches;
     requirements.performance_result_id matches evaluation's (when both
     present); EVALUATED outcomes carry their required bindings.
  3. REALIZABILITY (P4 addendum): semantic values must project from real
     engine semantics. Schemas accept broad strings, so shape validity alone
     admits impossible products (e.g. rcu_enabled=True with COMPILED, which
     model/resolved_fabric.py refuses as UNSUPPORTED). The enum mirrors below
     are copied from the frozen engine authorities and are checked here.

Exit 0 iff all fixtures pass. Studio boots from fixtures only, so this is
the gate that keeps the UI honest.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

STUDIO = Path(__file__).resolve().parent.parent  # apps/studio
REPO = STUDIO.parent.parent  # workspace root
SCHEMAS = REPO / "contracts" / "srota" / "v1"
FIXTURE_DIR = STUDIO / "fixtures"

VIEW_SCHEMAS = {
    "design": "design.view.schema.json",
    "compilation": "compilation.view.schema.json",
    "evaluation": "evaluation.view.schema.json",
    "requirements": "requirement.report.schema.json",
    "optimization": "optimization.study.view.schema.json",
}

EXPECTED_FIXTURES = {
    "compiled-mesh",
    "invalid-design",
    "backend-unavailable",
    "evaluated-design",
    "optimization-study",
}

# ── engine-mirrored vocabularies (values, never imports) ─────────────────────
# model/compile_model.py::ModelFamily
MODEL_FAMILIES = {
    "dense_transformer",
    "mixture_of_experts",
    "diffusion",
    "cnn",
    "custom",
}
# model/compile_model.py::AgentKind
AGENT_KINDS = {
    "compute_tile",
    "hbm_controller",
    "nic",
    "peripheral",
    "ucie_port",
}
# model/compile_model.py::QoSClass
QOS_CLASSES = {"latency_critical", "bandwidth", "best_effort"}
# model/compile_model.py::TopologyFamily
TOPOLOGY_FAMILIES = {"mesh", "torus", "concentrated_mesh", "gec", "fat_tree"}
# model/compile_model.py::ServingMode
SERVING_MODES = {"prefill_heavy", "decode_heavy", "mixed"}
# model/router_behavior.py::_ARBITRATION_ALIASES
ARBITRATION_ALIASES = {"islip", "round_robin", "round-robin", "rr"}


def load_schema(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text())


def check_linkage(doc: dict, errors: list[str]) -> None:
    fid = doc.get("fixture_id", "?")
    design = doc.get("design") or {}
    dh = design.get("design_hash")
    comp = doc.get("compilation")
    if comp and comp.get("design_hash") != dh:
        errors.append(f"{fid}: compilation.design_hash != design.design_hash")
    ev = doc.get("evaluation")
    if ev:
        if ev.get("design_hash") != dh:
            errors.append(f"{fid}: evaluation.design_hash != design.design_hash")
        if ev.get("status") == "EVALUATED":
            for key in (
                "message_artifact_id",
                "physical_traffic_id",
                "backend_producer",
                "evidence",
                "performance_result_id",
                "network_traffic_window",
            ):
                if ev.get(key) is None:
                    errors.append(f"{fid}: EVALUATED missing {key}")
        if ev.get("status") in ("BACKEND_UNAVAILABLE", "FAILED", "UNSUPPORTED"):
            if ev.get("metrics") is not None:
                errors.append(
                    f"{fid}: {ev['status']} must not carry metrics "
                    "(absent metrics are absent, never zero-filled)"
                )
    req = doc.get("requirements")
    if req:
        if req.get("design_hash") != dh:
            errors.append(f"{fid}: requirements.design_hash != design.design_hash")
        if ev and ev.get("performance_result_id") and (
            req.get("performance_result_id") != ev["performance_result_id"]
        ):
            errors.append(f"{fid}: requirements.performance_result_id != evaluation's")
    opt = doc.get("optimization")
    if opt and opt.get("base_design_hash") != dh:
        errors.append(f"{fid}: optimization.base_design_hash != design.design_hash")


def check_realizable(doc: dict, errors: list[str]) -> None:
    """Semantic values must be producible by the real engine."""
    fid = doc.get("fixture_id", "?")
    design = doc.get("design")
    if not design:
        return
    wl = design.get("workload") or {}
    if wl.get("model_family") not in MODEL_FAMILIES:
        errors.append(
            f"{fid}: model_family {wl.get('model_family')!r} is not a "
            f"ModelFamily value {sorted(MODEL_FAMILIES)}"
        )
    if wl.get("serving_mode") is not None and wl["serving_mode"] not in SERVING_MODES:
        errors.append(
            f"{fid}: serving_mode {wl['serving_mode']!r} is not a ServingMode "
            f"value {sorted(SERVING_MODES)}"
        )
    for req in design.get("requirements", []):
        if req.get("qos_class") not in QOS_CLASSES:
            errors.append(
                f"{fid}: qos_class {req.get('qos_class')!r} is not a QoSClass "
                f"value {sorted(QOS_CLASSES)}"
            )
    for agent in design.get("agents", []):
        if agent.get("kind") not in AGENT_KINDS:
            errors.append(
                f"{fid}: agent kind {agent.get('kind')!r} is not an AgentKind "
                f"value {sorted(AGENT_KINDS)}"
            )
    guided = design.get("noc_guided") or {}
    if guided.get("topology_family") is not None and (
        guided["topology_family"] not in TOPOLOGY_FAMILIES
    ):
        errors.append(
            f"{fid}: topology_family {guided['topology_family']!r} is not a "
            f"TopologyFamily value {sorted(TOPOLOGY_FAMILIES)}"
        )
    if guided.get("arbitration") is not None and (
        guided["arbitration"] not in ARBITRATION_ALIASES
    ):
        errors.append(
            f"{fid}: arbitration {guided['arbitration']!r} is not a known "
            f"allocator alias {sorted(ARBITRATION_ALIASES)}"
        )
    comp = doc.get("compilation")
    if (comp and comp.get("status") == "COMPILED"
            and guided.get("rcu_enabled") is True):
        errors.append(
            f"{fid}: rcu_enabled=True with status COMPILED is impossible — "
            "model/resolved_fabric.py refuses rcu_enabled=True as UNSUPPORTED"
        )
    # materialize_family sizing: radix pins k, and k*k*concentration seats
    # must cover the full agent count for the fabric to exist at all.
    radix = guided.get("radix")
    concentration = guided.get("concentration")
    if (comp and comp.get("status") == "COMPILED"
            and isinstance(radix, int) and isinstance(concentration, int)):
        endpoints = sum(a.get("count", 0) for a in design.get("agents", []))
        seats = radix * radix * concentration
        if seats < endpoints:
            errors.append(
                f"{fid}: radix {radix} × concentration {concentration} "
                f"provides {seats} seats but {endpoints} agents must attach — "
                "the compiler would refuse (UNSUPPORTED), never COMPILE"
            )


def self_test() -> list[str]:
    """Prove the realizability gate rejects the impossibilities it exists for.

    Each case is a document the frozen schemas would accept but the engine
    cannot produce. If any case passes silently, the gate is broken.
    """
    errors: list[str] = []
    base_design = {
        "workload": {"model_family": "dense_transformer", "serving_mode": "mixed"},
        "requirements": [{"qos_class": "latency_critical"}],
        "agents": [{"kind": "compute_tile", "count": 64},
                   {"kind": "hbm_controller", "count": 8},
                   {"kind": "nic", "count": 2},
                   {"kind": "peripheral", "count": 4}],
        "noc_guided": {"topology_family": "mesh", "radix": 5,
                       "concentration": 4, "arbitration": "round_robin",
                       "rcu_enabled": False},
    }
    compiled = {"status": "COMPILED"}

    def mutated(**over):
        import copy
        design = copy.deepcopy(base_design)
        for path, value in over.items():
            if path == "rcu_enabled":
                design["noc_guided"]["rcu_enabled"] = value
            elif path == "radix":
                design["noc_guided"]["radix"] = value
            else:
                design[path] = value
        return {"fixture_id": "self-test", "design": design,
                "compilation": compiled}

    cases = {
        "rcu_enabled=True with COMPILED": mutated(rcu_enabled=True),
        "invented model_family": mutated(workload={"model_family": "llama3"}),
        "invented agent kind": mutated(agents=[{"kind": "compute", "count": 64}]),
        "invented qos_class": mutated(requirements=[{"qos_class": "latency_sensitive"}]),
        "uppercase topology value": mutated(
            noc_guided={"topology_family": "MESH", "radix": 5,
                        "concentration": 4, "rcu_enabled": False}),
        "impossible sizing": mutated(radix=3),
    }
    for label, doc in cases.items():
        found: list[str] = []
        check_realizable(doc, found)
        if not found:
            errors.append(f"self-test: gate failed to reject {label}")
    return errors


def validate_one(path: Path, validators: dict[str, Draft202012Validator]) -> list[str]:
    errors: list[str] = []
    try:
        doc = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return [f"{path.name}: unreadable ({exc})"]
    for view, validator in validators.items():
        payload = doc.get(view)
        if payload is None:
            continue
        for err in validator.iter_errors(payload):
            errors.append(f"{path.name}:{view}: {list(err.path)}: {err.message}")
    if not errors:
        check_linkage(doc, errors)
        check_realizable(doc, errors)
    return errors


def main() -> int:
    validators = {v: Draft202012Validator(load_schema(s)) for v, s in VIEW_SCHEMAS.items()}
    errors: list[str] = self_test()
    if errors:
        print("FAIL (realizability gate self-test):")
        for e in errors:
            print(f"  - {e}")
        return 1
    found = sorted(p.stem for p in FIXTURE_DIR.glob("*.json"))
    errors: list[str] = []
    if set(found) != EXPECTED_FIXTURES:
        errors.append(
            f"fixture set mismatch: found {found}, expected {sorted(EXPECTED_FIXTURES)}"
        )
    for stem in sorted(EXPECTED_FIXTURES):
        path = FIXTURE_DIR / f"{stem}.json"
        if not path.exists():
            errors.append(f"missing fixture {stem}.json")
            continue
        view_errors = validate_one(path, validators)
        if view_errors:
            errors.extend(view_errors)
        else:
            print(f"PASS {stem}.json (schema + linkage + realizability)")
    if errors:
        print("FAIL:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"All {len(EXPECTED_FIXTURES)} fixtures validate against contracts/srota/v1 "
          "and pass the engine-vocabulary realizability gate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

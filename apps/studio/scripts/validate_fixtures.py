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
  4. ENGINE REALIZABILITY (RT-5b, default ON when CI is set): regenerate all
     five fixtures with the engine tool
     (tracks/t3-topology/dse/veritx_dse/tools/generate_studio_fixtures.py)
     into a temp directory and compare them to the committed fixtures. The
     only fields allowed to differ are producer-bound (see
     VOLATILE_FIELD_PATHS). If the engine or a runnable BookSim binary is
     unavailable this gate FAILS LOUDLY — the fast path alone never counts
     as a realizability pass. Use --skip-engine to opt out offline.

Exit 0 iff all selected gates pass. Studio boots from fixtures only, so this
is the gate that keeps the UI honest.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator

STUDIO = Path(__file__).resolve().parent.parent  # apps/studio
REPO = STUDIO.parent.parent  # workspace root
SCHEMAS = REPO / "contracts" / "srota" / "v1"
FIXTURE_DIR = STUDIO / "fixtures"
DSE_DIR = REPO / "tracks" / "t3-topology" / "dse"

STUDY_SCHEMA_V1 = "optimization.study.view.schema.json"
STUDY_SCHEMA_V2 = "optimization.study.view.v2.schema.json"

# Non-study views stay v1. The study view selects v2 when the payload
# declares contract_version 2 and the v2 schema exists (RT-1); v1 fixtures
# keep validating against v1.
VIEW_SCHEMAS = {
    "design": "design.view.schema.json",
    "compilation": "compilation.view.schema.json",
    "evaluation": "evaluation.view.schema.json",
    "requirements": "requirement.report.schema.json",
    "optimization": STUDY_SCHEMA_V1,
}

EXPECTED_FIXTURES = {
    "compiled-mesh",
    "invalid-design",
    "backend-unavailable",
    "evaluated-design",
    "optimization-study",
}

ENGINE_TOOL_MODULE = "veritx_dse.tools.generate_studio_fixtures"

# ── engine-realizability volatile-field allowlist (documented) ───────────────
# The committed fixtures must be reproducible by the engine tool. These are
# the only paths allowed to differ, and each is bound to the execution
# producer, which is host-specific by construction:
#   * producer_identity is the sha256 of the exact BookSim binary that ran;
#   * raw_evidence_digest hashes a persisted evidence artifact that embeds
#     its absolute run directory (fresh for every regeneration);
#   * the performance_result_id chain binds that evidence digest.
# Everything else — design, certificate/obligations, network window,
# metrics, requirement verdicts, candidates, objectives, Pareto — must match
# byte-for-byte (or exactly after stripping only these paths).
VOLATILE_FIELD_PATHS: tuple[tuple[str, ...], ...] = (
    ("evaluation", "backend_producer", "producer_identity"),
    ("evaluation", "evidence", "raw_evidence_digest"),
    ("evaluation", "performance_result_id"),
    ("requirements", "performance_result_id"),
    ("requirements", "entries", "*", "performance_result_id"),
    ("optimization", "candidates", "*", "evaluation_ids",
     "performance_result_id"),
)

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


def study_schema_name(payload: dict) -> str:
    """v2 study view when declared and available, else v1."""
    if (isinstance(payload, dict)
            and payload.get("contract_version") == 2
            and (SCHEMAS / STUDY_SCHEMA_V2).exists()):
        return STUDY_SCHEMA_V2
    return STUDY_SCHEMA_V1


def check_linkage(doc: dict, errors: list[str]) -> None:
    fid = doc.get("fixture_id", "?")
    design = doc.get("design") or {}
    dh = design.get("design_hash")
    comp = doc.get("compilation")
    ev = doc.get("evaluation")
    req = doc.get("requirements")
    opt = doc.get("optimization")
    # Study rule: an optimization fixture spans base intent + winning
    # design. design/opt.base bind the BASE; comp/eval/req bind ONE
    # winner hash that must appear among the study candidates. A study
    # claiming a winner outside its own candidate set is incoherent.
    candidate_hashes = set()
    if isinstance(opt, dict):
        for row in opt.get("candidates", []):
            h = (row.get("evaluation_ids") or {}).get("design_hash")
            if h:
                candidate_hashes.add(h)
    product_hashes = {
        slot for slot in (
            (comp or {}).get("design_hash"),
            (ev or {}).get("design_hash"),
            (req or {}).get("design_hash"),
        ) if slot}
    # The winner hash is exempt from single-design equality below, but
    # never from the completeness checks (EVALUATED slots stay fully
    # audited whichever design they bind).
    winner_ok: set[str] = set()
    if candidate_hashes and product_hashes - {dh}:
        extra = product_hashes - {dh}
        if len(extra) != 1 or not extra <= candidate_hashes:
            errors.append(
                f"{fid}: study product views must share one winner hash "
                f"from the study candidates, got {sorted(extra)}")
        else:
            winner_ok = extra
    if comp and comp.get("design_hash") != dh \
            and comp.get("design_hash") not in winner_ok:
        errors.append(f"{fid}: compilation.design_hash != design.design_hash")
    if ev:
        if ev.get("design_hash") != dh \
                and ev.get("design_hash") not in winner_ok:
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
    if req:
        if req.get("design_hash") != dh \
                and req.get("design_hash") not in winner_ok:
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


# ── engine realizability (RT-5b) ─────────────────────────────────────────────

def _strip_paths(node, path: tuple[str, ...]) -> None:
    key = path[0]
    if len(path) == 1:
        if isinstance(node, dict):
            node.pop(key, None)
        return
    if key == "*":
        if isinstance(node, list):
            for item in node:
                _strip_paths(item, path[1:])
        return
    if isinstance(node, dict) and key in node:
        _strip_paths(node[key], path[1:])


def _normalized(doc: dict) -> dict:
    stripped = copy.deepcopy(doc)
    for path in VOLATILE_FIELD_PATHS:
        _strip_paths(stripped, path)
    return stripped


def _canonical(doc: dict) -> str:
    return json.dumps(_normalized(doc), sort_keys=True, indent=2)


def _diff_paths(a, b, prefix: str = "") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        paths: list[str] = []
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                paths.append(f"{prefix}.{key}")
            else:
                paths.extend(_diff_paths(a[key], b[key], f"{prefix}.{key}"))
        return paths
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{prefix} (length {len(a)} != {len(b)})"]
        paths = []
        for i, (x, y) in enumerate(zip(a, b)):
            paths.extend(_diff_paths(x, y, f"{prefix}[{i}]"))
        return paths
    if a != b:
        return [prefix or "<root>"]
    return []


def engine_mode_default() -> bool:
    """Engine mode is ON by default in CI, OFF on an offline workstation."""
    return bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))


def check_engine_realizability() -> list[str]:
    """Regenerate with the engine tool and compare against the committed files.

    Returns a list of errors; empty means every fixture is engine-realizable.
    """
    if not DSE_DIR.exists():
        return [
            f"ENGINE CHECK FAILED: engine package not found at {DSE_DIR}. "
            "This gate proves fixtures are realizable by running the engine; "
            "it never passes on the schema fast path alone. Re-run with "
            "--skip-engine to explicitly skip realizability (not a gate pass)."
        ]
    if str(DSE_DIR) not in sys.path:
        sys.path.insert(0, str(DSE_DIR))
    try:
        from veritx_dse.core.paths import REPO as engine_repo
        from veritx_dse.tools import generate_studio_fixtures as engine
    except Exception as exc:
        return [
            f"ENGINE CHECK FAILED: cannot import {ENGINE_TOOL_MODULE}: "
            f"{type(exc).__name__}: {exc}. A runnable engine checkout "
            "(Python >= 3.12) is required; re-run with --skip-engine to "
            "explicitly skip realizability (not a gate pass)."
        ]
    if Path(engine_repo).resolve() != REPO.resolve():
        return [
            f"ENGINE CHECK FAILED: engine package resolves to a different "
            f"checkout ({engine_repo}) than this workspace ({REPO}); refusing "
            "to compare fixtures against a foreign engine tree."
        ]
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="studio-fixture-regen-") as tmp:
        tmp_dir = Path(tmp)
        # The engine tool preserves title/description from the existing
        # envelope, so seed the temp dir with the committed fixtures.
        for stem in EXPECTED_FIXTURES:
            shutil.copy2(FIXTURE_DIR / f"{stem}.json", tmp_dir / f"{stem}.json")
        old_fixture_dir = engine.FIXTURE_DIR
        engine.FIXTURE_DIR = str(tmp_dir)
        try:
            engine.main()
        except Exception as exc:
            return [
                f"ENGINE CHECK FAILED: fixture regeneration raised "
                f"{type(exc).__name__}: {exc}. A runnable BookSim binary and "
                "the engine package are required; this gate never passes on "
                "the schema fast path alone. Re-run with --skip-engine to "
                "explicitly skip realizability (not a gate pass)."
            ]
        finally:
            engine.FIXTURE_DIR = old_fixture_dir
        for stem in sorted(EXPECTED_FIXTURES):
            committed = FIXTURE_DIR / f"{stem}.json"
            regenerated = tmp_dir / f"{stem}.json"
            if not regenerated.exists():
                errors.append(
                    f"{stem}.json: engine regeneration produced no file")
                continue
            committed_bytes = committed.read_bytes()
            regenerated_bytes = regenerated.read_bytes()
            if committed_bytes == regenerated_bytes:
                print(f"PASS {stem}.json (engine byte-identical)")
                continue
            committed_doc = json.loads(committed_bytes)
            regenerated_doc = json.loads(regenerated_bytes)
            if _canonical(committed_doc) == _canonical(regenerated_doc):
                volatile = sorted(set(_diff_paths(committed_doc,
                                                  regenerated_doc)))
                print(f"PASS {stem}.json (engine-realizable; "
                      f"producer-volatile only: {', '.join(volatile)})")
                continue
            differing = _diff_paths(committed_doc, regenerated_doc)
            errors.append(
                f"{stem}.json differs from engine regeneration on "
                f"non-volatile field(s): {', '.join(differing[:10])}"
                + (" ..." if len(differing) > 10 else ""))
    return errors


def validate_one(path: Path, validators: dict[str, Draft202012Validator]) -> list[str]:
    errors: list[str] = []
    try:
        doc = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return [f"{path.name}: unreadable ({exc})"]
    for view, default_schema in VIEW_SCHEMAS.items():
        payload = doc.get(view)
        if payload is None:
            continue
        schema_name = default_schema
        if view == "optimization":
            schema_name = study_schema_name(payload)
        validator = validators[schema_name]
        for err in validator.iter_errors(payload):
            errors.append(f"{path.name}:{view}: {list(err.path)}: {err.message}")
    if not errors:
        check_linkage(doc, errors)
        check_realizable(doc, errors)
    return errors


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Studio fixtures (schema + linkage + "
                    "engine realizability).")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--engine", action="store_true",
        help="force the engine realizability check (regenerate + compare)")
    group.add_argument(
        "--skip-engine", action="store_true",
        help="skip the engine realizability check (offline; fast path only)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    engine_mode = args.engine or (not args.skip_engine and engine_mode_default())
    schema_names = [
        "design.view.schema.json",
        "compilation.view.schema.json",
        "evaluation.view.schema.json",
        "requirement.report.schema.json",
        STUDY_SCHEMA_V1,
    ]
    if (SCHEMAS / STUDY_SCHEMA_V2).exists():
        schema_names.append(STUDY_SCHEMA_V2)
    validators = {name: Draft202012Validator(load_schema(name))
                  for name in schema_names}
    if STUDY_SCHEMA_V2 in validators:
        print(f"Study view: {STUDY_SCHEMA_V1} + {STUDY_SCHEMA_V2} accepted")
    if engine_mode:
        print("Engine realizability: ON (regenerate with the engine tool "
              "and compare)")
    else:
        print("WARNING: ENGINE REALIZABILITY NOT VERIFIED (fast path only). "
              "Pass --engine where the engine + BookSim are available.")

    errors: list[str] = self_test()
    if errors:
        print("FAIL (realizability gate self-test):")
        for e in errors:
            print(f"  - {e}")
        return 1
    found = sorted(p.stem for p in FIXTURE_DIR.glob("*.json"))
    errors = []
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
    print(f"All {len(EXPECTED_FIXTURES)} fixtures validate against "
          "contracts/srota/v1 and pass the engine-vocabulary realizability gate.")
    if not engine_mode:
        print("FAST PATH ONLY: engine realizability was not proven.")
        return 0
    print("Engine mode: regenerating fixtures with "
          f"{ENGINE_TOOL_MODULE} ...")
    engine_errors = check_engine_realizability()
    if engine_errors:
        print("FAIL (engine realizability):")
        for e in engine_errors:
            print(f"  - {e}")
        return 1
    print(f"All {len(EXPECTED_FIXTURES)} fixtures reproduce from the engine "
          "(producer-bound fields allowlisted).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

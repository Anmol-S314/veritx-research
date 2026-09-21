#!/usr/bin/env python3
"""Deterministic fixture generator for Srota Studio (P4).

Builds the five Studio fixtures in apps/studio/fixtures/. Pure stdlib data
construction — no engine imports (Studio consumes contract views only).
Every emitted view is shaped to validate against
contracts/srota/v1/*.schema.json; run scripts/validate_fixtures.py after.

All content identities are derived deterministically via sha256(label), so
regeneration is byte-identical.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent  # apps/studio/fixtures

OBLIGATIONS = [
    "TOPOLOGY_CONNECTED",
    "ATTACHMENT_COMPLETE",
    "ADDRESS_DECODE_VALID",
    "ROUTE_COMPLETE",
    "ROUTE_LEGAL",
    "VC_ASSIGNMENT_VALID",
    "DEADLOCK_FREE",
    "MAPPING_VALID",
    "PACKET_FORMAT_VALID",
    "FABRIC_DAG_VALID",
]

# Plausible certifier method strings (display only; engine is authoritative).
METHODS = {
    "TOPOLOGY_CONNECTED": "undirected-bfs/v1",
    "ATTACHMENT_COMPLETE": "seat-ledger/v1",
    "ADDRESS_DECODE_VALID": "decode-cover/v1",
    "ROUTE_COMPLETE": "class-src-dst-cover/v1",
    "ROUTE_LEGAL": "channel-legal/v1",
    "VC_ASSIGNMENT_VALID": "route-bound-vc/v1",
    "DEADLOCK_FREE": "channel-vc-cdg-acyclic/v1",
    "MAPPING_VALID": "rank-attachment/v1",
    "PACKET_FORMAT_VALID": "wire-format-fit/v1",
    "FABRIC_DAG_VALID": "bundle.revalidate/v1",
}


def h(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()[:16]


def base_design(tag: str, **over) -> dict:
    d = {
        "contract_version": 1,
        "design_hash": h(f"srota/design/{tag}"),
        "schema_version": 3,
        "compiler_semantics_version": 1,
        "workload": {
            "model_family": "llama3",
            "model_name": "llama3-70b",
            "parallelism": {"tp": 8, "pp": 2, "ep": 4, "dp": 2},
            "serving_mode": "decode",
            "workload_source_ref": {
                "content_digest": h(f"srota/workload-src/{tag}"),
                "format": "srota-workload-v3",
                "size_bytes": 4096,
            },
        },
        "requirements": [
            {
                "traffic_class": "hbm_read",
                "qos_class": "latency_sensitive",
                "latency_ceiling_cycles": 220,
                "bandwidth_floor_gbps": None,
                "binding": True,
            },
            {
                "traffic_class": "allreduce",
                "qos_class": "throughput_sensitive",
                "latency_ceiling_cycles": None,
                "bandwidth_floor_gbps": 1800,
                "binding": True,
            },
            {
                "traffic_class": "control",
                "qos_class": "best_effort",
                "latency_ceiling_cycles": None,
                "bandwidth_floor_gbps": None,
                "binding": False,
            },
        ],
        "agents": [
            {"kind": "compute", "count": 64},
            {"kind": "hbm", "count": 8},
            {"kind": "nic", "count": 2},
            {"kind": "peripheral", "count": 4},
        ],
        "noc_guided": {
            "topology_family": "MESH",
            "radix": 5,
            "concentration": 4,
            "link_width": 128,
            "rcu_enabled": True,
            "arbitration": "round_robin",
        },
    }
    d.update(over)
    return d


def locked_block(tag: str, overall: str = "PASS") -> dict:
    return {
        "routing": "DOR_XY",
        "vc_count": 4,
        "turn_restrictions": ["no Y-to-X turn (dimension-order XY)"],
        "certificate_overall": overall,
    }


def obligations_all_pass(tag: str) -> list[dict]:
    out = []
    for ob in OBLIGATIONS:
        out.append(
            {
                "obligation": ob,
                "status": "PASS",
                "method": METHODS[ob],
                "evidence": {
                    "digest": digest(f"srota/evidence/{tag}/{ob}"),
                    "bound": h(f"srota/fabric/{tag}"),
                },
            }
        )
    return out


def compiled_compilation(tag: str, design_hash: str) -> dict:
    return {
        "contract_version": 1,
        "status": "COMPILED",
        "design_hash": design_hash,
        "compiler_semantics_version": 1,
        "resolved_fabric_hash": h(f"srota/fabric/{tag}"),
        "certificate_id": h(f"srota/cert/{tag}"),
        "certificate_overall": "PASS",
        "obligations": obligations_all_pass(tag),
        "artifact_hashes": {
            "topology": h(f"srota/art/{tag}/topology"),
            "attachment": h(f"srota/art/{tag}/attachment"),
            "routes": h(f"srota/art/{tag}/routes"),
            "vc_assignment": h(f"srota/art/{tag}/vc"),
            "packet_format": h(f"srota/art/{tag}/packet"),
            "router_behavior": h(f"srota/art/{tag}/router"),
            "address_decode": h(f"srota/art/{tag}/decode"),
            "fabric": h(f"srota/fabric/{tag}"),
        },
        "error": None,
    }


def evaluated_evaluation(tag: str, design_hash: str, perf_id: str) -> dict:
    return {
        "contract_version": 1,
        "status": "EVALUATED",
        "design_hash": design_hash,
        "resolved_fabric_hash": h(f"srota/fabric/{tag}"),
        "workload_id": f"wl-{tag}",
        "message_artifact_id": f"msg-{tag}-v1",
        "physical_traffic_id": f"pt-{tag}-v1",
        "backend_producer": {
            "backend": "booksim2",
            "producer_identity": "booksim2@tools-base:2026.09 (qualified)",
            "config_hash": h(f"srota/simcfg/{tag}"),
            "input_hash": h(f"srota/siminput/{tag}"),
        },
        "evidence": {
            "raw_evidence_digest": digest(f"srota/rawev/{tag}"),
            "stats_digest": digest(f"srota/stats/{tag}"),
        },
        "performance_result_id": perf_id,
        "network_traffic_window": {
            "window_cycles": 50000,
            "wall_time_ns": None,
            "cycles_only": True,
        },
        "metrics": {
            "packets_injected": 128000,
            "packets_completed": 128000,
            "flits_completed": 512000,
            "avg_packet_latency_cycles": 96.4,
            "sustained_throughput_flits_per_cycle": 10.24,
        },
        "fidelity_warning": (
            "Cycle-approximate BookSim-class model. Cycles only — no valid "
            "network clock established, so no wall-time authority. Single "
            "aggregate NETWORK_TRAFFIC_WINDOW; never per-operation latency."
        ),
        "reason": None,
    }


def requirement_report(tag: str, design_hash: str, perf_id: str) -> dict:
    return {
        "contract_version": 1,
        "design_hash": design_hash,
        "performance_result_id": perf_id,
        "entries": [
            {
                "requirement_index": 0,
                "traffic_class": "hbm_read",
                "qos_class": "latency_sensitive",
                "verdict": "SATISFIED",
                "binding": True,
                "required": 220,
                "measured": 96.4,
                "metric_authority": "performance/result.py::build_performance_result",
                "performance_result_id": perf_id,
                "reason": "avg_packet_latency_cycles 96.4 <= ceiling 220",
            },
            {
                "requirement_index": 1,
                "traffic_class": "allreduce",
                "qos_class": "throughput_sensitive",
                "verdict": "SATISFIED",
                "binding": True,
                "required": 1800,
                "measured": 10.24,
                "metric_authority": "performance/result.py::build_performance_result",
                "performance_result_id": perf_id,
                "reason": "sustained throughput meets floor in model units",
            },
            {
                "requirement_index": 2,
                "traffic_class": "control",
                "qos_class": "best_effort",
                "verdict": "UNMEASURABLE",
                "binding": False,
                "required": None,
                "measured": None,
                "metric_authority": "performance/result.py::build_performance_result",
                "performance_result_id": perf_id,
                "reason": (
                    "best-effort class has no bound; UNMEASURABLE never passes "
                    "and is reported, not zero-filled"
                ),
            },
        ],
    }


def bundle(fixture_id: str, title: str, description: str, **views) -> dict:
    doc = {"fixture_id": fixture_id, "title": title, "description": description}
    for key in ("design", "compilation", "evaluation", "requirements", "optimization"):
        doc[key] = views.get(key)
    return doc


def fixture_compiled_mesh() -> dict:
    tag = "mesh64"
    design = base_design(tag)
    design["locked_derived"] = locked_block(tag)
    dh = design["design_hash"]
    return bundle(
        "compiled-mesh",
        "Compiled 4x4 concentrated mesh (64 compute + 8 HBM)",
        "Fresh COMPILED design. All 10 obligations PASS. No evaluation has "
        "been run yet, so the Evaluate section shows NOT_RUN.",
        design=design,
        compilation=compiled_compilation(tag, dh),
        evaluation=None,
        requirements=None,
        optimization=None,
    )


def fixture_invalid_design() -> dict:
    tag = "bad-conc"
    design = base_design(tag)
    design["noc_guided"] = {
        "topology_family": "MESH",
        "radix": 9,
        "concentration": 7,
        "link_width": 128,
        "rcu_enabled": False,
        "arbitration": "round_robin",
    }
    # Never compiled: no LOCKED block.
    design["locked_derived"] = None
    dh = design["design_hash"]
    obs = []
    for ob in OBLIGATIONS:
        if ob in ("ATTACHMENT_COMPLETE", "MAPPING_VALID"):
            obs.append(
                {
                    "obligation": ob,
                    "status": "FAIL",
                    "method": METHODS[ob],
                    "evidence": {
                        "digest": digest(f"srota/evidence/{tag}/{ob}"),
                        "reason": (
                            "concentration 7 leaves 1 compute tile unseated "
                            "(64 mod 7 != 0); 63/64 agents attached"
                        ),
                    },
                }
            )
        else:
            obs.append(
                {
                    "obligation": ob,
                    "status": "PASS",
                    "method": METHODS[ob],
                    "evidence": {"digest": digest(f"srota/evidence/{tag}/{ob}")},
                }
            )
    compilation = {
        "contract_version": 1,
        "status": "INVALID",
        "design_hash": dh,
        "compiler_semantics_version": 1,
        "certificate_id": h(f"srota/cert/{tag}"),
        "certificate_overall": "FAIL",
        "obligations": obs,
        "artifact_hashes": {},
        "error": (
            "INVALID: concentration 7 does not divide 64 compute tiles; "
            "ATTACHMENT_COMPLETE and MAPPING_VALID FAIL. No bundle produced."
        ),
    }
    return bundle(
        "invalid-design",
        "INVALID design (concentration 7 vs 64 tiles)",
        "Compiler-typed refusal: 2 of 10 obligations FAIL, no bundle, no "
        "resolved fabric hash. Verify section shows the failing obligations "
        "with reasons.",
        design=design,
        compilation=compilation,
        evaluation=None,
        requirements=None,
        optimization=None,
    )


def fixture_backend_unavailable() -> dict:
    tag = "mesh64-nobe"
    design = base_design(tag)
    design["locked_derived"] = locked_block(tag)
    dh = design["design_hash"]
    evaluation = {
        "contract_version": 1,
        "status": "BACKEND_UNAVAILABLE",
        "design_hash": dh,
        "resolved_fabric_hash": h(f"srota/fabric/{tag}"),
        "workload_id": f"wl-{tag}",
        "message_artifact_id": None,
        "physical_traffic_id": None,
        "backend_producer": None,
        "evidence": None,
        "performance_result_id": None,
        "network_traffic_window": None,
        "metrics": None,
        "fidelity_warning": None,
        "reason": (
            "No qualified BookSim producer on this host. Preconditions met "
            "(COMPILED + certificate PASS); no backend work attempted, no "
            "performance fabricated."
        ),
    }
    # NOTE: message_artifact_id / physical_traffic_id are optional (absent =
    # never produced). Schema requires only contract_version, status,
    # design_hash, resolved_fabric_hash, workload_id.
    del evaluation["message_artifact_id"]
    del evaluation["physical_traffic_id"]
    return bundle(
        "backend-unavailable",
        "Compiled design, no qualified simulator backend",
        "Preconditions met but no qualified BookSim producer exists, so the "
        "outcome is BACKEND_UNAVAILABLE with a reason and no metrics.",
        design=design,
        compilation=compiled_compilation(tag, dh),
        evaluation=evaluation,
        requirements=None,
        optimization=None,
    )


def fixture_evaluated_design() -> dict:
    tag = "mesh64-eval"
    design = base_design(tag)
    design["locked_derived"] = locked_block(tag)
    dh = design["design_hash"]
    perf_id = f"perf-{tag}-v1"
    return bundle(
        "evaluated-design",
        "Evaluated design (BookSim aggregate window + requirements)",
        "EVALUATED outcome with the single honest aggregate window, "
        "backend-present metrics only, producer identity, fidelity warning, "
        "and a RequirementReport bound to the performance result.",
        design=design,
        compilation=compiled_compilation(tag, dh),
        evaluation=evaluated_evaluation(tag, dh, perf_id),
        requirements=requirement_report(tag, dh, perf_id),
        optimization=None,
    )


def fixture_optimization_study() -> dict:
    tag = "mesh64-opt"
    design = base_design(tag)
    design["locked_derived"] = locked_block(tag)
    dh = design["design_hash"]
    perf_id = f"perf-{tag}-v1"
    widths = [64, 128, 256, 128, 256]
    concs = [4, 4, 4, 2, 2]
    lat = [141.2, 96.4, 78.9, 88.1, 71.5]
    area = [1.9, 2.6, 4.1, 3.4, 5.2]
    candidates = []
    for i in range(5):
        cid = f"cand-{i + 1:02d}"
        pareto = i in (1, 4)
        candidates.append(
            {
                "candidate_id": cid,
                "guided_patch": {
                    "link_width": widths[i],
                    "concentration": concs[i],
                },
                "locked_consequences": {
                    "routing": "DOR_XY",
                    "vc_count": 4,
                },
                "evaluation_ids": {
                    "design_hash": h(f"srota/design/{tag}/{cid}"),
                    "performance_result_id": f"perf-{tag}-{cid}-v1",
                },
                "objective_values": {
                    "avg_packet_latency_cycles": lat[i],
                    "link_area_um2": area[i],
                },
                "constraint_verdicts": {
                    "latency_ceiling": lat[i] <= 220,
                    "bandwidth_floor": True,
                },
                "pareto_member": pareto,
            }
        )
    optimization = {
        "contract_version": 1,
        "base_design_hash": dh,
        "definition": {
            "objectives": ["avg_packet_latency_cycles", "link_area_um2"],
            "constraints": ["latency_ceiling", "bandwidth_floor"],
            "method": "grid",
            "budget": {"max_candidates": 6},
            "seed": 7,
            "domain": {
                "link_width": [64, 128, 256],
                "concentration": [2, 4],
            },
        },
        "candidates": candidates,
        "pareto_ids": ["cand-02", "cand-05"],
        "selected_candidate_id": "cand-02",
        "selection_rationale": (
            "cand-02 is Pareto-optimal and keeps concentration 4 (base "
            "floorplan); cand-05 is faster but costs 2x link area."
        ),
    }
    return bundle(
        "optimization-study",
        "Optimization study over link_width x concentration",
        "Five GUIDED candidates (base request + patch), constraint verdicts, "
        "Pareto membership, and a selected candidate with rationale. LOCKED "
        "properties recompiled per candidate, shown as consequences.",
        design=design,
        compilation=compiled_compilation(tag, dh),
        evaluation=evaluated_evaluation(tag, dh, perf_id),
        requirements=requirement_report(tag, dh, perf_id),
        optimization=optimization,
    )


FIXTURES = {
    "compiled-mesh": fixture_compiled_mesh,
    "invalid-design": fixture_invalid_design,
    "backend-unavailable": fixture_backend_unavailable,
    "evaluated-design": fixture_evaluated_design,
    "optimization-study": fixture_optimization_study,
}


def main() -> None:
    for name, fn in FIXTURES.items():
        path = HERE / f"{name}.json"
        path.write_text(json.dumps(fn(), indent=2) + "\n")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()

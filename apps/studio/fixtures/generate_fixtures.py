#!/usr/bin/env python3
"""Deterministic fixture generator for Srota Studio (P4).

Builds the five Studio fixtures in apps/studio/fixtures/. Pure stdlib data
construction — no engine imports (Studio consumes contract views only).

REALIZABILITY (P4 addendum): every semantic value projects from real engine
semantics, not invented vocabulary. Values are mirrored from the frozen
engine authorities listed below; `scripts/validate_fixtures.py` re-checks
them as a gate so an impossible product cannot creep back in:

  * ModelFamily          model/compile_model.py::ModelFamily
  * AgentKind            model/compile_model.py::AgentKind
  * QoSClass             model/compile_model.py::QoSClass
  * TopologyFamily       model/compile_model.py::TopologyFamily
  * ServingMode          model/compile_model.py::ServingMode
  * arbitration aliases  model/router_behavior.py::_ARBITRATION_ALIASES
  * rcu_enabled=True     model/resolved_fabric.py refuses (UNSUPPORTED);
                         fixtures therefore use False
  * semantics version    model/compile_model.py::COMPILER_SEMANTICS_VERSION = 2
  * obligation methods   verification/certificate.py real method strings
  * artifact hash keys   model/resolved_bundle.py::root_hashes
  * DOR_XY route class   core/route_artifact.py::DOR_XY_DEFINITION
  * link area metric     reports/reports.py::estimate_fabric_area (links_mm2)
  * sizing               model/topology_artifact.py::materialize_family
                         (radix pins k; k*k*concentration seats must cover
                          the full agent count)

Request projection (verified against the real compiler, not assumed): the
DesignView does not carry E4 dependencies or E1 collectives, so each design
below projects the canonical P1A mesh_dense_64 request that carries them:

    dependencies: prefill-attn -> prefill-ffn (blocking)
    collectives:  allreduce, group_size 8

With radix 5 / concentration 4 / link_width 128 over 78 agents that request
COMPILES (10/10 obligations PASS, vc_count 1, 600 route entries); with
radix 3 the same request is refused UNSUPPORTED (36 seats < 78 agents).
Every obligation evidence value below was read from that engine run.

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

# Real certifier method strings (verification/certificate.py).
METHODS = {
    "TOPOLOGY_CONNECTED": "undirected-bfs/v1",
    "ATTACHMENT_COMPLETE": "attachment.validate_against/v1",
    "ADDRESS_DECODE_VALID": "address_decode.validate_against/v1",
    "ROUTE_COMPLETE": "entry-coverage/v1",
    "ROUTE_LEGAL": "route.validate_against/v1",
    "VC_ASSIGNMENT_VALID": "vc.validate_against/v1",
    "DEADLOCK_FREE": "channel-vc-cdg/v1",
    "MAPPING_VALID": "mapping-attachment-seam/v1",
    "PACKET_FORMAT_VALID": "packet_format.validate_against/v1",
    "FABRIC_DAG_VALID": "bundle.revalidate/v1",
}

# ── realizable instance constants ────────────────────────────────────────────
# Dense-transformer 64-NPU request (mirrors model/presets.py::llama70b_tp64
# plus the PRD §4.1 nic/peripheral agent kinds).
AGENTS = [
    {"kind": "compute_tile", "count": 64},
    {"kind": "hbm_controller", "count": 8},
    {"kind": "nic", "count": 2},
    {"kind": "peripheral", "count": 4},
]
ENDPOINT_COUNT = sum(a["count"] for a in AGENTS)  # 78
WORLD_SIZE = 64  # tp × pp × ep × dp == compute_tile count

# GUIDED knobs: radix 5 pins k=5 → 25 routers × concentration 4 = 100 seats
# ≥ 78 agents (materialize_family). link_width 128 bits.
RADIX = 5
CONCENTRATION = 4
LINK_WIDTH = 128
GRID_K = RADIX
ROUTER_COUNT = GRID_K * GRID_K  # 25
DIRECTED_CHANNELS = 2 * 2 * GRID_K * (GRID_K - 1)  # 80
ROUTE_ENTRIES = ROUTER_COUNT * (ROUTER_COUNT - 1)  # 1 class × n × (n-1) = 600
VC_COUNT = 1  # no dependency cycles / one multi-rank collective → floor 1
ROUTING = "DOR_XY"
TURN_RESTRICTIONS = ["no_negative_dimension_turns"]


def h(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()[:16]


def base_design(tag: str, **over) -> dict:
    d = {
        "contract_version": 1,
        "design_hash": h(f"srota/design/{tag}"),
        "schema_version": 2,
        "compiler_semantics_version": 2,
        "workload": {
            "model_family": "dense_transformer",
            "model_name": "LLaMA-70B",
            "parallelism": {"tp": 64, "pp": 1, "ep": 1, "dp": 1},
            "serving_mode": "mixed",
        },
        # QoS classes are the real enum; traffic_class is null exactly as the
        # current v2 requirement authority carries it (P1C v3 adds identity).
        "requirements": [
            {
                "traffic_class": None,
                "qos_class": "latency_critical",
                "latency_ceiling_cycles": 220,
                "bandwidth_floor_gbps": None,
                "binding": True,
            },
            {
                "traffic_class": None,
                "qos_class": "bandwidth",
                "latency_ceiling_cycles": None,
                "bandwidth_floor_gbps": 100,
                "binding": True,
            },
            {
                "traffic_class": None,
                "qos_class": "best_effort",
                "latency_ceiling_cycles": None,
                "bandwidth_floor_gbps": None,
                "binding": False,
            },
        ],
        "agents": [dict(a) for a in AGENTS],
        "noc_guided": {
            "topology_family": "mesh",
            "radix": RADIX,
            "concentration": CONCENTRATION,
            "link_width": LINK_WIDTH,
            "rcu_enabled": False,  # True is refused by the compiler (UNSUPPORTED)
            "arbitration": "round_robin",
        },
    }
    d.update(over)
    return d


def locked_block(overall: str = "PASS") -> dict:
    return {
        "routing": ROUTING,
        "vc_count": VC_COUNT,
        "turn_restrictions": list(TURN_RESTRICTIONS),
        "certificate_overall": overall,
    }


def bundle_hashes(tag: str) -> dict:
    """Real resolve-bundle children (resolved_bundle.py::root_hashes keys)."""
    return {
        "fabric_hash": h(f"srota/art/{tag}/fabric"),
        "mapping_hash": h(f"srota/art/{tag}/mapping"),
        "topology_hash": h(f"srota/art/{tag}/topology"),
        "attachment_hash": h(f"srota/art/{tag}/attachment"),
        "router_route_hash": h(f"srota/art/{tag}/router_route"),
        "resolved_route_hash": h(f"srota/art/{tag}/resolved_route"),
        "vc_assignment_hash": h(f"srota/art/{tag}/vc_assignment"),
        "packet_format_hash": h(f"srota/art/{tag}/packet_format"),
        "router_behavior_hash": h(f"srota/art/{tag}/router_behavior"),
        "address_decode_hash": h(f"srota/art/{tag}/address_decode"),
    }


def obligation_evidence(ob: str, tag: str) -> dict:
    """Real evidence keys per obligation runner (certificate.py)."""
    if ob == "TOPOLOGY_CONNECTED":
        return {"routers": ROUTER_COUNT,
                "directed_channels": DIRECTED_CHANNELS, "components": 1}
    if ob == "ATTACHMENT_COMPLETE":
        return {"endpoints": ENDPOINT_COUNT}
    if ob == "ADDRESS_DECODE_VALID":
        return {"entries": 0}
    if ob == "ROUTE_COMPLETE":
        return {"routing_classes": [ROUTING], "routers": ROUTER_COUNT,
                "expected_entries": ROUTE_ENTRIES, "entries": ROUTE_ENTRIES}
    if ob == "ROUTE_LEGAL":
        return {"routing_classes": [ROUTING]}
    if ob == "VC_ASSIGNMENT_VALID":
        return {"vc_count": VC_COUNT,
                "vc_to_routing_class": [[0, ROUTING]]}
    if ob == "DEADLOCK_FREE":
        return {"vc_count": VC_COUNT, "routing_classes": [ROUTING],
                "escape_vcs": [], "node_count": DIRECTED_CHANNELS,
                "edge_count": 124,
                "route_realization": "v2_channel_id",
                "cdg_route_classes": [ROUTING],
                "acyclic": True, "sccs_gt_1": 0}
    if ob == "MAPPING_VALID":
        return {"placements": WORLD_SIZE}
    if ob == "PACKET_FORMAT_VALID":
        return {"flit_width_bits": LINK_WIDTH, "vc_count": VC_COUNT}
    if ob == "FABRIC_DAG_VALID":
        return bundle_hashes(tag)
    return {"digest": digest(f"srota/evidence/{tag}/{ob}")}


def obligations_all_pass(tag: str) -> list[dict]:
    return [
        {
            "obligation": ob,
            "status": "PASS",
            "method": METHODS[ob],
            "evidence": obligation_evidence(ob, tag),
        }
        for ob in OBLIGATIONS
    ]


def compiled_compilation(tag: str, design_hash: str) -> dict:
    return {
        "contract_version": 1,
        "status": "COMPILED",
        "design_hash": design_hash,
        "compiler_semantics_version": 2,
        "resolved_fabric_hash": h(f"srota/fabric/{tag}"),
        "certificate_id": h(f"srota/cert/{tag}"),
        "certificate_overall": "PASS",
        "obligations": obligations_all_pass(tag),
        "artifact_hashes": bundle_hashes(tag),
        "error": None,
    }


def evaluated_evaluation(tag: str, design_hash: str, perf_id: str) -> dict:
    return {
        "contract_version": 1,
        "status": "EVALUATED",
        "design_hash": design_hash,
        "resolved_fabric_hash": h(f"srota/fabric/{tag}"),
        "workload_id": h(f"srota/workload/{tag}"),
        "message_artifact_id": h(f"srota/messages/{tag}/v2"),
        "physical_traffic_id": h(f"srota/traffic/{tag}/v2"),
        "backend_producer": {
            "backend": "booksim2-fork",
            "producer_identity": (
                "binary sha256:"
                + hashlib.sha256(f"srota/booksim-binary/{tag}".encode()).hexdigest()
                + " transport=SUPERVISED_PROCESS revision=ec747ffe"
            ),
            "config_hash": h(f"srota/simcfg/{tag}"),
            "input_hash": h(f"srota/siminput/{tag}"),
        },
        "evidence": {
            "raw_evidence_digest": h(f"srota/rawev/{tag}"),
            "stats_digest": h(f"srota/stats/{tag}"),
        },
        "performance_result_id": perf_id,
        "network_traffic_window": {
            "window_cycles": 50000,
            "wall_time_ns": None,
            "cycles_only": True,
        },
        # BookSim-class aggregate counts only. No wall-time, no per-operation
        # latency, no Gbps (cycles-only window has no valid clock).
        "metrics": {
            "packets_injected": 128000,
            "packets_completed": 128000,
            "flits_completed": 512000,
            "avg_packet_latency_cycles": 96.4,
            "sustained_throughput_flits_per_cycle": 10.24,
        },
        "fidelity_warning": (
            "Cycle-approximate BookSim-class model. Cycles only — no valid "
            "network clock established, so no wall-time or Gbps authority. "
            "Single aggregate NETWORK_TRAFFIC_WINDOW; never per-operation "
            "latency."
        ),
        "reason": None,
    }


def requirement_report(tag: str, design_hash: str, perf_id: str) -> dict:
    authority = "performance/result.py::build_performance_result"
    return {
        "contract_version": 1,
        "design_hash": design_hash,
        "performance_result_id": perf_id,
        "entries": [
            {
                "requirement_index": 0,
                "traffic_class": None,
                "qos_class": "latency_critical",
                "verdict": "SATISFIED",
                "binding": True,
                "required": 220,
                "measured": 96.4,
                "metric_authority": authority,
                "performance_result_id": perf_id,
                "reason": "avg_packet_latency_cycles 96.4 <= ceiling 220",
            },
            {
                "requirement_index": 1,
                "traffic_class": None,
                "qos_class": "bandwidth",
                "verdict": "UNMEASURABLE",
                "binding": True,
                "required": 100,
                "measured": None,
                "metric_authority": authority,
                "performance_result_id": perf_id,
                "reason": (
                    "bandwidth_floor_gbps 100 requires a valid network clock; "
                    "the aggregate window is cycles-only, so Gbps is not "
                    "derivable. Binding + UNMEASURABLE never passes."
                ),
            },
            {
                "requirement_index": 2,
                "traffic_class": None,
                "qos_class": "best_effort",
                "verdict": "NOT_APPLICABLE",
                "binding": False,
                "required": None,
                "measured": None,
                "metric_authority": authority,
                "performance_result_id": perf_id,
                "reason": "non-binding best-effort class carries no threshold",
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
    design["locked_derived"] = locked_block()
    dh = design["design_hash"]
    return bundle(
        "compiled-mesh",
        "Compiled 5x5 mesh · 64 compute tiles + 8 HBM (dense_transformer)",
        "Fresh COMPILED design (DOR_XY, VC count 1). All 10 obligations PASS. "
        "No evaluation has been run yet, so Evaluate shows NOT_RUN.",
        design=design,
        compilation=compiled_compilation(tag, dh),
        evaluation=None,
        requirements=None,
        optimization=None,
    )


def fixture_invalid_design() -> dict:
    tag = "bad-radix"
    design = base_design(tag)
    # Realizable GUIDED edit that the engine refuses at materialization:
    # radix 3 pins k=3 → 3*3 seats/router-conc 4 = 36 seats < 78 agents.
    design["noc_guided"] = {
        "topology_family": "mesh",
        "radix": 3,
        "concentration": CONCENTRATION,
        "link_width": LINK_WIDTH,
        "rcu_enabled": False,
        "arbitration": "round_robin",
    }
    design["locked_derived"] = None  # never compiled
    seats = 3 * 3 * CONCENTRATION
    error = (
        f"radix 3 with concentration {CONCENTRATION} provides "
        f"{seats} seats but {ENDPOINT_COUNT} agents must attach"
    )
    # Engine-typed refusal: no bundle, no certificate, therefore no
    # obligation list and no resolved fabric hash. (The engine maps this
    # materialization failure to UNSUPPORTED — typed refusal — not INVALID;
    # INVALID is reserved for a certificate that fails its proof.)
    compilation = {
        "contract_version": 1,
        "status": "UNSUPPORTED",
        "design_hash": design["design_hash"],
        "compiler_semantics_version": 2,
        "error": error,
    }
    return bundle(
        "invalid-design",
        "Refused design (radix 3 cannot seat 78 agents)",
        "Engine-typed UNSUPPORTED refusal: radix 3 pins k=3, so 36 seats "
        "cannot cover 78 agents. No bundle, no certificate, no obligation "
        "list, no resolved fabric hash.",
        design=design,
        compilation=compilation,
        evaluation=None,
        requirements=None,
        optimization=None,
    )


def fixture_backend_unavailable() -> dict:
    tag = "mesh64-nobe"
    design = base_design(tag)
    design["locked_derived"] = locked_block()
    dh = design["design_hash"]
    evaluation = {
        "contract_version": 1,
        "status": "BACKEND_UNAVAILABLE",
        "design_hash": dh,
        "resolved_fabric_hash": h(f"srota/fabric/{tag}"),
        "workload_id": h(f"srota/workload/{tag}"),
        "backend_producer": None,
        "evidence": None,
        "performance_result_id": None,
        "network_traffic_window": None,
        "metrics": None,
        "fidelity_warning": None,
        "reason": (
            "No qualified BookSim producer on this host (qualification binds "
            "the exact binary digest + source revision). Preconditions met "
            "(COMPILED + certificate PASS); no backend work attempted, no "
            "performance fabricated."
        ),
    }
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
    design["locked_derived"] = locked_block()
    dh = design["design_hash"]
    perf_id = h(f"srota/perf/{tag}/v1")
    return bundle(
        "evaluated-design",
        "Evaluated design (BookSim aggregate window + requirement verdicts)",
        "EVALUATED outcome with the single honest aggregate window, "
        "backend-present metrics only, producer identity, fidelity warning, "
        "and a RequirementReport bound to the performance result. The "
        "bandwidth floor is UNMEASURABLE (cycles-only window, no valid "
        "clock) and is reported as such.",
        design=design,
        compilation=compiled_compilation(tag, dh),
        evaluation=evaluated_evaluation(tag, dh, perf_id),
        requirements=requirement_report(tag, dh, perf_id),
        optimization=None,
    )


def fixture_optimization_study() -> dict:
    tag = "mesh64-opt"
    design = base_design(tag)
    design["locked_derived"] = locked_block()
    dh = design["design_hash"]
    perf_id = h(f"srota/perf/{tag}/v1")

    # Objectives are engine-real metrics: avg_packet_latency_cycles (BookSim
    # aggregate) and links_mm2 (reports.py::estimate_fabric_area).
    #
    #   id      link_width  conc  latency  links_mm2  pareto
    #   cand-01 64          4     141.2    0.42       yes (min area)
    #   cand-02 128         4      96.4    0.84       yes (base config)
    #   cand-03 128         8     112.0    0.84       dominated by cand-02
    #   cand-04 128         2      88.1    1.12       yes
    #   cand-05 256         4      78.9    1.68       yes
    #   cand-06 256         2      71.5    2.24       yes (min latency,
    #                                                    over area budget)
    rows = [
        (64, 4, 141.2, 0.42, True),
        (128, 4, 96.4, 0.84, True),
        (128, 8, 112.0, 0.84, False),
        (128, 2, 88.1, 1.12, True),
        (256, 4, 78.9, 1.68, True),
        (256, 2, 71.5, 2.24, True),
    ]
    candidates = []
    for i, (width, conc, lat, links, pareto) in enumerate(rows):
        cid = f"cand-{i + 1:02d}"
        candidates.append(
            {
                "candidate_id": cid,
                "guided_patch": {"link_width": width, "concentration": conc},
                # LOCKED properties are recompiled per candidate and never
                # searched; GUIDED patches cannot change them.
                "locked_consequences": {"routing": ROUTING, "vc_count": VC_COUNT},
                "evaluation_ids": {
                    "design_hash": h(f"srota/design/{tag}/{cid}"),
                    "performance_result_id": h(f"srota/perf/{tag}/{cid}/v1"),
                },
                "objective_values": {
                    "avg_packet_latency_cycles": lat,
                    "links_mm2": links,
                },
                "constraint_verdicts": {
                    "latency_ceiling": lat <= 220,
                    "link_area_budget": links <= 2.0,
                },
                "pareto_member": pareto,
            }
        )
    optimization = {
        "contract_version": 1,
        "base_design_hash": dh,
        "definition": {
            "objectives": ["avg_packet_latency_cycles", "links_mm2"],
            "constraints": ["latency_ceiling", "link_area_budget"],
            "method": "grid",
            "budget": {"max_candidates": 6},
            "seed": 7,
            "domain": {
                "link_width": [64, 128, 256],
                "concentration": [2, 4, 8],
            },
        },
        "candidates": candidates,
        "pareto_ids": [
            c["candidate_id"] for c in candidates if c["pareto_member"]
        ],
        "selected_candidate_id": "cand-02",
        "selection_rationale": (
            "cand-02 is the base GUIDED config (link_width 128, "
            "concentration 4) and sits on the Pareto frontier: it keeps the "
            "5x5 mesh floorplan, meets the latency ceiling, and costs less "
            "than half the link area of the faster cand-06."
        ),
    }
    return bundle(
        "optimization-study",
        "Optimization study over link_width × concentration",
        "Six GUIDED candidates (base request + patch), constraint verdicts, "
        "Pareto membership (cand-03 dominated), and selected cand-02 with "
        "rationale. LOCKED properties recompiled per candidate, shown as "
        "consequences.",
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

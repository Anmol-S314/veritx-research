#!/usr/bin/env python3
"""Generate docs/product/feature-reclamation-registry.yaml.

The audit rows live here as data and are emitted with yaml.safe_dump, so
the machine-readable registry cannot be malformed by hand-editing prose.
Run:  python3 scripts/gen_feature_reclamation.py [--check]
"""
from __future__ import annotations
import sys
from pathlib import Path
import yaml

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "product" / "feature-reclamation-registry.yaml"

HEADER = """\
# feature-reclamation-registry.yaml  (GENERATED — do not hand-edit prose)
#
# Regenerate: python3 scripts/gen_feature_reclamation.py
#
# WHAT THIS FILE IS NOT
#
#   It is NOT `capability-registry.yaml` and does not replace it. They answer
#   different questions:
#
#     capability-registry.yaml      what the CURRENT canonical product can
#                                   truthfully do today (Gate 4)
#     feature-reclamation-registry  what historically EXISTED anywhere in
#                                   VERITX/SROTA history, and what must be
#                                   reclaimed, canonicalized, rejected or
#                                   rebuilt
#
#   A `NOT_AVAILABLE` row in the capability registry does NOT prove the
#   capability should be absent. Every current NOT_AVAILABLE /
#   FUTURE_CONTRACT / ENGINE_ONLY / omitted capability was searched in
#   history before being classified here.
#
# HOW THIS WAS PRODUCED
#
#   Sources: the current integration branch/worktree; the existing migration
#   ledger `veritx_dse/application/inventory.py` (which already classifies
#   PATHS as AUTHORITATIVE / MIGRATE / LEGACY_INTERNAL / TEST_ONLY / DELETE);
#   the Gate 1-8 planning corpus; 84 branches searched with git ls-tree and
#   git grep. Capability was located in CODE AND TESTS, never inferred from
#   branch names. `third_party/` is kept separate from SROTA capability: a
#   BookSim network backend existing is NOT canonical product exposure.
#
# COVERAGE: PARTIAL — see `coverage:`. Domains under `not_yet_audited` have
# NOT been searched in history and are NOT classified.
"""

CAPS = [
 dict(id="FRA-TOPO-001", capability="broad topology family representation",
  domain="topology families",
  historical_source="BookSim network backends + t3 BookSim configs",
  exact_files=["third_party/booksim2/src/networks/ (flatfly_onchip, dragonfly, qtree, tree4, fattree, anynet, mesh, torus, ...)",
   "tracks/t3-topology/configs/{anynet16,cmesh16,dragonfly16,fattree16,flatfly16,fly4,ftree,mesh4x4,qtree16,torus4x4,tree4}.cfg"],
  tests="third_party BookSim self-tests; no SROTA canonical test",
  historical_maturity="IMPLEMENTED",
  current_canonical_representation="TopologyFamily = MESH | TORUS | CONCENTRATED_MESH | GEC | FAT_TREE (compile_model.py:597) — 5 declarable values. MaterializedFamily = MESH | TORUS | RING | CONCENTRATED_MESH (topology_artifact.py:55) — 4 materializable values. GEC and FAT_TREE are declarable but NOT materializable; RING is materializable but NOT declarable.",
  current_product_wiring="FAB-001/FAB-002/FAB-003/FAB-004",
  classification="NEEDS_CANONICALIZATION", priority="P1",
  required_action="Decide which historical families SROTA claims. The current tree's own two enumerations disagree (declarable-but-not-materializable GEC/FAT_TREE; materializable-but-not-declarable RING); that internal inconsistency must be resolved before any family is added.",
  notes="BookSim breadth is NOT canonical exposure."),

 dict(id="FRA-TOPO-002", capability="custom / arbitrary topology representation",
  domain="custom/arbitrary topology",
  historical_source="AnyNet graphs; MILP-generated .anynet output",
  exact_files=["tracks/t3-topology/configs/anynet16.cfg",
   "third_party/booksim2/src/networks/anynet.cpp",
   "veritx_dse/synthesis/milp_topology_v2.py (emits <out>.anynet)",
   "veritx_dse/tools/deadlock_routing.py (consumes .anynet)"],
  tests="no canonical declaration test",
  historical_maturity="IMPLEMENTED",
  current_canonical_representation="ABSENT as intent. CAPABILITY-MATRIX.md §18 records AnyNet as exactly two compiler-owned capabilities — ROUTE-002 canonical route algorithm and ROUTE-003 backend projection — and states: 'Neither is user intent. There is no AnyNet checkbox.' FAB-007 'custom / hierarchical topology' is NOT_AVAILABLE / NO_CONTRACT.",
  current_product_wiring="FAB-007 NOT_AVAILABLE",
  classification="NEEDS_CANONICALIZATION", priority="P0",
  required_action="The routing and projection halves already exist and are canonical; only the DECLARATION half is missing. Give it a contract (FAB-007's NO_CONTRACT is the gap, not the machinery).",
  notes="The case this audit was commissioned to find: the corpus is coherent while incomplete. Planning did not reject arbitrary topology; it recorded that the two halves exist and that there is no user intent for it."),

 dict(id="FRA-SYNTH-001", capability="traffic-weighted topology synthesis (MILP/TMCF)",
  domain="topology synthesis",
  historical_source="NetSmith-method synthesizer",
  exact_files=["veritx_dse/synthesis/milp_topology_v2.py (solve_tmcf, sa_synthesize, priced_geodesic, interposer_xy, set_costs, is_bridge, base_mesh, valid_links)",
   "tracks/t3-topology/scripts/archive/milp_topology.py",
   "tracks/t3-topology/scripts/archive/milp_exactness.py",
   "tracks/t3-topology/scripts/archive/milp_exactness_norm.py"],
  tests="none dedicated (test_topology_artifact.py is unrelated)",
  historical_maturity="IMPLEMENTED",
  current_canonical_representation="ABSENT",
  current_product_wiring="none",
  classification="NEEDS_CANONICALIZATION", priority="P0",
  required_action="Reclaim as a canonical synthesis capability or record a dated refusal. It generates the topology GRAPH from a traffic matrix under radix, link-length and diameter budgets with a physical layout model (grid/interposer + jitter) and wire/pipe cost pricing. Planning deferred 'Bayes/MILP' as SEARCH METHODS over a fixed space (INTENT-DESIGN-SPACE.md:512) and separately acknowledged 'a future compiler that synthesises topology from requirements is a new compiler-guidance contract and is not assumed' (INTENT-REQUIREMENTS.md:384) — the same return condition stated twice.",
  notes="inventory.py already classifies veritx_dse/synthesis/ as LEGACY_INTERNAL with replacement 'none in Wave C (synthesis science is Wave E)'. Wave E became the performance model, so the deferral landed nowhere. Documented deferral, NOT accidental erasure."),

 dict(id="FRA-SYNTH-002", capability="Bayesian-optimization topology search",
  domain="topology synthesis",
  historical_source="bo_synthesizer.py",
  exact_files=["veritx_dse/synthesis/bo_synthesizer.py",
   "veritx_dse/cli/cli.py (cmd_synthesize_bo)"],
  tests="none dedicated", historical_maturity="IMPLEMENTED",
  current_canonical_representation="ABSENT",
  current_product_wiring="legacy CLI only (PF-D15 marks REMOVE)",
  classification="NEEDS_CANONICALIZATION", priority="P1",
  required_action="Same disposition as FRA-SYNTH-001."),

 dict(id="FRA-SYNTH-003", capability="iterative (RHO/GRPO) topology search",
  domain="topology synthesis",
  historical_source="iterative_synthesizer.py",
  exact_files=["veritx_dse/synthesis/iterative_synthesizer.py",
   "veritx_dse/cli/cli.py (cmd_synthesize_iterative)"],
  tests="none dedicated", historical_maturity="IMPLEMENTED",
  current_canonical_representation="ABSENT",
  current_product_wiring="legacy CLI only",
  classification="NEEDS_CANONICALIZATION", priority="P1",
  required_action="Same disposition as FRA-SYNTH-001."),

 dict(id="FRA-SYNTH-004", capability="event-driven topology objective scoring",
  domain="topology synthesis",
  historical_source="event_objective.py — scores a candidate topology from the event timeline",
  exact_files=["veritx_dse/synthesis/event_objective.py",
   "tracks/t3-topology/dse/scripts/event_objective.py"],
  tests="none dedicated", historical_maturity="EXPERIMENTAL",
  current_canonical_representation="ABSENT", current_product_wiring="none",
  classification="RESEARCH_ONLY", priority="P2",
  required_action="Keep as research. It couples topology scoring to a temporal model (Wave E), so it cannot be reclaimed before the temporal layer is canonical."),

 dict(id="FRA-SYNTH-005", capability="topology physical constraints (radix, link length, diameter, layout, wire/pipe pricing)",
  domain="topology physical constraints",
  historical_source="milp_topology_v2 layout + cost model",
  exact_files=["veritx_dse/synthesis/milp_topology_v2.py (grid_xy, interposer_xy, valid_links, set_costs, _edge_len, priced_geodesic)"],
  tests="none dedicated", historical_maturity="IMPLEMENTED",
  current_canonical_representation="ABSENT (concentration exists; no link-length or diameter budget)",
  current_product_wiring="none",
  classification="NEEDS_CANONICALIZATION", priority="P1",
  required_action="These constraints are what make a generated topology physically meaningful. Decide whether they belong in canonical intent or in a synthesis-only contract; do not silently drop them.",
  notes="PIPE_COST / WIRE_COST are module constants reused by event_objective.py, so the pricing model has at least one live consumer outside the synthesizer."),

 dict(id="FRA-OPT-001", capability="topology as an optimization variable",
  domain="topology as optimization dimension",
  historical_source="synthesis MILP/SA emits a topology as its OUTPUT",
  exact_files=["veritx_dse/synthesis/milp_topology_v2.py"],
  tests="none", historical_maturity="IMPLEMENTED",
  current_canonical_representation="ABSENT. The canonical design space enumerates topology_family over a finite set (INTENT-DESIGN-SPACE.md); it never GENERATES a graph. OPT-002 'expert typed design space' is WIRED but bounded by DomainParam finite value tuples.",
  current_product_wiring="none",
  classification="NEEDS_CANONICALIZATION", priority="P0",
  required_action="Decide whether topology generation is in the product thesis. If it is, it needs a canonical candidate representation that is NOT a DomainParam (a generated graph has no finite value tuple) plus a candidate-identity rule.",
  notes="Distinct from FRA-SYNTH-001: that is the generator, this is whether a GENERATED topology can be a study candidate at all."),

 dict(id="FRA-TOPO-003", capability="multiplane fabric",
  domain="multiplane",
  historical_source="t3 BookSim multiplane configs",
  exact_files=["tracks/t3-topology/configs/plane_control.cfg",
   "tracks/t3-topology/configs/plane_data.cfg",
   "tracks/t3-topology/configs/plane_shared.cfg",
   "tracks/t3-topology/configs/plane_cmesh.cfg",
   "tracks/t3-topology/configs/plane_cmesh_ctrl.cfg"],
  tests="none", historical_maturity="EXPERIMENTAL",
  current_canonical_representation="ABSENT",
  current_product_wiring="FAB-005 multiplane NOT_AVAILABLE / FUTURE_CONTRACT",
  classification="RESEARCH_ONLY", priority="P2",
  required_action="Keep as research until a canonical multiplane contract exists. The configs are BookSim experiments, not a canonical derivation, and no code produces them.",
  notes="The word 'multiplane' appears in NO SROTA source file. The evidence is five BookSim config names only, which is why maturity is EXPERIMENTAL and not IMPLEMENTED."),

 dict(id="FRA-ROUTE-001", capability="dimension-order routing (DOR / DOR-XY)",
  domain="routing algorithms",
  historical_source="canonical compiler",
  exact_files=["veritx_dse/model/routing.py (derive_route, _CERTIFIED_FAMILIES)",
   "veritx_dse/model/routing_materialize.py (DOR_XY family)"],
  tests="test_routing_realization.py, test_route_artifact.py",
  historical_maturity="SEALED",
  current_canonical_representation="CANONICAL — RouteArtifact with RoutingClassDefinition(id='DOR_XY')",
  current_product_wiring="ROUTE-001 WIRED",
  classification="CANONICAL_NOW", priority="P3", required_action="none"),

 dict(id="FRA-ROUTE-002", capability="BookSim AnyNet Dijkstra routing",
  domain="routing algorithms",
  historical_source="BookSim backend",
  exact_files=["third_party/booksim2/src/networks/anynet.cpp",
   "veritx_dse/core/route_artifact.py (_anynet_replica_first_hops replicates AnyNet::route() tie-break semantics exactly)"],
  tests="test_route_artifact.py", historical_maturity="SEALED",
  current_canonical_representation="ROUTE-003 (AnyNet backend projection); COND-CANONICAL-ROUTE-PRESENT",
  current_product_wiring="ROUTE-003; CAP-ENV-BOOKSIM-ANYNET-V1",
  classification="CANONICAL_NOW", priority="P3", required_action="none"),

 dict(id="FRA-ROUTE-003", capability="adaptive routing (MinAdapt / UGAL / congestion-aware)",
  domain="routing algorithms",
  historical_source="routing_policy vocabulary; BookSim adaptive backends",
  exact_files=["veritx_dse/model/routing_policy.py — a full RoutingPolicyDefinition artifact (PathMode, DecisionScope, CandidateMode, SelectionLocus, RandomnessMode, RoutingStateKind, RuntimeObservation, RoutingResourceRoleKind incl. ADAPTIVE, DeadlockProofObligation), content-addressed",
   "veritx_dse/model/router_behavior.py — 'Explicitly absent: escape/adaptive priority, routing-action priority, congestion thresholds, MinAdapt/UGAL arbitration, hidden QoS priority'"],
  tests="test_routing_policy.py (depth not audited)",
  historical_maturity="IMPLEMENTED",
  current_canonical_representation="PARTIAL. The routing-policy VOCABULARY exists and models adaptive routing; the canonical compile path derives DOR_XY only. The router-behavior artifact excludes MinAdapt/UGAL BY DESIGN.",
  current_product_wiring="ROUTE-009 adaptive NOT_AVAILABLE / FUTURE_CONTRACT",
  classification="NEEDS_CANONICALIZATION", priority="P1",
  required_action="Resolve the internal tension: a canonical adaptive-policy vocabulary exists while the behavior artifact states adaptive arbitration is absent. Decide which is authoritative and make the registry row match.",
  notes="Do NOT classify REJECTED_UNSOUND: the router_behavior exclusion is a stated scope boundary of that artifact, not a claim that adaptive routing is unsound."),

 dict(id="FRA-ROUTE-004", capability="min-max-load routing (MCLB / ILP)",
  domain="routing optimization",
  historical_source="CLI + deadlock tooling",
  exact_files=["veritx_dse/cli/cli.py", "veritx_dse/tools/deadlock_routing.py"],
  tests="none canonical", historical_maturity="EXPERIMENTAL",
  current_canonical_representation="ABSENT", current_product_wiring="none",
  classification="RESEARCH_ONLY", priority="P2",
  required_action="Audit depth not reached in this pass. It appears in a tool and a CLI command, not in a canonical derivation. Confirm before any promotion."),

 dict(id="FRA-ROUTE-005", capability="valiant / randomized routing",
  domain="routing algorithms",
  historical_source="unknown",
  exact_files=["veritx_dse/model/packet_format.py (single mention)"],
  tests="none", historical_maturity="CONCEPT_ONLY",
  current_canonical_representation="ABSENT",
  current_product_wiring="ROUTE-010 valiant NOT_AVAILABLE / FUTURE_CONTRACT",
  classification="RESEARCH_ONLY", priority="P3",
  required_action="One mention in packet_format.py is not an implementation. Do not promote on the strength of a keyword hit."),

 dict(id="FRA-ROUTE-006", capability="escape VC designation",
  domain="VC assignment",
  historical_source="canonical compiler",
  exact_files=["veritx_dse/model/vc_assignment.py", "veritx_dse/compiler/candidate_policy.py",
   "veritx_dse/backend/meshdor.py", "veritx_dse/backend/booksim.py"],
  tests="test_channel_vc_cdg.py, test_adaptive_escape.py",
  historical_maturity="SEALED",
  current_canonical_representation="CANONICAL — VCAssignmentArtifact carries escape_vcs",
  current_product_wiring="ROUTE-008 NOT_AVAILABLE / IMPLEMENTATION_GAP",
  classification="NEEDS_CANONICALIZATION", priority="P2",
  required_action="The artifact carries escape_vcs and the code is widespread, yet ROUTE-008 says IMPLEMENTATION_GAP. Determine whether the gap is product exposure or a real derivation gap, and correct whichever row is wrong."),

 dict(id="FRA-ROUTE-007", capability="RCU / in-network reduction",
  domain="RCU / in-network reduction",
  historical_source="none found", exact_files=[], tests="none",
  historical_maturity="ABSENT", current_canonical_representation="ABSENT",
  current_product_wiring="ROUTE-011 FUTURE_CONTRACT (removed from v4)",
  classification="REJECTED_UNSOUND", priority="P3",
  required_action="Confirmed absent in history: `rcu`/`RCU` matches ZERO SROTA source files on any branch. The Gate-5 removal was correct — there was never an implementation to remove, only an intent field.",
  notes="The cleanest REJECTED_UNSOUND in the audit: planning removed a control for a capability that never existed."),

 dict(id="FRA-WORK-001", capability="full workload operation vocabulary",
  domain="workload graph operation vocabulary",
  historical_source="Wave-D canonical workload graph",
  exact_files=["veritx_dse/workload/graph.py (KIND_COMPUTE, KIND_COLLECTIVE, KIND_P2P, KIND_MULTICAST, KIND_EXPERT_BEGIN, KIND_EXPERT_END, KIND_PIM_CHANNEL, KIND_PIM_END)",
   "veritx_dse/workload/canonical_graph.py",
   "veritx_dse/workload/{canonical,lowering,messages,migration,timeline}.py",
   "veritx_dse/backend/astra.py"],
  tests="workload tests present (depth not audited)",
  historical_maturity="SEALED",
  current_canonical_representation="TWO LAYERS, not one. Evaluation side: the 8-kind Wave-D graph, reachable via application/requests.py and fabric_evaluator.py. Design-intent side: WorkloadV3 carries `collectives` with only CollectiveKind = allreduce | allgather | reducescatter | broadcast | alltoall, plus DependencyGraph. So P2P, MULTICAST, EXPERT_DISPATCH/COMBINE and PIM are expressible downstream but NOT declarable as canonical Design intent.",
  current_product_wiring="WORK-001/WORK-002/WORK-004",
  classification="NEEDS_CANONICALIZATION", priority="P0",
  required_action="INTENT-WORKLOAD.md:122-129 reconciled the PHASE-9 grammar against Wave-D (P2P RENAMED_EQUIVALENT, MULTICAST EXACT_EQUIVALENT, EXPERT_BEGIN RENAMED_EQUIVALENT, PIM_CHANNEL/PIM_END PARTIAL_EQUIVALENT -> MEMORY). That reconciliation does NOT cover the WorkloadV3 -> Wave-D gap. Close it explicitly: either extend WorkloadV3 or record that Design intent is deliberately collective-only.",
  notes="Planning reconciled the OLD grammar; the audit found the CURRENT intent vocabulary is narrower than the canonical graph it must lower to. A new finding, not a restatement."),

 dict(id="FRA-WORK-002", capability="PIM (processing-in-memory) channel semantics",
  domain="PIM",
  historical_source="Wave-D + ASTRA",
  exact_files=["veritx_dse/workload/graph.py (KIND_PIM_CHANNEL, KIND_PIM_END, _PIM_CHANNEL_KEYS = {'channel'})",
   "veritx_dse/backend/astra.py"],
  tests="present (depth not audited)", historical_maturity="IMPLEMENTED",
  current_canonical_representation="PARTIAL. Present in the Wave-D graph and the ASTRA backend; absent from WorkloadV3 (Design intent). Planning records PIM_CHANNEL as PARTIAL_EQUIVALENT -> MEMORY (INTENT-WORKLOAD.md:128).",
  current_product_wiring="MEM-007 PIM NOT_AVAILABLE / LEGACY_ONLY",
  classification="NEEDS_CANONICALIZATION", priority="P1",
  required_action="LEGACY_ONLY understates it: PIM_CHANNEL is live in the Wave-D graph and the ASTRA backend, not merely a legacy grammar token. Reclassify or justify.",
  notes="Direct instance of the audit's critical rule — a NOT_AVAILABLE registry row whose historical evidence is stronger than the row implies."),

 dict(id="FRA-META-001", capability="capability introspection and path migration classification",
  domain="capability introspection",
  historical_source="Wave-C migration ledger",
  exact_files=["veritx_dse/application/inventory.py (LEDGER, ledger_table, VALID_CLASSIFICATIONS = AUTHORITATIVE | MIGRATE | LEGACY_INTERNAL | TEST_ONLY | DELETE)"],
  tests="ledger_table() asserts every row's classification is valid",
  historical_maturity="SEALED", current_canonical_representation="CANONICAL",
  current_product_wiring="application/inventory.py",
  classification="CANONICAL_NOW", priority="P3",
  required_action="This registry EXTENDS this vocabulary rather than inventing a parallel one. inventory.py classifies PATHS; feature-reclamation-registry classifies CAPABILITIES. Keep both."),

 dict(id="FRA-META-002", capability="control-plane operation surface",
  domain="agent/API/machine-readable surfaces",
  historical_source="SrotaControlPlane",
  exact_files=["veritx_dse/application/service.py",
   "veritx_dse/application/capabilities.py (operations: capabilities, validate, compile, plan, evaluate, run_study, compare, inspect, list_results, diagnose)",
   "veritx_dse/cli/service_cli.py", "veritx_dse/api.py"],
  tests="test_application_service.py and others", historical_maturity="SEALED",
  current_canonical_representation="CANONICAL (product/service.py + gateway/app.py)",
  current_product_wiring="WIRED",
  classification="CANONICAL_NOW", priority="P3",
  required_action="Depth not audited: the historical operation list must be diffed against the current product surface to find dropped operations. Not done in this pass."),
]

PROTECTED_BRANCHES = [
 ("integration/canonical", "carries veritx_dse/synthesis/{milp_topology_v2,bo_synthesizer,iterative_synthesizer,event_objective}.py"),
 ("main", "carries the same synthesis module"),
 ("prod/production-readiness", "carries the same synthesis module"),
 ("rebuild/live-product-flow", "carries the same synthesis module"),
 ("validation/b4-campaign", "carries milp_topology_v2.py"),
 ("longhaul/econ-test", "carries the same synthesis module"),
 ("local/serving-preflight-guard", "carries the same synthesis module"),
 ("github/audit/wave-f-parity-ledger", "Wave-F parity evidence"),
 ("github/audit/rt-final-optimization-truth", "adversarial optimization-truth suite (14 cases)"),
 ("github/audit/rt-final-optimization-truth-v2", "candidate status/reason in records"),
 ("github/audit/rt-final-reports", "evidence-only; never merge"),
 ("github/audit/rt-final-reports-v2", "evidence-only; never merge"),
 ("github/t3-rtl-noc-backup-20260814", "RTL/NoC backup"),
 ("github/t3-rtl-noc-backup-20260815", "RTL/NoC backup"),
 ("origin/reference/gec-wire-pricing", "GEC wire-pricing variant of gec.cpp"),
 ("origin/astrasim-manal", "ASTRA-Sim topology integration"),
 ("origin/updated-booksim", "BookSim fork with local changes"),
 ("github/epic/booksim-forward-port", "FabricArtifact/MappingArtifact binding"),
]


def build() -> dict:
    return {
        "version": 1,
        "schema": "srota/feature-reclamation-registry/v1",
        "narrative": "docs/product/FEATURE-RECLAMATION-AUDIT.md",
        "generated_by": "scripts/gen_feature_reclamation.py",
        "companion_registry": {
            "path": "docs/product/capability-registry.yaml",
            "relationship": "capability-registry states what the canonical product can do NOW; this registry states what historically existed and its disposition. Neither replaces the other.",
        },
        "vocabularies": {
            "historical_maturity": ["SEALED", "TESTED", "IMPLEMENTED",
                                    "EXPERIMENTAL", "CONCEPT_ONLY", "ABSENT"],
            "classification": ["CANONICAL_NOW", "RECLAIMABLE",
                               "NEEDS_CANONICALIZATION", "RESEARCH_ONLY",
                               "GENUINELY_NEW", "REJECTED_UNSOUND"],
            "priority": {
                "P0": "required for the core product thesis before major product implementation proceeds",
                "P1": "important existing capability that must be reclaimed before product seal",
                "P2": "valuable research/diagnostic capability",
                "P3": "historical/developer-only or optional",
            },
        },
        "coverage": {
            "status": "PARTIAL",
            "reason": "Domains under not_yet_audited were NOT searched in history and are NOT classified. This registry must not be read as 'everything else is absent'.",
            "audited_domains": sorted({c["domain"] for c in CAPS}),
            "not_yet_audited": [
                "traffic classes / virtual networks / QoS depth",
                "multicast implementation depth",
                "collective semantics depth",
                "MoE semantics depth",
                "memory-location semantics depth (REMOTE/CXL/STORAGE)",
                "Ramulator integration depth",
                "ASTRA-Sim / Chakra integration depth",
                "LLMServingSim depth",
                "multi-instance serving depth",
                "scheduling / batching / request traces depth",
                "temporal / system-performance model (Wave E)",
                "sensitivity / scaling analysis",
                "physical area estimates",
                "power estimates",
                "timing / Fmax estimates",
                "Timeloop / energy",
                "RTL generation",
                "Verilator",
                "UVM generation",
                "SVA / assertion generation",
                "RTL <-> simulator parity",
                "fault injection",
                "MTU / packetization",
                "packet / flit conservation",
                "backend qualification depth",
                "evidence / provenance depth",
                "signed / export artifacts",
                "immutable experiment / attempt lifecycle depth",
                "studies / comparison / comparability gates depth",
                "design-space enumeration depth",
                "multi-scenario optimization",
                "exhaustive vs budgeted completeness",
                "Pareto / selection policies depth",
                "candidate persistence / reopen verification",
                "workload-as-scenario-variable",
                "flow-class certification",
                "Studio surfaces depth",
                "chiplet / hotspot / multicast / HPC examples",
                "report generation",
            ],
        },
        "capabilities": CAPS,
        "branch_cleanup_rule": {
            "branches_deleted_or_modified": 0,
            "rule": "A branch may be archived ONLY after traceability exists: unique capability identified, canonical replacement identified, test replacement identified, retained commit/tag recorded. Branches holding the only implementation of a RECLAIMABLE or NEEDS_CANONICALIZATION capability MUST be retained.",
            "protected_branches": [
                {"branch": b, "why": w} for b, w in PROTECTED_BRANCHES],
            "proposed_for_archival": [],
            "archival_note": "None proposed: the audit is incomplete, so no capability has yet been shown to have a canonical + test replacement.",
        },
    }


def main(argv):
    doc = build()
    text = HEADER + "\n" + yaml.safe_dump(
        doc, sort_keys=False, allow_unicode=True, width=88, default_flow_style=False)
    if "--check" in argv:
        if not OUT.is_file() or OUT.read_text() != text:
            print("feature-reclamation-registry.yaml is STALE", file=sys.stderr)
            return 1
        print(f"registry current ({len(doc['capabilities'])} capabilities)")
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(REPO)} ({len(doc['capabilities'])} capabilities)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

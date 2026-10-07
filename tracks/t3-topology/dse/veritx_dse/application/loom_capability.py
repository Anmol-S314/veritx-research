"""veritx_dse.application.loom_capability — the ONE capability registry the
product UI is allowed to read.

Why this module exists
----------------------
The reference "Srota Loom" screenshots decide capability inside the view layer:
a topology selector lists families, a plane card says whether an artifact
exists, a simulation page offers a metric. Every one of those decisions is a
place where the UI can disagree with the compiler.

This module is the single seam. It answers three questions for the UI and
nothing else:

1. Which topology families can this compiler actually take, and how far does
   each one get? The answer is PROBED, not declared — it delegates to
   :mod:`veritx_dse.application.capability_truth`, which runs the real
   compiler, profile selector and execution handlers and reports the authority
   string for each stage.
2. Which capabilities exist only as a *name* — no compiler kind, no artifact,
   no backend profile? They are listed as ``NOT_IMPLEMENTED`` with the reason,
   so the UI refuses them by reading this table instead of guessing. The
   ``srota`` fabric is the motivating case: it is a working topology in the
   vendored BookSim (``third_party/booksim2/src/networks/srota.cpp``, verified
   executing with its own static CDG check) that has no entry in
   ``TopologyFamily``, no ``AUTHORABLE_INTENTS`` kind and no BookSim projection
   profile. A user cannot reach it today. Saying so here is the whole point.
3. What a capability's status MEANS, so "READY" is never rendered as though it
   were a pass/fail verdict.

It deliberately does NOT decide readiness for a concrete evaluation. That
belongs to ``EvaluationPlanner`` over a real canonical context, which
distinguishes ``support`` (can the backend represent this at all) from
``readiness`` (can it execute right now). This module carries that distinction
through to the UI rather than flattening it into one word.

Rationale: docs/decisions/modules/application.md
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

class CapabilityError(ValueError):
    """A capability row is internally inconsistent."""


# Capability status vocabulary. Deliberately NOT the same words as the
# reference product's UI, and deliberately not the backend's
# ``BackendReadiness`` enum: readiness is per-context and evaluated at plan
# time, whereas these are properties of the installed system.
CAPABILITY_STATUSES: tuple[str, ...] = (
    "READY",          # implemented, wired, and proven by a probe at this HEAD
    "PARTIAL",        # implemented and wired; the artifact carries less
    "BLOCKED",        # implemented; refuses on this input with a typed reason
    "UNSUPPORTED",    # declared out of scope by a sealed decision
    "NOT_IMPLEMENTED",  # does not exist: no code, no artifact, no endpoint
)

# The eight stages a design traverses, in order. A family that stops at stage N
# is usable up to N-1 and not beyond; the UI must not offer the later ones.
STAGE_ORDER: tuple[str, ...] = (
    "AUTHORABLE", "MATERIALIZABLE", "ROUTABLE", "VERIFIABLE",
    "PROJECTABLE", "EXECUTABLE", "QUALIFIED", "PRODUCT_WIRED",
)

# The stage at which each capability class becomes meaningful. Used to explain
# "READY" in words rather than leaving the word to stand alone.
_STAGE_MEANING: dict[str, str] = {
    "AUTHORABLE": "the compiler accepts this as design intent",
    "MATERIALIZABLE": "the compiler emits a TopologyArtifact for it",
    "ROUTABLE": "the compiler derives a RouteArtifact over it",
    "VERIFIABLE": "the compiler produces the full bundle to certify",
    "PROJECTABLE": "a BookSim profile renders it into an executable input",
    "EXECUTABLE": "an execution handler exists for the projection",
    "QUALIFIED": "that execution path carries a qualification profile",
    "PRODUCT_WIRED": "a shipped product preset normalizes to it",
}


@dataclass(frozen=True)
class Capability:
    """One capability, its status, and why.

    ``evidence_refs`` are the real paths that establish the row. An empty list
    on a READY row would mean the claim is unbacked, so the product view below
    refuses to emit one.

    ``blocked_at`` names the stage a family stopped at, using this module's
    ``STAGE_ORDER`` vocabulary. It is carried explicitly rather than recovered
    from ``reason``, because parsing prose for control flow is how a UI and its
    server drift apart.
    """

    id: str
    status: str
    reason: str
    required_inputs: tuple[str, ...] = ()
    backend: str | None = None
    qualification: str | None = None
    evidence_refs: tuple[str, ...] = ()
    blocked_at: str | None = None

    def __post_init__(self) -> None:
        # Normalise a bare string into a one-element path list.
        #
        # Without this, writing a source path as a plain string in the tables
        # below looks correct but silently iterates CHARACTER BY CHARACTER when
        # serialised, turning
        #   "third_party/booksim2/src/networks/srota.cpp"
        # into forty one-letter "paths". A single-character entry is therefore
        # refused here rather than shipped.
        refs: tuple[str, ...]
        if isinstance(self.evidence_refs, str):  # type: ignore[unreachable]
            refs = (self.evidence_refs,)
        else:
            refs = tuple(self.evidence_refs)
        for ref in refs:
            if len(ref) < 4 or "/" not in ref:
                raise CapabilityError(
                    f"{self.id}: evidence ref {ref!r} is not a path. Every "
                    f"entry must be a source path, which is what establishes "
                    f"the row.")
        object.__setattr__(self, "evidence_refs", refs)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "reason": self.reason,
            "required_inputs": list(self.required_inputs),
            "backend": self.backend,
            "qualification": self.qualification,
            "evidence_refs": list(self.evidence_refs),
            "blocked_at": self.blocked_at,
        }


# Capabilities that have a NAME in the codebase or the reference product but no
# implementation behind them in the product. Each is listed so the UI can refuse
# it by reading this table. None of these is inferable from an artifact, which
# is precisely why they are written down.
# Each entry is (capability id, reason, evidence paths). The paths are a
# TUPLE, never a bare string: a string here would be iterated character by
# character by ``list()`` and turn every source path into 40 one-letter rows.
_NOT_IMPLEMENTED: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # topology.srota is NOT listed here. It used to be a static entry, but a
    # static entry rots: engine work landing a srota intent kind would leave
    # this table claiming "no authorable intent kind" after it became false.
    # _srota_capability() below probes the engine instead, so the row follows
    # the compiler instead of contradicting it.
    (
        "access.firewall",
        "No firewall or access-policy engine exists. There is no policy "
        "artifact, no permission evaluation and no SystemVerilog firewall "
        "generator, so the reference product's 'Zero-Trust rules validated' "
        "and per-path generated rules have nothing behind them.",
        "tracks/t3-topology/dse/veritx_dse (zero occurrences of 'firewall')",
    ),
    (
        "generate.rtl",
        "OutputFormat.SYSTEMVERILOG is declared in the model and an artifact id "
        "'-rtl' is named, but no emitter exists: scripts/rtlgen/gen_rtl.py is "
        "absent from the tree and scripts/check_python_deps.py records the "
        "absence with an explicit fallback verdict rather than a silent pass.",
        "scripts/check_python_deps.py",
    ),
    (
        "physical.signoff",
        "No PDK, LEF/DEF, RC model, static-timing analysis or place-and-route "
        "artifact exists. Die area, TDP, metal stack, WNS/TNS, congestion and "
        "thermal numbers cannot be produced or verified here.",
        "apps/studio/src/pages/loom/FloorplanLoom.tsx",
    ),
    (
        "workload.compute_architecture",
        "No compute-tile internal model exists (compute units, local memory "
        "hierarchy, accelerator units). Workload lowering produces logical "
        "operations and collectives; it does not model per-tile compute "
        "execution, so no cycle-accurate accelerator claim is available.",
        "tracks/t3-topology/dse/veritx_dse/workload/",
    ),
)

# Capabilities that are implemented but carry strictly less than the reference
# product implies. Each names exactly what is missing.
_PARTIAL: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "generate.uvm",
        "The product can emit stamped SystemVerilog, but that output is not "
        "qualified: it has no real UVM library integration, and its generated "
        "noc_mesh instantiation uses parameters and omits ports required by "
        "the repository's RTL DUT. Verilator lint against rtl/t3/mesh.sv "
        "fails. Treat output as an unverified template, not runnable UVM "
        "collateral, until it compiles and runs against the supported DUT.",
        (
            "tracks/t3-topology/dse/veritx_dse/verification/uvm_gen.py",
            "tracks/t3-topology/rtl/t3/mesh.sv",
        ),
    ),
    (
        "agent.interface",
        "The agent interface record carries five fields (data width, address "
        "width, protocol, clock domain, power domain). AIU type, ordering "
        "rules, payload splitting, max outstanding transactions and access "
        "permissions are not in the contract, so the reference product's "
        "per-agent deep config cannot be populated from any artifact.",
        "tracks/t3-topology/dse/veritx_dse/model/attachment.py",
    ),
    (
        "domain.clock_power",
        "Clock and power domain NAMES are authored per agent group and "
        "membership is readable from the certified attachment, so a census and "
        "a derived crossing list are possible. There is no clock tree (source, "
        "PLL, divider, mux, gate), no per-domain frequency, uncertainty or "
        "jitter, no synchronizer recommendation, no power state table and no "
        "SDC/UPF export. Every shipped example leaves the domain fields null.",
        "tracks/t3-topology/dse/veritx_dse/model/compile_model.py",
    ),
    (
        "address.decode",
        "The address-decode group is present and carries address_transform and "
        "unmatched_address_policy, but emits no rows for the shipped designs, "
        "and the drafts declare empty address_map ranges. No address map, "
        "overlap detection or address editor can be built on it yet.",
        "tracks/t3-topology/dse/veritx_dse/application/address_decode.py",
    ),
    (
        "physical.placement",
        "Router coordinates and channel adjacency are certified and link "
        "lengths are modelled, but the shipped revisions carry zero physical "
        "links, so there is no wire geometry to measure. Only an abstract "
        "projection is honest.",
        "tracks/t3-topology/dse/veritx_dse/model/topology_artifact.py",
    ),
    (
        "evidence.route_realization",
        "Route realization is observed at FIRST_HOP scope and explicitly does "
        "not claim a full observed path. The canonical route is DERIVED "
        "EXPECTED; a full runtime path observation does not exist.",
        "tracks/t3-topology/dse/veritx_dse/backend/route_observation.py",
    ),
    (
        "simulation.per_link_telemetry",
        "Per-link (per-channel) MEASURED telemetry is real and product-wired: "
        "backend/channel_measurements.py parses the vendored BookSim "
        "channel-activity dump into a MEASURED_CHANNEL_LOAD artifact, "
        "backend/channel_series.py reads the sampled series with its "
        "sample_period_cycles, and the gateway serves both through "
        "/api/v1/loom/simulation/{load,series,link} with source='measured' "
        "(derived utilization is refused server-side). It is PARTIAL rather "
        "than READY because the counters it can carry are only flits and "
        "window/period timing: stalls_per_window is None, not zeros "
        "(TRACK_STALLS is not defined in the build), so stall/backpressure "
        "cycles and buffer-occupancy samples are ABSENT, not zero. No power "
        "counter exists either.",
        (
            "tracks/t3-topology/dse/veritx_dse/backend/"
            "channel_measurements.py",
            "tracks/t3-topology/dse/veritx_dse/backend/channel_series.py",
        ),
    ),
    (
        "staleness.run_vs_draft",
        "draft.dirty is exposed and a run records the revision it ran against, "
        "so staleness is computable, but there is no first-class server-side "
        "STALE verdict binding a result to the current draft.",
        "tracks/t3-topology/dse/veritx_dse/gateway/staleness.py",
    ),
    (
        "fabric.multiplane",
        "Srota plane-role names exist but the fabric bundle supports only "
        "SINGLE_PLANE and refuses multi-plane construction. No independent "
        "data/telemetry/config plane materialization or per-plane capability "
        "exists.",
        "tracks/t3-topology/dse/veritx_dse/model/fabric_artifact.py",
    ),
    (
        "router.concentration",
        "1:1 mesh and qualified 4:1 concentrated mesh are supported. 2:1 is "
        "not supported by the native cmesh projection: the vendored code asserts "
        "c == 4 ('broken for c != 4'); no exact AnyNet lowering for 2:1 exists.",
        "third_party/booksim2/src/networks/cmesh.cpp",
    ),
    (
        "router.vc_allocation",
        "VC assignment/resources and PACKET allocation scope exist, but no "
        "authored static/dedicated/shared-pool/custom allocation modes are "
        "mapped to BookSim semantics.",
        "tracks/t3-topology/dse/veritx_dse/model/router_behavior.py",
    ),
)

# Capabilities the compiler fully owns, proven by a probe. These are not
# hard-coded statuses: each one's status is read out of capability_truth.
_STATIC_CAPABILITIES: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    (
        "design.compile_request",
        "CompileRequest v4 is the current authoring seam; v3 is still accepted "
        "and migrated. Working draft, revision and revision diff are all wired.",
        "READY", "",
        ("tracks/t3-topology/dse/veritx_dse/model/compile_request_v4.py",
         "tracks/t3-topology/dse/veritx_dse/model/compile_model.py"),
    ),
    (
        "attachment.endpoints",
        "The certified attachment carries one row per agent instance with "
        "endpoint id, router, port, group and instance index. A real per-agent "
        "matrix is therefore a projection of an artifact, not a synthesis.",
        "READY", "",
        ("tracks/t3-topology/dse/veritx_dse/model/attachment.py",),
    ),
    (
        "routing.canonical_route",
        "Routes are derived by the compiler and served by query. The route "
        "table is deliberately withheld from the payload; the UI must query "
        "per (class, src, dst).",
        "READY", "",
        ("tracks/t3-topology/dse/veritx_dse/core/route_artifact.py",
         "tracks/t3-topology/dse/veritx_dse/gateway/app.py"),
    ),
    (
        "vc.assignment",
        "VC count, VC-to-routing-class and traffic-class-to-VC bindings are "
        "derived and carried in the compile-result resources group.",
        "READY", "",
        ("tracks/t3-topology/dse/veritx_dse/model/compile_model.py",),
    ),
    (
        "verification.deadlock_certificate",
        "The channel-VC dependency graph is built from the resolved routes and "
        "VC assignment and checked for cycles, with a witness and method name. "
        "Escape VCs are modelled.",
        "READY", "",
        ("tracks/t3-topology/dse/veritx_dse/verification/channel_vc_cdg.py",
         "tracks/t3-topology/dse/veritx_dse/verification/adaptive_escape.py"),
    ),
    (
        "execution.booksim_standalone",
        "BookSim standalone executes trace-driven network runs under a "
        "qualified profile and returns conserved packet and flit counters plus "
        "per-class latency aggregates.",
        "READY", "",
        ("tracks/t3-topology/dse/veritx_dse/backend/booksim_execution.py",),
    ),
    (
        "evidence.chain_and_provenance",
        "The artifact chain links design to inventory, topology and route with "
        "the obligation that proves each hop. Run evidence carries binary, "
        "build-manifest, config, trace and route-dump digests, seed, parser "
        "version, profile and producer revision.",
        "READY", "",
        ("tracks/t3-topology/dse/veritx_dse/backend/evidence.py",),
    ),
    (
        "optimization.candidate_ledger",
        "Candidates, including infeasible and evaluation-failed ones, are "
        "retained; Pareto selection and capability-checked objectives are "
        "wired, and adoption promotes to draft rather than mutating the source "
        "revision.",
        "READY", "",
        ("tracks/t3-topology/dse/veritx_dse/optimization/",),
    ),
    (
        "comparison.runs",
        "Run comparison refuses inadmissible pairs itself: differing workload "
        "identity yields NOT_COMPARABLE with a per-row reason and no winner.",
        "READY", "",
        ("tracks/t3-topology/dse/veritx_dse/core/comparison.py",
         "tracks/t3-topology/dse/veritx_dse/application/comparison.py"),
    ),
)

# Backends that implement but cannot answer everything. Readiness here is a
# property of the installed system; per-design readiness belongs to the
# evaluation planner and is NOT restated in this table.
_BACKEND_CAPABILITIES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "execution.astra",
        "The ASTRA2 embedded-BookSim frontend is present and answers "
        "SYSTEM_MAKESPAN under a qualified collective profile. Its numerical "
        "timing oracle is NOT_ESTABLISHED: the integration is qualified while "
        "numerical timing awaits the per-domain oracles.",
        "tracks/t3-topology/dse/veritx_dse/backend/astra_execution.py",
    ),
    (
        "execution.ramulator",
        "Ramulator answers DRAM_TIMING only, and only when a memory operation "
        "can be attributed to a real memory participant. Without compute "
        "operation placement it refuses rather than sending anonymous compute "
        "traffic and calling the result DRAM timing.",
        "tracks/t3-topology/dse/veritx_dse/backend/ramulator_adapter.py",
    ),
    (
        "execution.serving",
        "Serving answers SERVING_TTFT and SERVING_COMPLETION for a bound "
        "experiment whose cluster profile actually matches the design's model "
        "and rank count. With no bound experiment it is BLOCKED, never READY.",
        "tracks/t3-topology/dse/veritx_dse/backend/serving_adapter.py",
    ),
)


# New canonical intent submodels authored this pass. Each is REAL CODE that
# validates and roundtrips, but NONE is yet carried by a CompileRequest root,
# so none of them enters design identity — that is exactly what
# blocked_at=AUTHORABLE records. Reporting them READY would claim the compiler
# accepts them as design intent, which it does not yet do.
_SUBMODEL_CAPABILITIES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "design.compile_request_v5",
        "CompileRequestV5 explicitly composes a CompileRequestV4 base with "
        "identity-bearing agent roles, transaction policy, sidebands, access "
        "policy, clocks, resets, power domains and crossings. v4 migration is "
        "explicit and adds only empty, neutral extensions. V5-only intent "
        "changes the V5 hash, and projecting it to v4 refuses rather than "
        "dropping semantics. The current FabricCompiler still accepts only v4, "
        "so V5 is AUTHORABLE but stops before MATERIALIZABLE.",
        "MATERIALIZABLE",
        ("tracks/t3-topology/dse/veritx_dse/model/compile_request_v5.py",
         "tracks/t3-topology/dse/tests/test_compile_request_v5.py"),
    ),
    (
        "catalog.ip",
        "Server-owned IP catalog contains 12 typed templates, but templates "
        "are not draft mutations: no Stamp command, compiler instance "
        "materializer, or backend consumer exists. Area and power remain NOT "
        "PROVIDED. Loom must not expose an actionable stamp until its required "
        "capability ids and draft mutation seam are bound.",
        "AUTHORABLE",
        ("tracks/t3-topology/dse/veritx_dse/model/ip_catalog.py",
         "tracks/t3-topology/dse/tests/test_ip_catalog.py"),
    ),
    (
        "transaction.outstanding",
        "Canonical agent TRANSACTION CREDIT model (explicitly not a BookSim "
        "router buffer credit): OutstandingLimit(reads/writes/total) with "
        "cross-field laws, plus OutstandingTracker, a deterministic model that "
        "proves a limit of N blocks issue N+1 until a completion frees a slot. "
        "Not yet carried by a CompileRequest root, so it does not enter design "
        "identity and no backend consumes it.",
        "AUTHORABLE",
        ("tracks/t3-topology/dse/veritx_dse/model/transaction_intent.py",
         "tracks/t3-topology/dse/tests/test_transaction_intent.py"),
    ),
    (
        "transaction.ordering",
        "Protocol-neutral ordering: STRONG/RELAXED/CUSTOM with RAW/WAR/WAW "
        "hazard enforcement. STRONG requires all three hazards; CUSTOM refuses "
        "when it enforces none. Not bound into a root, and deliberately not "
        "called 'AXI ordering' — no protocol adapter exists yet.",
        "AUTHORABLE",
        ("tracks/t3-topology/dse/veritx_dse/model/transaction_intent.py",),
    ),
    (
        "transaction.splitting",
        "Splitting materializes real child transactions: split_transactions() "
        "emits contiguous [start,end) children carrying parent id, sequence, "
        "ordering domain and traffic class, with a conservation invariant. "
        "Legal boundaries are powers of two that evenly divide the payload. "
        "Not yet wired to packetization or to any execution backend.",
        "AUTHORABLE",
        ("tracks/t3-topology/dse/veritx_dse/model/transaction_intent.py",),
    ),
    (
        "sideband.interface",
        "Typed sideband interfaces (11 kinds, direction, width, clock/power "
        "domain, optional protocol binding) with strict validation. Not carried "
        "by a CompileRequest root yet.",
        "AUTHORABLE",
        ("tracks/t3-topology/dse/veritx_dse/model/sideband.py",
         "tracks/t3-topology/dse/tests/test_sideband.py"),
    ),
    (
        "sideband.connectivity",
        "Sideband connections are validated as their OWN edges (existence, "
        "direction, width, agent universe). A crossing clock domain is only "
        "FLAGGED via requires_clock_crossing(), never resolved here; resolution "
        "belongs to domain_intent. Sidebands are never modelled as payloads "
        "carried over the main NoC data plane.",
        "AUTHORABLE",
        ("tracks/t3-topology/dse/veritx_dse/model/sideband.py",),
    ),
    (
        "access.policy",
        "Architectural access policy: RW/RO/WO/DENY rules over address windows "
        "with an explicit five-rung ladder (endpoint, route, window, "
        "permission, observed) kept separate, each rung bool|None so unknown "
        "never becomes false. Unmapped addresses default to DENY; overlaps "
        "refuse naming both rules. This is NOT a firewall — access.firewall "
        "stays unimplemented. Not bound into a root, so no run has ever been "
        "authorized by it.",
        "AUTHORABLE",
        ("tracks/t3-topology/dse/veritx_dse/model/access_policy.py",
         "tracks/t3-topology/dse/tests/test_access_policy.py"),
    ),
    (
        "reset.intent",
        "First-class reset intent: source, target clock domain, polarity, an "
        "assertion mode, a release synchronizer stage count and a dependency "
        "release order, with cycle/self-reference/unknown-dependency refusal. "
        "Not carried by a CompileRequest root yet.",
        "AUTHORABLE",
        ("tracks/t3-topology/dse/veritx_dse/model/domain_intent.py",),
    ),
    (
        "reset.async_assert_sync_deassert",
        "The canonical async-assert/sync-deassert case is expressible and "
        "valid: assertion=ASYNC requires synchronizer_stages>=2 and "
        "deassertion=SYNC. ASYNC deassertion is a typed REFUSAL because this "
        "system neither models nor claims it. Structural intent only — this is "
        "NOT a metastability proof and NOT signoff.",
        "AUTHORABLE",
        ("tracks/t3-topology/dse/veritx_dse/model/domain_intent.py",),
    ),
    (
        "cdc.crossing",
        "Crossing intent with mechanism validation: same-domain refusal, "
        "multi-bit vs single-bit classification, SYNC_2FF/SYNC_3FF exact stage "
        "laws, ASYNC_FIFO consistency, and UNRESOLVED_CROSSING as the honest "
        "answer when information is missing — never auto-promoted to a 2FF. "
        "Intent VALID only; no signoff verification exists.",
        "AUTHORABLE",
        ("tracks/t3-topology/dse/veritx_dse/model/domain_intent.py",),
    ),
    (
        "cdc.sync_2ff",
        "Two-flop synchronizer crossing validated structurally (stages must be "
        "exactly 2; single-bit/pulse only). INTENT VALIDATION ONLY: no RTL "
        "differential, no MTBF claim, no signoff.",
        "AUTHORABLE",
        ("tracks/t3-topology/dse/veritx_dse/model/domain_intent.py",),
    ),
    (
        "cdc.sync_3ff",
        "Three-flop synchronizer crossing validated structurally (stages must "
        "be exactly 3; single-bit/pulse only). INTENT VALIDATION ONLY: no RTL "
        "differential, no MTBF claim, no signoff.",
        "AUTHORABLE",
        ("tracks/t3-topology/dse/veritx_dse/model/domain_intent.py",),
    ),
    (
        "cdc.async_fifo",
        "Async FIFO intent (depth>=2, Gray requires power-of-two depth, width, "
        "synchronizer stages) plus AsyncFIFOModel, a Q1 performance model "
        "covering occupancy, full/empty, synchronizer latency and backpressure "
        "with no-overfill/no-underflow invariants. Fidelity is "
        "HETERO_TIMING_ABSTRACT: the model deliberately shares ONE cycle "
        "counter and models NO clock ratio, so clock-ratio behaviour is "
        "NOT_MODELED. Not differential-tested against PULP common_cells RTL.",
        "AUTHORABLE",
        ("tracks/t3-topology/dse/veritx_dse/model/domain_intent.py",),
    ),
)

# Capabilities with no implementation at this HEAD; verified by absence.
_MISSING_SURFACE: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "physical.openroad",
        "No OpenROAD integration exists: no LEF/DEF/SDC handoff, no sidecar "
        "runner, no tool-version/input-digest/output-digest provenance. The "
        "floorplan view is an ABSTRACT placement projection only, so WNS/TNS, "
        "congestion and routed wirelength are unavailable — not zero.",
        ("apps/studio/src/pages/loom/FloorplanLoom.tsx",),
    ),
    (
        "desktop.tauri",
        "No desktop shell exists: apps/studio is a Vite/React web build with no "
        "Tauri v2 configuration, no packaged gateway sidecar, no owned process "
        "lifecycle and no OS filesystem/export ownership. The product still "
        "requires the user to start the gateway themselves.",
        ("apps/studio/package.json",),
    ),
    (
        "router.rcu",
        "No RCU collective realization is wired in the current compiler/backend. "
        "A legacy rcu_enabled input exists but does not materialize an RCU router "
        "or collective endpoint; the field was removed from the v4 design view.",
        ("tracks/t3-topology/dse/veritx_dse/model/noc_controls.py",),
    ),
)


def _srota_capability() -> Capability | None:
    """The srota fabric's product reachability, probed live, never asserted.

    Every check here is cheap — enum membership, tuple membership, one file
    existence — so this runs on every registry read including the fast path
    that skips the topology probe.

    Returns None when srota is a gated compiler kind. Then the probed family
    row carries the pipeline truth under this same id, and a second row would
    be a duplicate id, not a second fact. The simulator-side record matters
    only while the product cannot reach the fabric — precisely when srota is
    not gated — so yielding loses nothing. The gate check reads GATED_KINDS,
    not the probe result, so it is correct on the fast path too.

    The state machine follows the engine, which is the whole point. Today
    srota is READY in the vendored simulator and absent from the product, so
    this reports NOT_IMPLEMENTED. When engine work lands an authorable srota
    intent kind, the row moves to PARTIAL on its own, and when the kind is
    gated the family probe takes over. No text edit is required for any of
    those transitions, which is what keeps this table from contradicting the
    compiler it describes.
    """
    from veritx_dse.application.capability_truth import GATED_KINDS
    if "srota" in GATED_KINDS:
        return None
    from veritx_dse.core.paths import REPO
    from veritx_dse.model.compile_model import TopologyFamily
    from veritx_dse.model.topology_intent import AUTHORABLE_INTENT_KINDS

    simulator = (REPO / "third_party" / "booksim2" / "src"
                 / "networks" / "srota.cpp").is_file()
    authorable = "srota" in AUTHORABLE_INTENT_KINDS
    familied = any(m.value == "srota" for m in TopologyFamily)

    refs = ["third_party/booksim2/src/networks/srota.cpp"]
    if not simulator:
        # The one fact this row always carried is gone. That is reported,
        # not papered over: without the vendored model there is no srota
        # anywhere, product or simulator.
        return Capability(
            id="topology.srota",
            status="NOT_IMPLEMENTED",
            reason="The vendored BookSim srota model "
            "(third_party/booksim2/src/networks/srota.cpp) is absent from "
            "this checkout, and the product has no srota intent kind, family "
            "or profile either. There is currently no srota anywhere.",
            evidence_refs=tuple(refs),
        )
    refs.append("tracks/t3-topology/dse/veritx_dse/model/topology_intent.py")
    if familied:
        refs.append("tracks/t3-topology/dse/veritx_dse/model/compile_model.py")

    if not authorable:
        missing = []
        if not familied:
            missing.append("no entry in the compiler's TopologyFamily enum")
        missing.append("no authorable intent kind")
        missing.append("no BookSim projection profile renders topology = srota")
        return Capability(
            id="topology.srota",
            status="NOT_IMPLEMENTED",
            reason="The srota NoC fabric exists and executes in the vendored "
            "BookSim (networks/srota.cpp: MECS express channels, hybrid "
            "mesh+express planes, per-class path shape/plane/VC, O1TURN-XY "
            "with a congestion overlay, and its own static "
            "channel-dependency-graph check). It has " + "; ".join(missing)
            + ", so no user can author, compile, verify or evaluate it "
            "through the product.",
            evidence_refs=tuple(refs),
        )

    # Authorable but not yet gated (or the probe skipped). The pipeline
    # position belongs to the family probe, so this row refuses to guess it:
    # PARTIAL names exactly what is known — the fabric is authorable and the
    # simulator executes it — and points at the probed registry for the rest.
    # (Authorable-but-ungated is also a red CI gate via missing_probe_kinds,
    # so this branch doubles as the honest row for a transiently broken tree.)
    return Capability(
        id="topology.srota",
        status="PARTIAL",
        reason="srota is an authorable intent kind and executes in the "
        "vendored BookSim, but it is not a gated compiler kind, so no "
        "probed pipeline position exists for it. Read the probed family "
        "rows, not this row, for how far any family compiles.",
        evidence_refs=tuple(refs),
        required_inputs=("a CompileRequestV4 topology intent of kind 'srota'",),
    )


def _family_capability(family: str, truth: Any) -> Capability:
    """One topology family, its probed stage truth, and where it stops.

    Derive the stop from the final per-stage observations, not the compiler's
    internal stop marker: direct seam probes can prove a stage even when the
    full compiler path stopped earlier.
    """
    stages = dict(truth.stages)
    incomplete = [s for s in STAGE_ORDER if stages.get(s) != "YES"]
    blocked_at = incomplete[0] if incomplete else None
    if blocked_at is None:
        status = "READY"
        reason = (
            "Probed end to end at this HEAD: the compiler accepts this family, "
            "materializes it, derives routes, produces the verifiable bundle, "
            "and a shipped product preset normalizes to it.")
    else:
        authority = truth.authority.get(blocked_at, "")
        # Only the shipping stage is a PARTIAL capability: everything before it
        # works. Anything earlier is a genuine gap in the compiler path.
        status = "PARTIAL" if blocked_at == "PRODUCT_WIRED" else "BLOCKED"
        reason = (
            f"Blocked at {blocked_at} (requires: "
            f"{_STAGE_MEANING.get(blocked_at, blocked_at)}). Probe authority: "
            + (authority or "no authority recorded for this stage."))
    return Capability(
        id=f"topology.{family}",
        status=status,
        reason=reason,
        required_inputs=(f"a CompileRequestV4 topology intent of kind '{family}'",),
        backend="BOOKSIM_STANDALONE",
        qualification=truth.profile_id,
        evidence_refs=(
            "tracks/t3-topology/dse/veritx_dse/application/capability_truth.py",
            "tracks/t3-topology/dse/veritx_dse/model/topology_intent.py",
        ),
        blocked_at=blocked_at,
    )


def _stage_name_for(internal: str) -> str:
    """Map an internal stop name onto this module's STAGE_ORDER vocabulary.

    ``capability_truth`` reports the compiler stage that produced the stop
    ("TOPOLOGY", "ROUTING", "VERIFICATION"). The product speaks in pipeline
    stages, so a client never has to know the compiler's internal vocabulary.
    """
    return {
        "TOPOLOGY": "MATERIALIZABLE",
        "ROUTING": "ROUTABLE",
        "VERIFICATION": "VERIFIABLE",
        "VERIFICATION_BUNDLE": "VERIFIABLE",
        "PROJECTION": "PROJECTABLE",
        "EXECUTION": "EXECUTABLE",
        "QUALIFICATION": "QUALIFIED",
        "PRESET": "PRODUCT_WIRED",
    }.get(internal, internal)


def topology_family_capabilities(
    truth: dict[str, Any] | None = None,
) -> list[Capability]:
    """Probe the real compiler for every registered topology family.

    This is the expensive call: it runs the compiler for each of the registered
    families. The result is the authority the UI uses, so it is never cached
    into a static literal that could drift from the compiler. A caller that
    already derived the stage truth (loom_capabilities, which also needs the
    srota row's pipeline position) passes it in so the probe runs once.
    """
    if truth is None:
        from veritx_dse.application.capability_truth import (
            GATED_KINDS, derive_all_stages,
        )
        truth = derive_all_stages()
    else:
        from veritx_dse.application.capability_truth import GATED_KINDS
    return [_family_capability(family, truth[family]) for family in GATED_KINDS]


def loom_capabilities(*, include_topology_probe: bool = True) -> dict[str, Any]:
    """The complete capability table the Loom UI is allowed to read.

    ``include_topology_probe`` exists because the topology probe compiles every
    registered family and is far slower than the rest of the table. Callers that
    only need the static capabilities (a health check, a unit test) can skip it;
    callers that will render a topology selector must not.
    """
    capabilities: list[Capability] = []
    for cid, reason, backend, qualification, refs in _STATIC_CAPABILITIES:
        capabilities.append(Capability(
            id=cid, status="READY", reason=reason,
            required_inputs=(), backend=backend or None,
            qualification=qualification or None, evidence_refs=refs))
    for cid, reason, refs in _BACKEND_CAPABILITIES:
        capabilities.append(Capability(
            id=cid, status="BLOCKED", reason=reason,
            required_inputs=(
                "a bound execution context whose canonical design matches "
                "the backend's supported question and ownership"),
            backend=cid.split(".", 1)[1],
            evidence_refs=refs))
    for cid, reason, refs in _PARTIAL:
        capabilities.append(Capability(
            id=cid, status="PARTIAL", reason=reason, evidence_refs=refs))
    for cid, reason, blocked_at, refs in _SUBMODEL_CAPABILITIES:
        capabilities.append(Capability(
            id=cid, status="PARTIAL", reason=reason,
            blocked_at=blocked_at, evidence_refs=refs,
            required_inputs=(
                "a CompileRequest root that carries this intent, so it enters "
                "design identity",)))
    for cid, reason, refs in _MISSING_SURFACE:
        capabilities.append(Capability(
            id=cid, status="NOT_IMPLEMENTED", reason=reason,
            evidence_refs=refs))
    for cid, reason, refs in _NOT_IMPLEMENTED:
        capabilities.append(Capability(
            id=cid, status="NOT_IMPLEMENTED", reason=reason,
            evidence_refs=refs))

    # The srota row is probed, not listed: _srota_capability reads the engine
    # (gated kinds, intent kinds, family enum, vendored model) on every read,
    # so the row follows the compiler instead of rotting beside it. When
    # srota is gated the function yields None and the probed family row
    # carries it (one id, one row).
    topology: dict[str, Any] = {"probed": False, "families": []}
    if include_topology_probe:
        from veritx_dse.application.capability_truth import derive_all_stages
        truth = derive_all_stages()
        families = topology_family_capabilities(truth)
        capabilities.extend(families)
    srota_row = _srota_capability()
    if srota_row is not None:
        capabilities.append(srota_row)
    if include_topology_probe:
        topology = {
            "probed": True,
            "stage_order": list(STAGE_ORDER),
            "stage_meaning": dict(_STAGE_MEANING),
            "families": [
                {"family": f.id.split(".", 1)[1],
                 "status": f.status,
                 "stopped_at": f.blocked_at,
                 "qualification": f.qualification,
                 "reason": f.reason}
                for f in families
            ],
        }

    by_status: dict[str, list[str]] = {}
    for cap in capabilities:
        by_status.setdefault(cap.status, []).append(cap.id)

    return {
        "schema_version": 1,
        "type": "srota/LoomCapabilityRegistry",
        "statuses": list(CAPABILITY_STATUSES),
        "note": (
            "Capability state is decided here, on the server, by probing the "
            "compiler and the installed backends. A client must not infer "
            "capability from a topology name, a model name or a design value, "
            "and must not offer an action whose capability is not READY."),
        "readiness_note": (
            "These statuses describe the installed system. Whether a specific "
            "design can be executed RIGHT NOW is decided per context by the "
            "evaluation planner, which separates support (can the backend "
            "represent this at all) from readiness (can it run now). Both "
            "appear on an evaluation plan; neither is inferred here."),
        "capabilities": [c.as_dict() for c in capabilities],
        "by_status": by_status,
        "topology": topology,
    }

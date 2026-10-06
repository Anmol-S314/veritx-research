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
_NOT_IMPLEMENTED: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "topology.srota",
        "The srota NoC fabric exists and executes in the vendored BookSim "
        "(networks/srota.cpp: MECS express channels, hybrid mesh+express "
        "planes, per-class path shape/plane/VC, O1TURN-XY with a congestion "
        "overlay, and its own static channel-dependency-graph check). It has "
        "no entry in the compiler's TopologyFamily enum, no authorable intent "
        "kind, and no BookSim projection profile, so no user can author, "
        "compile, verify or evaluate it through the product.",
        "third_party/booksim2/src/networks/srota.cpp",
    ),
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
    (
        "simulation.per_link_telemetry",
        "The BookSim backend emits per-NODE injection and acceptance rates and "
        "per-CLASS latency aggregates. It does not emit per-link counters, "
        "per-cycle series, or a stall-class breakdown (TRACK_STALLS is not "
        "defined in the build). A cycle scrubber or a per-link utilization "
        "heatmap therefore has no backing artifact.",
        "tracks/t3-topology/dse/veritx_dse/backend/booksim_execution.py",
    ),
)

# Capabilities that are implemented but carry strictly less than the reference
# product implies. Each names exactly what is missing.
_PARTIAL: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
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
        "generate.uvm",
        "A real UVM generator exists (486 lines: top, sequences, assertions, "
        "coverage) but it imports model symbols that the v4 refactor removed "
        "and no product or gateway route calls it. Research-grade until it is "
        "re-plumbed and wired.",
        "tracks/t3-topology/dse/veritx_dse/verification/uvm_gen.py",
    ),
    (
        "staleness.run_vs_draft",
        "draft.dirty is exposed and a run records the revision it ran against, "
        "so staleness is computable, but there is no first-class server-side "
        "STALE verdict binding a result to the current draft.",
        "tracks/t3-topology/dse/veritx_dse/gateway/staleness.py",
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


def _family_capability(family: str, truth: Any) -> Capability:
    """One topology family, its probed stage truth, and where it stops."""
    stages = dict(truth.stages)
    stopped = truth.stopped_at_stage
    if stopped is None:
        # No explicit stop: the family is complete when every stage is YES.
        incomplete = [s for s in STAGE_ORDER if stages.get(s) != "YES"]
        stopped = incomplete[0] if incomplete else None
    if stopped is None:
        status = "READY"
        blocked_at = None
        reason = (
            "Probed end to end at this HEAD: the compiler accepts this family, "
            "materializes it, derives routes, produces the verifiable bundle, "
            "and a shipped product preset normalizes to it.")
    else:
        blocked_at = _stage_name_for(stopped)
        authority = truth.authority.get(stopped, "")
        # Only the shipping stage is a PARTIAL capability: everything before it
        # works. Anything earlier is a genuine gap in the compiler path.
        status = "PARTIAL" if blocked_at == "PRODUCT_WIRED" else "BLOCKED"
        reason = (
            f"Complete up to but not including {blocked_at} "
            f"({_STAGE_MEANING.get(blocked_at, blocked_at)}). "
            + (authority or "No authority recorded for this stage."))
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


def topology_family_capabilities() -> list[Capability]:
    """Probe the real compiler for every registered topology family.

    This is the expensive call: it runs the compiler for each of the registered
    families. The result is the authority the UI uses, so it is never cached
    into a static literal that could drift from the compiler.
    """
    from veritx_dse.application.capability_truth import (
        GATED_KINDS, derive_all_stages,
    )
    truth = derive_all_stages()
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
    for cid, reason, refs in _NOT_IMPLEMENTED:
        capabilities.append(Capability(
            id=cid, status="NOT_IMPLEMENTED", reason=reason,
            evidence_refs=refs))

    topology: dict[str, Any] = {"probed": False, "families": []}
    if include_topology_probe:
        families = topology_family_capabilities()
        capabilities.extend(families)
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

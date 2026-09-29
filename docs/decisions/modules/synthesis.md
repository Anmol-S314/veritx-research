# `synthesis` — extracted module rationale

Extracted from the module docstrings of `veritx_dse/{name}` by the 2026-09-29 debloat. Code keeps a one-line pointer; this is the original long-form text.

## `tracks/t3-topology/dse/veritx_dse/synthesis/bo_adapter.py`

```text
BO synthesis adapter — parameterized-generator search as candidate producer.

Bayesian optimization over the historical 5-D topology-generator space
(cluster_size, express_length, radix, intra_weight, inter_weight).
The surrogate is pluggable and defaults to honestly-labelled
seeded-random: no scikit-optimize GP is vendored or claimed. A GP
returns only with a vendored, qualified surrogate whose name is recorded
on the proposal; until then the search reports BUDGETED completeness,
never exhaustive or optimal.

Same laws as the RHO/GRPO adapter: seeded determinism, connectivity +
radix invariants, sentinel ban, no uniform fallback, no BookSim
authority, candidate-identical proposal identity, vocabulary gate.
```

## `tracks/t3-topology/dse/veritx_dse/synthesis/bo_synthesizer.py`

```text
bo_synthesizer.py — Bayesian Optimization topology synthesis.

Replaces SA with BO for sample-efficient optimization of NoC topologies.
Searches over TOPOLOGY PARAMETERS (5 dimensions) instead of individual
edges (118+ dimensions), making it tractable for GP surrogates.

Search space:
  cluster_size:   {4, 8, 16} — nodes per cluster
  express_length: {1, 2, 3}  — max hop length for express links
  radix:          {3, 4, 5}  — max degree per node
  intra_weight:   [0.5, 1.0] — probability of intra-cluster edges
  inter_weight:   [0.1, 0.5] — probability of inter-cluster edges

Usage:
  python3 bo_synthesizer.py --traffic runs/traces/test1_events.json --nodes 64 --iters 50
```

## `tracks/t3-topology/dse/veritx_dse/synthesis/candidate.py`

```text
veritx_dse.synthesis.candidate — TopologyCandidate and the MILP adapter.

THE AUTHORITY BOUNDARY
----------------------

A synthesis engine produces a CANDIDATE. It does not produce a fabric, a
route, a certificate or a measurement. The chain is:

    SynthesisDefinition + SynthesisTrafficMatrix
        -> engine (milp_topology_v2, unmodified)
        -> TopologyCandidate            <- this module
        -> TopologyIR  (kind=custom)    <- the SAME explicit topology
                                           representation an authored custom
                                           graph uses
        -> materialize_ir -> TopologyArtifact
        -> the NORMAL compiler -> verification -> evaluation

The engine never becomes a second compiler, verifier or evaluator. The
adapter's only job is to translate one engine's output into the canonical
explicit topology representation and to record provenance honestly.

GENERATOR OBJECTIVE != EVALUATED PERFORMANCE
--------------------------------------------

`objective_value` is a GENERATOR objective: traffic-weighted hop count, or
a priced geodesic over ANALYTICAL, UNCALIBRATED wire/pipeline constants.
It is NOT latency, NOT BookSim completion, NOT a Pareto metric. It is
carried on the candidate so a synthesis attempt can be compared with
another synthesis attempt, and for no other purpose. A test asserts the
candidate carries no certificate or performance field.

`.anynet` IS NOT AUTHORITY
--------------------------

The engine writes `<out>.anynet`. That is a BookSim PROJECTION. The
canonical graph is `links` on the candidate, and the candidate identity is
computed from the definition and the graph — never from the projection's
formatting or path.
```

## `tracks/t3-topology/dse/veritx_dse/synthesis/definition.py`

```text
veritx_dse.synthesis.definition — the canonical synthesis problem.

WHAT THIS IS
------------

One strict, immutable, versioned, content-addressed description of a
topology synthesis problem. It is the input to a synthesis engine and the
parent identity of every candidate the engine produces.

SCIENCE vs EXECUTION POLICY (the central distinction)
-----------------------------------------------------

Identity binds only what can CHANGE THE GRAPH:

  SCIENTIFIC_IDENTITY  router count, layout, layout seed/jitter, radix,
                       max link length, diameter bound, objective, physical
                       price model, link attributes, engine family, and the
                       deterministic seed of a stochastic algorithm
  EXECUTION_POLICY     solver time limit, exact-solve node cap, binary path,
                       output directory — these change how long a run takes,
                       never which graph is correct
  PROVENANCE           solver name/version, host, wall time

A time limit that produces a different incumbent DOES change the emitted
graph, but it changes the ATTEMPT, not the problem: the candidate identity
binds the graph, so a different incumbent is a different candidate under
the same definition. That is the correct modelling, and it is why the
timeout is policy rather than identity.

NO HIDDEN FALLBACK
------------------

The historical CLI accepts a bare matrix file and will happily build a
degenerate problem from it. This type refuses to exist without an explicit,
validated traffic authority and an explicit layout that matches the router
count. There is no uniform-traffic default and no auto-guessed layout.
```

## `tracks/t3-topology/dse/veritx_dse/synthesis/event_objective.py`

```text
event_objective.py — Score a candidate topology DIRECTLY from the event
stream (no intermediate matrix aggregation).

This closes the gap identified after Test 3: synthesis consumed re-aggregated
matrices. Here the objective reads the lossless event representation:

  - dram_io events      → per-tile DRAM load (context; not fabric edges)
  - collective events   → kept STRUCTURAL {participants, size_bytes}; scored
                          under MULTIPLE algorithms (ring / halving-doubling)
                          on the candidate topology, best algorithm wins
  - flow class priority → deadline-critical flows (prio 1) count more

Objective = sum over collectives of priority_weight * algo_weight *
            priced_geodesic_latency(participants, size, adj, algo)

This is the thing a pre-aggregated matrix CANNOT express (Test 2, Proof 2).
```

## `tracks/t3-topology/dse/veritx_dse/synthesis/iterative_synthesizer.py`

```text
iterative_synthesizer.py — RHO + GRPO topology synthesis.

Standalone research driver for rolling-horizon and group-relative topology
search over BookSim trace replay. The product wiring is
``rho_grpo_adapter.py``; keep the two in sync. See
``docs/decisions/synthesis.md`` for the search semantics.
```

## `tracks/t3-topology/dse/veritx_dse/synthesis/milp_topology_v2.py`

```text

milp_topology_v2.py — Traffic-weighted topology MILP (NetSmith method, scipy/HiGHS).

Reads a traffic matrix T (row=src, col=dst) and, given a router physical layout
(grid or interposer) + radix + link-length budget, GENERATES a custom topology
minimizing the traffic-weighted average hop count.

This is the correct L2 synthesizer core. Objective is enforced by a
Traffic-Min-Cost-Flow (TMCF) MILP: every (i,j) unit of demand is routed on
chosen links, each link traversal costs 1 hop, and we minimize total hops.
Result: a topology (chosen links) + routing that is latency-optimal under T,
respecting radix + link-length + optional diameter.

Design:
  * Seed with the layout's base mesh -> guarantees connectivity/feasibility.
  * MILP decides which EXTRA candidate links (within link-length budget) to add
    and the flow routing, minimizing total hops under radix budget.
  * Exact solve capped at --max_nodes (=20 default); larger N falls back to the
    hot-pair greedy (milp_topology.py logic) for design-time speed. NetSmith's
    stance: converged-but-beats-mesh is the goal, not global optimality.

Outputs:
  <out>.anynet   BookSim anynet (cycle-accurate proof leg)
  <out>.json     topology graph + routing + stats (for DSE / Constellation/FlooNoC)

Usage:
  python milp_topology_v2.py --matrix dse/inputs/qwen_moe_2d.mat --layout grid  --radix 3 --max_len 2 --out /tmp/c  --max_nodes 16
  python milp_topology_v2.py --matrix /tmp/test16.mat --layout interposer --rows 4 --cols 4 --radix 5 --out /tmp/ci
```

## `tracks/t3-topology/dse/veritx_dse/synthesis/rho_grpo_adapter.py`

```text
RHO/GRPO synthesis adapters — candidate producers, not evaluators.

Rolling-horizon (RHO) retains the useful historical idea (seed topology,
add/remove link mutations, connectivity + edge-budget invariants,
rolling-horizon evaluation) and GRPO retains group candidate evaluation
with relative selection — WITHOUT pretending GRPO is a trained RL policy.

Both emit HeuristicProposal objects whose identity binding is
candidate-identical (definition_id + traffic_id + nodes + sorted links),
so the lead integrator's vocabulary widening (candidate.ALGORITHMS +
definition ENGINES) changes nothing in this file. Conversion via
to_topology_candidate() raises AdapterVocabularyPending until that
widening lands — a typed gate, never a silent bypass.

Laws (fail-closed):
- Seeded random.Random only; no global random, no subprocess, no BookSim.
- Analytical traffic_weighted_hops objective (exact BFS shortest paths);
  disconnected graphs raise CandidateRejected, never a penalty number.
- Sentinel ban: 1000.0 / 1e9 / non-finite objectives are refused, never
  valid measurements (historical failure laundering ends here).
- No uniform-traffic fallback: traffic dims must equal definition nodes.
- Proposals carry NO certificate, qualified performance, routing proof,
  Pareto membership or recommendation — screening only.
```

## `tracks/t3-topology/dse/veritx_dse/synthesis/traffic.py`

```text
veritx_dse.synthesis.traffic — canonical synthesis traffic authority.

WHY THIS EXISTS
---------------

The historical MILP generator reads a bare ``.mat`` file::

    def load_matrix(path):
        mat = []
        with open(path) as f:
            for line in f:
                ...
                mat.append([float(x) for x in line.split()])
        return np.array(mat)

That is a research-tool loader. It performs NO validation: a ragged file
raises deep inside numpy, a NaN propagates silently into the objective, and
a negative demand is accepted as ordinary traffic. It also carries no
record of WHERE the traffic came from, so a synthesised topology cannot be
traced back to the workload that justified it.

The canonical path needs the opposite: an explicit, validated, identified
traffic authority with no fallback of any kind.

NO HIDDEN FALLBACK — this is the rule the module exists to enforce:

  * no uniform-traffic default when the source is missing or malformed
  * no partial/lenient parse of a bad file
  * no silently reshaped matrix
  * no negative, NaN or infinite demand
  * no namespace mismatch between the matrix and the router count

Every one of those refuses with a typed error naming the field.

AGGREGATION IS DECLARED, NOT ASSUMED
------------------------------------

A traffic matrix is a PROJECTION of a richer workload. Which messages were
summed, over what span, in what unit — that is science, so it is carried
explicitly rather than implied. A matrix whose aggregation rule is unknown
cannot be reproduced and is therefore not a canonical authority.
```


# `synthesis` — extracted inline comments

## `tracks/t3-topology/dse/veritx_dse/synthesis/candidate.py`

line 26:

```text
#: Solver status vocabulary, preserved rather than collapsed. `OPTIMAL` is
#: only ever reported when the solver PROVED optimality of the encoded
#: MILP formulation — never inferred from a feasible incumbent.
```

line 331:

```text
        # Above the exact-solve cap the engine uses SIMULATED ANNEALING on the
        # ANALYTICAL objective. This is the ONLY place `objective` /
        # `pipe_cost` / `wire_cost` are consumed: the TMCF MILP always
        # minimizes traffic-weighted hops and cannot express them.
        #
        # The seed is `layout_seed`, so the same definition produces the SAME
        # graph every time — a synthesis candidate must be a stable scientific
        # identity, not a function of when it was evaluated.
```

## `tracks/t3-topology/dse/veritx_dse/synthesis/definition.py`

line 16:

```text
#: Layout domains. `grid` places k*k routers on an integer lattice;
#: `interposer` places rows*cols routers with seeded jitter (a chiplet
#: floorplan). Coordinates are SCIENTIFIC: they decide which links are
#: admissible and what a link costs.
```

line 29:

```text
#: `milp_tmcf` is exact for small N and falls back to SA above the cap. The
#: cap is EXECUTION POLICY: it selects which algorithm runs, and the chosen
#: algorithm is recorded on the candidate as provenance.
```

line 51:

```text
    #: Canonical channel attributes. TopologyIR REQUIRES these, so the
    #: synthesis problem must state them rather than let an adapter invent
    #: them. Both are SCIENTIFIC: they enter the artifact.
```

line 61:

```text
    #: NOTE: a diameter bound is deliberately ABSENT. The historical
    #: docstring of milp_topology_v2 advertises "optional diameter", but the
    #: engine adds only link-capacity, flow-conservation and radix
    #: constraints — diameter is never enforced. Exposing a constraint the
    #: engine ignores would be a false capability claim, so the field does
    #: not exist and a caller cannot ask for it.
    #:
    #: Deterministic layout seed + jitter (interposer only). SCIENTIFIC:
    #: a different floorplan is a different problem.
```

## `tracks/t3-topology/dse/veritx_dse/synthesis/event_objective.py`

line 12:

```text
# Script-mode safe import (RECLAIMED from the stronger lineage). This module
# advertises `python event_objective.py ...` and has a __main__ entry point;
# a bare package-relative import fails before argparse when run directly.
# Package import first, direct-script fallback second.
```

line 79:

```text
# Fallback weights when an event carries no priority of its own.
# NOTE: with frontier_timing.py output, priorities are SLO-DERIVED
# (decode=deadline-critical -> 1) and carried IN the events; these
# defaults only apply to legacy untimed streams.
```

line 120:

```text
            # Some algorithm moves unreachable on this topology.
            # Penalty MUST exceed any feasible cost (~1e9 here) or the
            # optimizer will prefer broken topologies.
```

## `tracks/t3-topology/dse/veritx_dse/synthesis/milp_topology_v2.py`

line 12:

```text
# Canonical constants — single source of truth in veritx_dse.core.constants.
# Script-mode safe: running this file directly has no package root on
# sys.path, so add the DSE root and fall back to literal defaults that
# MATCH the canonical values (never a different number).
```

line 55:

```text
# RECLAIMED, not re-invented. This loader is the hardened version from
# p1b/verified-evaluation / integration/p1-product (identical there),
# which the current tree had regressed to the older integration/canonical
# copy. A reclamation pass that "discovered" the old loader validated
# nothing and re-implemented the checks in SynthesisTrafficMatrix was
# duplicating work that already existed. SynthesisTrafficMatrix remains the
# CANONICAL authority (it additionally binds source provenance); this file
# parser is developer tooling and must not contradict it.
```

line 108:

```text
    # Enforce the radix budget on the SEED too: jittered interposer placements
    # can give a node 6+ nearest neighbors, violating radix (observed: maxdeg 6
    # at radix 5). Greedily drop the LONGEST edge at any over-degree node.
```

line 134:

```text
# R-expr: physical latency pricing. A link of length L pitches costs
# PIPELINE (router traverse) + L*WIRE. Replacing k short hops with one
# long express link saves (k-1)*PIPELINE - extra wire — the reason
# express topologies win when pipeline_depth > wire_per_pitch.
```

line 292:

```text
    # vars: x_e in {0,1} (add/keep link e); f_k^{e-in} flow of demand k on each directed link
    # We model per directed link; but undirected x controls both directions.
    # Directed edge index: (u,v). Build directed list.
```

line 314:

```text
    # NOTE: flow vars kept continuous (LP routing). Link binaries drive topology;
    # the LP relaxation of the latency objective is a valid lower bound and converges
    # fast (18k+ integer flow vars blow up). NetworkSmith-style: good link set > fast-enough solve.
    # for k in range(F):  # (disabled: integral flows too heavy)
    #     for e in range(E): integ[fv(k, e)] = 1
```

line 351:

```text
    # radix: degree at each node <= radix (undirected)
    #   sum over undirected links incident to node <==> base mesh + chosen extras
    #   degree = sum_{e in all_links, node in e} x_e
```

line 476:

```text
    # write anynet + json. The anynet text is DEVELOPER OUTPUT for this
    # standalone CLI; the canonical writer is model.topology_ir.to_anynet /
    # synthesis.candidate.anynet_projection. Format matches theirs exactly
    # (no trailing space) so a downstream reader cannot tell them apart.
    # (The historical delegation to synthesis.evaluator.write_anynet is
    # superseded: that module was removed; the engine must not import the
    # candidate layer, which would invert the dependency.)
```


# `synthesis` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/synthesis/candidate.py` :: `promote_to_explicit_topology`

```text

    WHAT PROMOTION IS: freezing the candidate's exact graph into a canonical
    `TopologyIR` (kind=custom) so it can enter a normal CompileRequest. That
    is all. It is NOT "mark the candidate verified" — nothing here claims a
    certificate, a measurement or a Pareto status.

    WHAT PROMOTION IS NOT: a second design type. The result is the SAME
    explicit topology an authored graph produces, so a synthesized design
    and a hand-authored one are indistinguishable downstream. Synthesis
    provenance is returned SEPARATELY as linkage.

    ORIGIN DOES NOT ENTER DESIGN IDENTITY. The returned TopologyIR carries a
    `name`, but `TopologyIR.scientific_dict()` excludes it, so the promoted
    graph and the identical manual graph have the same design_hash. Callers
    must attach `provenance` as metadata, never into the request's
    scientific fields.

    STALE PROMOTION REFUSES. Before freezing, the candidate is re-verified:
    schema, self-identity, definition identity, traffic identity, and graph
    integrity. A candidate that does not re-verify cannot become a design.
```

## `tracks/t3-topology/dse/veritx_dse/synthesis/candidate.py` :: `synthesize`

```text

    FAIL-CLOSED BOUNDARY. Everything the historical CLI would accept
    leniently is checked before the engine is called:

      * the traffic dimension MUST equal the definition's router count —
        the historical loader would happily solve a mismatched problem
      * every demand is already validated finite and non-negative by
        SynthesisTrafficMatrix
      * no uniform fallback exists at any point

    The engine is called UNMODIFIED. This function only translates.
```

## `tracks/t3-topology/dse/veritx_dse/synthesis/rho_grpo_adapter.py` :: `AdapterVocabularyPending`

```text

    Raised by to_topology_candidate() until the lead integrator widens
    the central vocabulary. The proposal identity is already
    candidate-identical, so widening changes nothing here.
```

## `tracks/t3-topology/dse/veritx_dse/synthesis/traffic.py` :: `SynthesisTrafficMatrix`

```text

    ``values[i][j]`` is the demand from router/endpoint ``i`` to ``j``.
    The diagonal MUST be zero: a node does not send to itself, and a
    nonzero diagonal would be silently dropped by every consumer while
    still moving the matrix identity.
```


# `synthesis` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/synthesis/candidate.py` :: `TopologyCandidate`

```text

    Carries NO certificate, NO performance, NO Pareto status and NO
    qualification — those are produced downstream by the ordinary pipeline.
```

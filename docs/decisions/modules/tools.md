# `tools` — extracted module rationale

Extracted from the module docstrings of `veritx_dse/{name}` by the 2026-09-29 debloat. Code keeps a one-line pointer; this is the original long-form text.

## `tracks/t3-topology/dse/veritx_dse/tools/chakra_to_dse.py`

```text
chakra_to_dse.py — Convert LLMServingSim text traces into DSE trace format.

Reads per-batch trace files from LLMServingSim's trace generator
(instance0_batch0.txt, instance1_batch0.txt) and emits time-stamped DSE
traces (cyc src cl dst sz) suitable for:
  - BookSim matrix derivation (evaluator._trace_to_matrix)
  - RTL replay via noc_frontend (trace_n%d.hex)
  - Dynamic trace mode in recommend.py (--trace)

Collective decomposition into point-to-point:
  ALLREDUCE:1,0     → ring: rank[i] → rank[(i+1)%N]
  ALLGATHER:1,1     → ring: rank[i] → rank[(i+1)%N] (MoE dispatch within EP group)
  REDUCESCATTER:1,1 → ring: rank[i] → rank[(i-1)%N] (MoE reduce within EP group)
  ALLTOALL:0,1      → permuted: rank[i] → rank[(i+ep_size)%N] (cross-EP-group)
  DP_ALLREDUCE      → ring between DP group members (cross-instance sync)
  REMOTE:0          → excluded (KV-cache remote memory, <0.1%)

Class assignment:
  0 = ALLREDUCE (TP collective)
  1 = ALLGATHER/REDUCESCATTER/ALLTOALL (EP dispatch/reduce)
  2 = DP allreduce (cross-instance sync)
  3 = REMOTE (excluded)

Usage:
  python3 chakra_to_dse.py instance0_batch0.txt instance1_batch0.txt \
    --npu-map "0,4,8,12,16,20,24,28,32,36,40,44,48,52,56,60" \
    --ep-size 2 --dp-group "0,1" --speedup 100 --out trace.trace
```

## `tracks/t3-topology/dse/veritx_dse/tools/deadlock_routing.py`

```text

deadlock_routing.py — M2: MCLB routing + deadlock certificate for a custom topology.

Given a topology (.anynet from milp_topology_v2.py) and a traffic matrix T:

  1. MCLB routing ILP (min max channel load): for each (src,dst) flow, choose the
     shortest-path route(s) that minimize the maximum channel load under T
     (NetSmith §3.4 "MCLB"). Emits a routing: first-hop table per (src,dst).
  2. Deadlock certificate: build the CHANNEL-DEPENDENCY GRAPH (CDG) of the
     resulting routing and check acyclicity (Dally–Seitz: an acyclic CDG for a
     routing subfunction => deadlock-free). If the CDG is acyclic, emit a PASS
     certificate. If cyclic, report the minimal set of channels that must be
     assigned to ESCAPE virtual channels (cycle-breaking=true), flagging where a
     VC-per-escape is required.

Uses scipy.optimize.milp (HiGHS) for the routing ILP. No Clab: routing here is
path selection over shortest paths (deterministic tie-break for a valid table),
matching the gen_route_tables.py convention (neighbors at anynet token idx 5,7,9).

Usage:
  python deadlock_routing.py --anynet /tmp/milp16.anynet --matrix /tmp/test16.mat --k 16 --out /tmp/cert
  python deadlock_routing.py --anynet <f> --matrix <m> --out <prefix> --method mclb|shortest|escape|booksim
  python deadlock_routing.py --anynet <f> --matrix <m> --out <prefix> --method booksim --export-table
```

## `tracks/t3-topology/dse/veritx_dse/tools/flow_certifier.py`

```text
flow_certifier.py — Flow-Class-Aware Certification Engine.

Named for what it does (certifies traffic-model flow classes against a
topology); formerly milestone_c.py, a plan-phase name that outlived the
plan.

Reads:
  1. Unified TrafficModel JSON (dse/models/traffic_model.json)
  2. Topology .anynet file (from synthesis or manual input)
  3. gen_rtl.py meta.json (for guardrail_hash, if available)

Emits:
  certificate.json — reviewer-verifiable proof that every flow class
  from the TrafficModel has reachability + latency-bound + injection-ceiling
  assertions whose deadline provenance is stated.

Design principle: the certificate schema dictates what we can assert.
deadline_cycles in the TrafficModel are bandwidth HINTS (bytes*8/100GB/s),
not hard timing contracts.  We derive LATENCY_BOUND from topology structure
(algorithmic hops × physical hops × pipeline cost) and compare against
the hint deadline.  A PASS means the topology CAN deliver within the
bandwidth-implied deadline under ideal conditions.

Usage:
  python3 flow_certifier.py \\
    --traffic-model dse/models/traffic_model.json \\
    --topology .noc_p0/custom.anynet \\
    [--meta .noc_p0/rtl_out/meta.json] \\
    [--out certificate.json] \\
    [--pipeline-cost 1.0]
```

## `tracks/t3-topology/dse/veritx_dse/tools/gen_serving_chakra_fixtures.py`

```text
gen_serving_chakra_fixtures.py — deterministic serving Chakra fixtures (R1).

The serving integration tests (``tests/test_full_pipeline.py``) originally
depended on a developer-local LLMServingSim run directory
(``third_party/llmservingsim/traces/run_...``) that is git-ignored and absent
from a clean clone, so six release-critical tests skipped. This tool replaces
that opaque, developer-local blob with a *deterministic* generator:

    canonical text trace (declarative, in this file)
        -> tracked Chakra LLMConverter
        -> .et fixture bytes (Chakra / ASTRA feeder_v3)

Properties required by the closure program (R1.2):
  * runs with no network access (pure local file reads/imports);
  * uses tracked source/config only (the converter is vendored under
    ``third_party/astra-sim/extern/graph_frontend/chakra``);
  * produces byte-identical output for identical input (there is no timestamp
    or absolute path in the encoded ``GlobalMetadata``), and
  * records a sha256 regression digest for every emitted file in
    ``MANIFEST.json`` plus the digest of the generator source itself.

Regenerate with::

    python3 -m veritx_dse.tools.gen_serving_chakra_fixtures

Verify committed fixtures are byte-identical to a fresh generation::

    pytest tests/test_serving_fixture_provenance.py

Semantics of the canonical cases
--------------------------------
Each ``.et`` file is one rank's Chakra node graph:

* ``event_handler`` — a single ``event_<alarm>ns`` COMP node per rank. This is
  the arrival alarm LLMServingSim feeds ASTRA; with ``alarm=1000`` ns the
  converter writes ``duration_micros=1`` and a replay-only run reports exactly
  1000 cycles at 1 GHz. Its shape matches LLMServingSim's
  ``trace_generator.generate_event``.
* ``dense_single`` — one rank, three compute layers, no collective
  (TP=1 / DP=1 inference).
* ``dense_tp2`` — two ranks sharing one tensor-parallel group; each rank runs
  the same layers and every dense layer is followed by an ALLREDUCE of the
  hidden state (TP=2).
* ``dense_tp4`` — the four-rank form of ``dense_tp2``.
* ``moe_ep`` — two ranks, expert-parallel dispatch (ALLGATHER) + per-rank
  expert compute + combine (REDUCESCATTER), the block shape emitted by
  ``trace_generator._emit_moe_block`` for ``allgather_reducescatter``.

Data-parallel serving is a *serving-layer* construct
(``ServingDataParallelGroup`` in ``backend/canonical_serving.py``); it does not
change the per-instance Chakra graph. It is qualified at runtime by
``tests/test_serving_dp.py`` and is deliberately not faked here as an
additional fixture.
```

## `tracks/t3-topology/dse/veritx_dse/tools/generate_studio_fixtures.py`

```text
Regenerate Srota Studio fixtures from the INTEGRATED engine.

Every view in apps/studio/fixtures/*.json originates from a live engine
object on this tree via the product gateways
(application/product_evaluator.py, application/views.py) — no
hand-written semantics, no hashes, no verdicts, no Pareto membership.
Envelope copy (title/description) is preserved from the existing files;
only values regenerate.

The optimization fixture is produced by the CERTIFIED entry point
``Optimizer.optimize_certified(request, definition,
backend_config=CertifiedBackendConfig(...))``. That is the only path
that can yield ``result_class == "CERTIFIED_PRODUCT"`` and bind the
product-controlled metric registry identity; ``optimize_with_port`` /
its ``optimize`` alias is analytic-only and is never used here.

The study is deliberately shaped so the REAL engine emits the full
candidate-state taxonomy the Studio must render (all values below are
engine verdicts, never authored): one eligible Pareto member, one
evaluated candidate failing a binding product requirement, one
evaluated candidate violating a hard optimization constraint, and
compile-refused candidates whose objectives/constraints are
UNMEASURABLE. ``main()`` asserts those states were actually produced.

Producer provenance: every evaluation here passes the fixture run root
as the producer ``repo_root``. The git revision of the harness checkout
is deliberately NOT recorded in fixture evidence: a committed fixture
can never name the commit that contains it (generating the artifact
changes the revision it would have to record), so recording the
checkout revision would make the fixtures non-reproducible at their own
commit. The exact executed producer stays pinned by
``booksim_binary_sha256``; the source fields are honestly recorded as
unavailable (``None`` — never invented), which is also why fixture
evidence is never eligible for the pinned-producer reuse path.

Usage: python3 -m veritx_dse.tools.generate_studio_fixtures
(from tracks/t3-topology/dse; needs a runnable BookSim binary for the
evaluated + study fixtures).
```

## `tracks/t3-topology/dse/veritx_dse/tools/memory_miss_model.py`

```text
Memory-class traffic generator (T3, D8 coupling model).

EXPERIMENTAL / ASSUMPTION_BASED (MEMORY-ROADMAP §2 quarantine): this is
research code, NOT certified system evidence. In particular `bank_contention`
implements a topology-invariant M/D/1 scalar that measured +0.0c on real
traces — it must not silently become comparison evidence. The `veritx compare
--memory` path that consumed it is deprecated and refused fail-closed; this
module's standalone `main()` report remains available as a research tool,
with all outputs to be read as experimental estimates.

Converts an LLMServingSim per-batch trace into *memory-class* traffic for the
fabric, alongside the collective traffic that trace_to_matrix.py already
emits. This is the analytical coupling D8 locked: memory misses enter the
same BookSim2 fabric as collectives, and contention is captured on one set of
routers.

Hierarchy (D10 structured spec, buyer-supplied capacities):
    regfile -> scratchpad (per-NPU, size S) -> shared L2 (per-die, size L)
             -> HBM (local) -> remote (fabric)

Which accesses become *fabric* traffic:
  * Scratchpad hit      -> stays inside the NPU, no fabric.
  * Shared-L2 access    -> crosses the die fabric (shared structure).
  * HBM access          -> local DRAM, no fabric.
  * Remote access       -> crosses the fabric to another die.

Model (per layer, capacity-miss approximation):
  ws = in_size + weight_size + out_size        # working set this layer
  scratchpad_hit = min(ws, S)                   # fits in per-NPU scratchpad
  l2_access     = min(ws - scratchpad_hit, L)   # spill to shared L2 -> FABRIC
  hbm_access    = max(ws - scratchpad_hit - L, 0)  # spill to local DRAM
  remote_access = 0                             # (extend when multi-die)

Output: an N x N traffic matrix (same format trace_to_matrix.py writes),
plus a JSON provenance file. The emitted matrix is the *memory-class* half;
add it to the collective matrix (element-wise byte sum) for the combined
fabric load D8 requires.

Validation hook: --scalesim <DETAILED_ACCESS_REPORT.csv> cross-checks the
model's per-layer HBM bytes against SCALE-Sim's DRAM reads+writes when the
same working set is run under its scratchpad config.
```

## `tracks/t3-topology/dse/veritx_dse/tools/multi_workload_pareto.py`

```text
multi_workload_pareto.py — traffic-aware Pareto evaluation.

Evaluates the same topologies across diverse workloads to find
traffic-robust designs. A topology optimized for mcast may be worse
on per-phase Mix — this quantifies it.

Usage:
  python3 multi_workload_pareto.py --traces runs/traces/qwen3_mcast_real.trace,runs/traces/hpc_wrf128_ring.trace --topos mesh_8x8,mecs64 --seeds 1
  python3 multi_workload_pareto.py --traces runs/traces/qwen3_mcast_real.trace,runs/traces/llama_1b_15all_960.trace --anynet runs/booksim/mecs64.anynet,runs/booksim/mot_64.anynet
```


# `tools` — extracted inline comments

## `tracks/t3-topology/dse/veritx_dse/tools/chakra_to_dse.py`

line 23:

```text
# Max flits per packet — realistic NoC packets are 8-16 flits (512B-1KB)
# Larger packets reduce header overhead but increase per-hop latency.
# 16 flits is the sweet spot: realistic and BookSim handles it in 30s.
```

line 140:

```text
        # Convert bytes to flits, then split into packets
        # pkt_flits is the actual flit count per packet
        # n_pkts is how many packets we need to transfer all the data
```

line 146:

```text
        # Conservation: every packet carries full pkt_flits EXCEPT the
        # last, which carries the remainder — total emitted flits ==
        # size_flits exactly (no fabricated bytes for non-multiples).
```

## `tracks/t3-topology/dse/veritx_dse/tools/deadlock_routing.py`

line 298:

```text
    # Absolute import: this module runs in three contexts (package,
    # importlib bare-module, direct script) and veritx_dse is importable
    # in all of them (editable install).
```

line 401:

```text
        # Phase 10: the certificate carries the content-addressed
        # RouteArtifact (hash-verified on load) alongside the CSV diff
        # seam — consumers reference the artifact hash, not the file.
```

## `tracks/t3-topology/dse/veritx_dse/tools/flow_certifier.py`

line 127:

```text
    # Known saturation points from BookSim validation (PLAN §Test 5):
    # mesh_4x4: saturates ~0.45
    # synthesized T3: saturates ~0.45
    # We use 0.40 as conservative ceiling (80% of saturation).
```

line 149:

```text
    # Import from gen_rtl.py (same codebase). Path is computed relative to
    # THIS file (veritx_dse/tools/) so it works no matter where the repo root is:
    # veritx_dse/tools -> veritx_dse -> dse -> t3-topology -> scripts/rtlgen.
```

line 260:

```text
        # Injection check for this class
        # Per-class IR = total_bytes_per_batch / (nodes * cycle_time)
        # Simplified: invocations * bytes_per_invocation across all instances
```

## `tracks/t3-topology/dse/veritx_dse/tools/generate_studio_fixtures.py`

line 37:

```text
    # One transport root for this regeneration. The evidence paths are
    # transport, never science; identities remain content-derived. The
    # tree is removed once every view has been projected.
```

line 155:

```text
        # Binding ceiling set inside the measured spread of the real
        # 4-tile mesh so the engine itself separates the candidates:
        # the widest link configuration passes, narrower ones exceed it.
        # Engine verdicts, asserted below.
```

## `tracks/t3-topology/dse/veritx_dse/tools/multi_workload_pareto.py`

line 14:

```text
# ── Auto-timeout budget (per-trace, not flat) ────────────────────────────
# A flat wall-clock cutoff measures the host, not the fabric: a 668k-packet
# serving trace and a 20k-packet slice need wildly different budgets, and a
# cutoff tuned for the small one labels every big-trace run TIMEOUT — the
# failure then reads as a topology property when it is a benchmark property.
# Budget = base + TIME_BUDGET_PER_PKT × packets, floored/clamped.
```

line 103:

```text
    # Prefer honest latency (arrival - trace timestamp). The stock plat
    # mean is ctime-based: qtime slots go stale across idle gaps. Falls
    # back to plat for pre-honest_avg binaries. First phase wins, same as
    # the old plat-only behavior (max_samples>1 prints per phase).
    # Phase 2a: thin wrapper over the shared evaluator parser (identical
    # semantics: honest-first, plat fallback, first-match). Kept because
    # tests import it directly.
```

line 343:

```text
    # TRUE trace replay (8b19afeb): exact timestamps, full trace.
    # latency_thres must exceed real latency (default 500 aborts) — 1e6.
    # sample window sized so max_samples*period > span + drain.
```

line 347:

```text
    # use_noc_latency lives ONLY on the GEC branch: it forces 1-cycle channels
    # in kncube.cpp, which is correct for GEC taps but understates torus link
    # latency (2c) everywhere else. The canonical builder (simulation/booksim.py)
    # scopes it the same way — keep pareto numbers comparable with compare/.
```

line 379:

```text
            # Canonical mesh: 2*k*(k-1) for 2D (112 for k=8), else
            # n*(k-1)*k^(n-1). Kept here only for standalone use
            # without an install; primary path is _canonical_size above.
```

line 721:

```text
                # A trace addressing nodes the topology doesn't have would run
                # degraded (BookSim skips out-of-range entries) and record junk.
                # Skip up front with the reason instead of burning the run.
```

line 752:

```text
    # Aggregate per topo per trace (mean over seeds)
    # Build per-topo vector: {name, edges, latency[0], latency[1], ...}
    # Classification audit first: a table mixing OK rows with silent
    # NO_METRIC rows is how scoreboard lies get shipped.
```

line 787:

```text
    # Pareto on per-trace latencies + edges (Phase 8: scope-stated).
    # The ok-only restriction is now an explicit, reported exclusion —
    # every requested candidate stays visible in the table (fail rows
    # print below) and pareto.json carries the evaluated scope. This
    # tool compares single-backend BookSim rows with legacy provenance:
    # the output is marked uncertified (LEGACY scope), never a certified
    # Pareto claim. Certified comparisons go through core.comparison on
    # immutable runs.
```


# `tools` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/tools/chakra_to_dse.py` :: `generate_dp_allreduce`

```text

    Each instance computes independently, then syncs via ring allreduce.
    The DP allreduce happens AFTER all per-instance ops complete.

```

## `tracks/t3-topology/dse/veritx_dse/tools/memory_miss_model.py` :: `bank_contention`

```text

    The fabric routers handle *routing* contention (BookSim2 captures it);
    the L2 banks are a SEPARATE serialization point: every miss arbitrates
    at its home bank. This is the explicit analytical coupling D8 requires —
    we add the bank queueing delay to the fabric latency rather than max()ing
    the two.

    Per bank: arrival rate lambda = bytes_banked / cycles,
    service rate mu = bank_bw_bytes_cycle. M/D/1 mean queueing delay:
        W_q = rho / (2 * mu * (1 - rho)),  rho = lambda / mu
    Returns per-access added latency in cycles (fractional OK; BookSim2
    latency is in cycles).
```

## `tracks/t3-topology/dse/veritx_dse/tools/memory_miss_model.py` :: `emit_matrix`

```text

    Shared L2 is banked across the die (D10 hierarchy). A miss from node s
    lands on the bank covering its tile of the address space. With `banks`
    banks distributed round-robin over the node ids, node s's misses go to
    the local bank group -- a SHORT-hop, locality-biased pattern, unlike the
    all-pairs collectives. This spatial difference is what makes memory
    traffic change the fabric ranking (F6 thesis).

    Bank placement: bank b sits at node round(b * N / banks); node s hashes
    to the bank covering its address tile (s * banks // N).
```

## `tracks/t3-topology/dse/veritx_dse/tools/multi_workload_pareto.py` :: `aggregate`

```text

    The module's deep seam for the audit fixes: classification, per-trace
    normalization, common-successful-set discipline, and the normalized
    geomean — all here, no printing, no IO, so tests and CLI cross the
    same surface.

    Interface:
      results     eval_once-shaped dicts (name, trace_name, latency, …)
      topo_names  display order of topologies (agg rows follow it)
      trace_keys  deduped trace stems
    Returns (agg, meta):
      agg[i]      one record per topology: name, nodes, edges, lat_<trace>
                  (seed-mean), mean_lat (raw arithmetic mean over whatever
                  ran — legacy, kept for pipeline.py tables, NOT a ranking
                  metric), ok (succeeded on every trace), n_common (the
                  common successful trace set), geomean (ranking metric;
                  None unless the topology succeeded on every common trace)
      meta        {"classes": verdict -> ["topo/trace"],
                   "common_ok": set of traces any topology succeeded on,
                   "baseline": trace -> best latency across topologies}

    Why geomean-of-ratios: a raw arithmetic mean lets the biggest-number
    trace dominate the ranking and silently compares different trace
    populations when runs fail. Normalizing per trace (latency / best)
    gives every workload equal influence; the geometric mean of ratios is
    the scale-free mean across workloads. Computing it only over the
    common successful set means every ranked topology is scored on the
    SAME workloads — comparable by construction. A shrunken common set is
    surfaced to the user (main prints it), never silently absorbed.
```


# `tools` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/tools/deadlock_routing.py` :: `assert_unit_weights`

```text

    Returns nothing; raises SystemExit via main()'s caller convention —
    actually raises ValueError here so both CLI and library callers can
    handle it.
```

## `tracks/t3-topology/dse/veritx_dse/tools/deadlock_routing.py` :: `escape_routes`

```text

    rank[root]=0, rank increases with BFS level. A flow s->t is routed along the
    tree via their LCA: s climbs up (rank decreasing) to the LCA, then down to t.
    Every tree edge is oriented parent(child) = lower(higher) rank; "down" edges
    always go rank r -> rank r-1. Because we only ever move UP a tree (and DOWN
    strictly toward the LCA), the escape subfunction is a tree => its CDG is
    acyclic => packets can always drain on the escape class => deadlock-free by
    construction. Returns bestp: {(s,t): full path}.
```

## `tracks/t3-topology/dse/veritx_dse/tools/deadlock_routing.py` :: `parse_anynet`

```text

    History: this parser used to scan only single-line files and dropped
    reverse edges, so two-line link files parsed as DIRECTED graphs —
    CDG analysis on configs/anynet16.links was silently wrong.
```

## `tracks/t3-topology/dse/veritx_dse/tools/memory_miss_model.py` :: `validate_scalesim`

```text

    SCALE-Sim streams compulsory fills (DRAM reads/writes) under its own
    scratchpad config; our model splits the same working set across
    hierarchy levels. Conservation: total model traffic (scratch + l2 + hbm)
    must equal SCALE-Sim's SRAM + DRAM access bytes for the same working set.
    The ratio is reported per-level so capacity vs compulsory is visible.
```

## `tracks/t3-topology/dse/veritx_dse/tools/multi_workload_pareto.py` :: `_canonical_size`

```text

    Thin wrapper over :func:`veritx_dse.model.presets.topo_size`:
    Topology-object form when the name resolves in the registry,
    otherwise backend+params-dict form. Returns None when presets isn't
    importable (standalone use); callers then fall back to their legacy
    inline table.
```

## `tracks/t3-topology/dse/veritx_dse/tools/multi_workload_pareto.py` :: `_validate_trace`

```text

    Returns a dict recorded into the pareto.json header. The unique-node
    count is a WARNING, not a gate — a genuinely 4-NPU serving trace is a
    legitimate workload — but the active coverage is now written down next
    to every result, so nobody reads a 64-node topology comparison off a
    trace that exercises 4 endpoints (the audit's point #1).
```

## `tracks/t3-topology/dse/veritx_dse/tools/multi_workload_pareto.py` :: `eval_once`

```text

    Phase 2a: delegates to the shared evaluator with PARETO_PRESET
    (sample_period=max(50000, span+10000), max_samples=5,
    sim_type=latency, honest-first latency key). Signature and legacy keys
    preserved; canonical SynthResult fields (status/backend/provenance/
    extra) merged ADDITIVELY. The pareto.json record boundary therefore
    carries status/error with latency=None on failure (no float sentinel
    was ever used here).
```

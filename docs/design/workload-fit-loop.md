# Workload → hardware fit loop

Status: contract + resolver (implemented in `apps/studio/prototype/src/agentMap.ts`,
`checkWorkloadFit` / `sizeM2FromEnvelope`). The Python lowering side
(`veritx_dse/workload/intent_lowering.py:198-357`) is referenced, not changed.
Audience: compiler + studio implementers.

Goal: a workload change must not regenerate RTL when the same design still
fits. The workload envelope constrains **capacity only**; everything the
workload cannot change stays fixed at synthesis time.

## 1. Three kinds of fact (hard vs envelope vs tuning)

| Kind | Contents | Set by | Changes per workload? |
|---|---|---|---|
| **Hard semantics** | Routing law (DOR / dateline / MECS / shape…), VC counts + deadlock-freedom proof (`derive_vc_assignment_v3`), address decode, protocol ordering promises, CDC gating | Topology intent, at design synthesis | **Never.** Workload-independent by construction |
| **Envelope** | Capacity bounds: outstanding budget, burst split threshold, concurrency, dependency-count, bandwidth ceiling, achievable latency | Design synthesis (the design stores its envelope) | No — the design envelope is fixed; the *workload* envelope is checked against it |
| **Tuning degrees** | Arbitration policy, credit thresholds, buffer split per VC, M2 target sizing | Per-compilation, re-checked cheaply | Yes, without new hardware |

The workload lowering emits a dependency graph, not hardware:
collectives expand into ordered groups, compute stages chain sequentially,
traffic profiles become p2p operations (`intent_lowering.py:245-334`), and
provenance (`design_hash`, `:349-363`) binds the graph to the design it was
lowered against. The fit loop sits between that graph and the design: the
graph's *demands* are turned into the workload envelope, and the resolver
asks whether the design's *capacity* absorbs them.

## 2. The workload envelope (demand side)

The envelope is six componentwise demands — no fabricated defaults, no
averaging away the peak:

| Dimension | Meaning | Source in the lowering |
|---|---|---|
| `burstiness` | Longest burst the workload issues, in flits | Collective payload + traffic-profile sizes |
| `concurrency` | Peak concurrent actors / streams | `ParallelismShape` world size / group expansion |
| `outstandingDemand` | Peak outstanding requests | Issuer MLP demand across the graph |
| `dependencyCount` | Count of ordering edges | Compute/collective/coherence op chains |
| `latencyBudgetNs` | Tolerated end-to-end latency | Declared workload latency ceiling |
| `bandwidthDemandGbps` | Sustained bandwidth demand | Payload × frequency of collectives/profiles |

## 3. Consuming the envelope

### (a) M2 sizing — `max_outstanding` / `split_at`

M2 is sized deterministically from the envelope (`sizeM2FromEnvelope`):

```
maxOutstanding = max(1, ceil(outstandingDemand))
splitAt        = max(1, ceil(burstiness))
```

That is, the design's outstanding budget covers the bursty peak exactly:
one maximal burst can never exceed the budget it is split against. The
design *stores* its M2 sizing alongside its envelope; the resolver compares
a new workload's demands against those stored numbers — it never re-derives
hardware from a workload on the fly.

### (b) The fit verdict — stored on the revision

The resolver (`checkWorkloadFit`) returns a three-way verdict plus a
componentwise evidence table, stored on the revision beside the compile
verdicts:

| Verdict | Meaning | Action |
|---|---|---|
| `satisfied` | Same workload hash, envelope within capacity | Nothing; checks re-run pass |
| `same-design-fits` | Workload **changed**, every demand within capacity | **No RTL regeneration.** Re-run checks + M2 sizing confirmation only |
| `needs-re-synthesis` | Any demand exceeds capacity | Re-synthesize for a larger envelope; `exceeded` names the dimensions |

Evidence table (demand vs capacity, per dimension) — the operator sees
exactly which dimension overflowed, never just "no fit":

```
outstanding (M2 max_outstanding): needs 64, design carries 32, fits: no
burstiness (M2 split_at):         needs 2048, design carries 4096, fits: yes
concurrency:                      needs 128, design carries 256, fits: yes
dependency ordering:              needs 200, design carries 512, fits: yes
latency budget (ns):              budget 500, achieved 900, fits: no
bandwidth (GiB/s):                needs 128, design carries 96, fits: no
→ needs-re-synthesis · outstanding, latency, bandwidth exceeded
```

## 4. Why same-design-fits does not regenerate RTL

Synthesis identity is the design hash over **hard semantics + the capacity
envelope** — routing law, VC assignment, decode table, and the bounds in
§2. A workload change that lands inside those bounds alters neither half:
the routing law still routes the same dependency classes (VC assignment
admission, `assert_traffic_classes_bound`, is a per-class membership check,
not a per-workload re-derivation), the decode still covers the same
windows, and the M2 budget still covers the burst peak. Regenerating RTL in
that case would produce a bit-identical design at full synthesis cost — the
resolver exists to prove that sameness componentwise instead of assuming
it. Only `needs-re-synthesis` (a demand above a stored bound) justifies new
hardware, and then only for the exceeded envelope, not for the workload
identity itself.

Flag: this proof is sound only because every capacity dimension is
componentwise and monotone — more outstanding, more burstiness, more
bandwidth are always worse, never cheaper. A dimension where *less* demand
were harder (a floor, not a ceiling) would break the check and is therefore
not modeled as an envelope dimension.

## 5. Family scope (audit §6)

The envelope check is family-agnostic: all 12 families
(`mesh-stage1-schema-compiler-scope.md` §6) share the same six dimensions
and the same componentwise comparison. The only per-family input is the
routing-law object, which lives entirely in hard semantics. A family whose
workload cannot be expressed in these six dimensions is a STAGE 1 bug, not
a family exception.

## 6. Address precision (companion change)

Address parsing is BigInt-canonical, not Number-based: `parseAddressBigInt`
(`agentMap.ts`) parses hex/decimal into an exact `bigint` over the full
unsigned 64-bit space; `parseAddressCanonical` renders the exact decimal
string for the wire. `parseAddress` (safe-number wrapper) widens to `Number`
only after a BigInt bound check against 2^53−1, so it is exact or refused —
never rounded — including at the 48-bit ceiling (2^48−1) and for HBM bases
past 2^53 (e.g. `0x20_0000_0000_0001`), which the wrapper refuses and the
canonical path carries exactly. Covered in `agentMap.test.ts`.

## 7. Non-goals

- No workload → RTL generation path in this change; the verdict is
  advisory until the gateway persists it on the revision.
- No estimation loop (no latency/bandwidth prediction from the envelope);
  achieved numbers come from the compiled design, demands from the workload.
- No change to `tracks/t3-topology/dse` (scope split); Python lowering
  semantics are referenced as-is.

## 8. One-click reproduce of the composed slice

The exact slice revision this fit loop covers (mesh 2×2, `HBM0`
[0x1000,0x2000), AXI4 subset DATA_W=32) has a one-click regenerate +
hash-verify path:

```bash
make -C tracks/t3-topology slice  #  needed verilator for lint+sim
scripts/reproduce_slice.sh        #  equivalent; re-checks every manifest hash
scripts/verify_slice.sh           #  re-checks hashes + verdicts only
```

Regeneration drives `veritx_dse.product.project_top_rtl.run_rtl_slice`
(preview + compose + Verilator lint + TB sim + manifest + zips) with the
pinned request (`design_hash b078985e…`); then `verify_slice` recomputes
every file hash against `project-top-manifest.json`, re-runs the RTL
`lint-slice` target, and refuses to pass a stale or drifted slice. The
fit-loop companion: a workload change inside the design envelope yields
`same-design-fits` (no RTL regeneration, §4) — the reproduce is only
needed when the slice itself is re-derived.

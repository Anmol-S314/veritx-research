# Analytic Cut Model — Bridge-Fork as a Replication Placement Problem

Status: DRAFT (paper §5 material; validated against measured cells, 2026-08-13)
Owner: Laura (opencode senior)
Source data: `paper_draft.md` §4a/§4b (BookSim), UCIE-ARC.md, gate cells verified in RTL
2026-08-13 (on-axis T52 / off-axis T87, +35 cycles, 154/154 zero mismatches at tol=0)

---

## 1. The cut abstraction

A two-die chiplet accelerator presents a **heterogeneous network**:

```
Die A NoC → [bridge: capacity-constrained cut] → Die B NoC
```

The bridge is not "a router hop with a label" — it is a **cut** in the graph sense
with three properties that no ordinary NoC link has:

1. **Limited bandwidth** — the entire inter-die traffic crosses it;
2. **No bypass** — traffic cannot be re-routed around it;
3. **Serialization point** — its utilization is a direct function of how much
   replication happens before vs after it.

Multicast traffic crossing the cut has a binary choice:

- **Fork before the cut (source-fork):** the sender replicates; the bridge
  carries g copies.
- **Fork after the cut (bridge-fork):** the bridge carries 1 copy; the
  destination-side NoC replicates to its g cores.

The mechanism is *where the replication point sits relative to the cut* — not
the existence of multicast itself (which is taken at the on-chip rung, cf.
FlatAttention; and vendor-shipped at the intra-chip rung, tt-metal PR #40733).

---

## 2. Theorem 1 — Cut-load scaling (the g-fold saturation win)

**Setup.** One multicast source, g destinations on die B, single bridge of
capacity B_b (flits/cycle), remote NoC headroom B_r.

**Source-fork.** Bridge demand per multicast event = g flits. The bridge
saturates when the multicast injection rate λ satisfies

```
λ_sat,source ≈ B_b / g
```

**Bridge-fork.** Bridge demand per event = 1 flit (the stream). The bridge
saturates at

```
λ_sat,bridge ≈ B_b
```

**Ratio.**

```
λ_sat,bridge / λ_sat,source ≈ g
```

**Measured validation (BookSim, 2-die 8×8, g=8, one bridge):**

| rate | source-fork lat | bridge-fork lat |
|---|---|---|
| 0.008 | 80.5 | 78.0 |
| 0.016 | **119.7 (knee)** | 77.9 |
| 0.032 | **497.7 (saturated)** | 78.6 |
| 0.064 | 376.2 | 80.7 |
| 0.128 | 366.6 | 119.4 |

- Source-fork knees at ~0.016, saturates at ~0.032 → λ_sat,source ≈ 0.016–0.032.
- Bridge-fork holds ~78 cycles flat to 0.064, first diverge at ~0.128.
- The measured ratio of saturation points ≈ 0.064/0.008 = **8× = g**, matching
  Theorem 1. (Known-answer gate: the JSON verdict's g-fold reading; the loose
  "2× the knee" phrasing in the draft is superseded by this closed form.)

**Note on the post-saturation fall (497.7 → 376.2 → 366.6).** This is the
traffic-manager's accepted/injected < 1 throttling, not a network speedup. The
paper must state this explicitly (measured, already flagged in paper_draft §4a
open items).

---

## 3. Theorem 2 — Placement penalty (ΔL = ΔH × L_hop)

**Setup.** Bridge-fork, 1 copy crosses the cut, fork fires on the destination
die. The bridge ingress lands at (BRIDGE_ROW, BRIDGE_COL) on die B; the
multicast row is row 0. On-axis: BRIDGE_ROW = 0. Off-axis: BRIDGE_ROW > 0 —
the stream must climb (S−1) rows before the row sweep can begin.

**Latency decomposition.** End-to-end multicast latency (first copy):

```
L = L_src_path + L_bridge + L_climb + L_sweep
```

The placement changes only the climb term:

```
ΔL = L_off − L_on = ΔH × L_hop
```

where for the row-multicast geometry the off-axis climb is exactly the die
height in hops:

```
ΔH = S − 1
```

and L_hop is the measured per-hop pipeline cost (5.0 cycles: 4 router stages +
1 channel, RTL-ARC §3).

**Closed form:**

```
ΔL = (S − 1) × L_hop          [cycles]
```

**Measured validation (BookSim):**

| die (S×S) | g | on-axis | off-axis | penalty | (S−1)×5 |
|---|---|---|---|---|---|
| 8×8 | 8 | 67.0 | 102.0 | 35 | 35 |
| 16×16 | 16 | 127.0 | 202.0 | 75 | 75 |
| 32×32 | 32 | 247.0 | 402.0 | 155 | 155 |

**RTL validation (2026-08-13, full committed tree, tol=0):**

| cell | first copy | stream far end | penalty |
|---|---|---|---|
| on-axis (BRIDGE_ROW=0) | T52 | T82 | — |
| off-axis (BRIDGE_ROW=7) | T87 | T117 | **+35 = 7×5** |

Both cells: 22 streams → 154/154 ejections, zero per-flit mismatches. The RTL
reproduces the closed form to the cycle.

**Scope discipline.** The 5.0 cyc/hop constant is this router's pipeline, not a
physical law. The *structure* — ΔL = ΔH × L_hop with ΔH = S−1 — transfers to
any single-sender row multicast; the constant changes with microarchitecture.
"Load-independent" is claimed only for the tested contention-free regime;
multi-stream independence is unmeasured (contention experiment, T3-004).

---

## 4. The design rule

The bridge port is a **floorplanning decision made once**, priced per crossing:

> The bridge port must sit on the multicast row's axis of the remote die, or
> every KV crossing pays the die-height hop count.

On 8×8 that is 35 cycles; on 32×32, 155. In the decode-critical path, per
token. Bridge-fork makes placement a *first-order* parameter: with source-fork
the remote fork does not exist and the bridge saturates first anyway; with
bridge-fork + on-axis placement, both the g-fold win and the minimum crossing
latency hold simultaneously. It is the only cell where both do.

---

## 5. Generality — the "Fork After the Cut" principle

The mechanism is not KV-specific. Any replicated state crossing a
capacity-constrained cut has the same two placements:

- KV-cache distribution across dies (this paper's motivating workload);
- MoE expert dispatch (token → g experts on the far side);
- embedding/parameter broadcast;
- any multicast tree crossing any bandwidth-constrained inter-die cut.

The general statement (novelty framing for the paper):

> Given a multicast communication tree crossing a bandwidth-constrained
> inter-die cut, place the replication point after the cut whenever the
> downstream fabric has sufficient capacity.

KV is the motivating workload; the principle is the contribution.

---

## 6. What the model does NOT cover (honest bounds)

1. **Contention / multi-stream.** Theorems 1-2 are single-stream. The
   multi-stream regime is unmeasured (the two-class cell shows contention
   jitter of −1..+3 cycles at the envelope tier); the contention experiment
   (T3-004) is the open item.
2. **Multi-flit multicast.** The RTL fork replicates the head flit only
   (F3). All cells are packet_size=1; multi-flit rows are out of scope until
   F3 is closed or declared in the paper's threats.
3. **Saturation behavior of bridge-fork.** λ_sat,bridge ≈ B_b assumes the
   remote NoC headroom B_r ≥ g×B_b; a bandwidth-starved remote die would
   shift the knee. This is the model's one parameterized assumption.
4. **Bridge PHY/protocol.** UCIe pJ/bit is unsourced; the bridge is modeled
   as a 2-stage channel (matching every other link in the RTL). No energy
   claims at the die boundary.

---

## 7. How the paper should use this

- §5 Analysis: state Theorems 1-2 as the model; the simulation tables become
  *validation of the model*, not the model itself.
- Report both BookSim and RTL numbers side by side (both exist, both
  tol=0-clean on the placement cells).
- The "35-Cycle Law" title is dead (the constant is router-specific); the
  closed form ΔL = (S−1)·L_hop is the claim.

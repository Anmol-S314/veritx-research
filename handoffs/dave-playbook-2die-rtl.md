# DAVE PLAYBOOK — 2-DIE BRIDGE RTL VERIFICATION (hard-won lessons)

Author: Dave (opencode senior), 2026-08-15. Everything here cost real time
to learn. Read before touching the 2-die RTL or the bridge cells.

---

## 1. TRACE FORMAT (the #1 source of phantom bugs)

The R1 trace hex format is EXACTLY 16 hex chars per entry:
`{cycle:08x}{cl:02x}{dst:02x}{size:04x}` = cycle(8) + cl(2) + dst(2) + size(4).
**NOT** 8+8. A wrong split (`0000000a00004001` instead of
`0000000a00400001`) silently decodes dst=0 size=0x4001 — the flit fires
with the wrong dst and "vanishes" (it's routing somewhere sane-looking but
wrong). ALWAYS generate hex from the trace with the reference generator
(fork_gate_sweep.py's gen_hex), never by hand.

Mcast entries have a SECOND line (the range word):
`00000000{lo:02x}{hi:02x}0000` (cycle=0 marks it as a range word, not an
entry).

## 2. THE REPLAY-BASE SHIFT (why "nothing fires" is often "fires later")

The TB pre-shifts every trace entry's cycle by
`replay_base = tck[0] + ND*N*T_DEPTH` before pumping it into the NIC BRAM.
- ND=2, N=64, T_DEPTH=2048 → shift = 262,144 cycles. **run_cycles must be
  > replay_base + last_trace_cycle + drain**, or the packets never fire.
- T_DEPTH=64 → shift = 8,192 — this is why small T_DEPTH makes everything
  fast AND correct for gate cells.
- The NIC's fire check: `(tick_r + 1) >= trace_mem[tptr][63:32]` (shifted).

## 3. T_DEPTH (build parameter, NOT a simulator knob)

- `-GT_DEPTH=64` on 2-die builds: 30× lighter builds AND 30× faster sim
  (pump 262K→8K cycles). The 2048 default is the OOM class (~8GB, 60min).
- **T_DEPTH must be ≥ the max entries in any trace_n*.hex** — the 5718-pkt
  cell has up to 59 entries/NIC → needs 64. Overflow fails with
  "$readmem file address beyond bounds of array" (a clean abort, not a hang).
- T_W must match: the TB computes it from T_DEPTH (5 for 64, 11 for 2048).

## 4. BRIDGE COLUMN (the config-mismatch trap that cost a day)

The fork-gate PROTOCOL uses **BRIDGE_COL=0** (bridge at die-A (7,0) ↔
die-B (0,0)) with anynet bridged_2die_onaxis.anynet (bridge link 56↔64).
The bridged_2die.anynet has the bridge at COLUMN 3 (59↔67). **Mixing them
looks like a deadlock**: with col-3 RTL but col-0 trace semantics, die-B
row-0 copies 65,66 lie WEST of the entry and are unreachable → 44/154
copies lost → "1-VC deadlock". The RTL was fine; the configs disagreed.
ALWAYS verify: bridge link in the anynet == BRIDGE_COL/BRIDGE_ROW in the
build.

## 5. CREDIT LOOPS (and the F8 family)

- The bridge has TWO credit loops: A→B (br_c1/c2 from die-B's W credit-out)
  and B→A (br_c1b/c2b from die-A's E credit-out). Crossed lanes = die-A
  self-allocates 8 credits and stalls on the 9th (commit b8531ac fixed this
  once — don't regress it).
- Credit return is 2-stage (br_c1 → br_c2). The CreditBased rule (arXiv
  2607.01430 §III-3): **downstream FIFO must be ≥3 deep** to absorb the
  credit-return latency. The bridge was 2-deep (br_f1, br_f2) — added
  br_f3/br_f3b (commit 9ae11d1). Below 3, one direction starves under
  bidirectional contention.
- The credit_free[PORT_L] (eject credit) can drift to saturation if the
  eject credit is unconditional and the FIFO/copy path double-counts
  (Laura's F8 leak family). Check `DBG5` cf values — `cfL8` is healthy,
  `cfL0` with occ>0 is a leak.

## 6. THE FIRE/VC LOG TRAPS

- FIRE prints `Y * X_DIM + X` — the NIC's LOCAL coordinates. die-A NIC 1
  and die-B NIC 65 BOTH print "FIRE n1". **You cannot distinguish die-A
  from die-B by the log alone** — use the dst field or DBG3's D0/D1 prefix.
- The VC line (head inject) proves `inject_valid` was asserted. If FIRE
  exists but no VC line, the packet fired but never injected (credit).
- `injected` in R1 totals counts NIC-side injects; `ejected` counts
  router-side deliveries. injected >> ejected with delivery ≈ 0 = genuine
  stall; injected ≈ trace count with ejected ≈ 0 = flits die in the network.

## 7. DBG PORT-INDEX LESSONS

- DBG3/DBG4/DBG5 had a port-index bug (reading input-indexed arrays as
  output-indexed) — fixed in F9 (409f1f7) and F9-bis (junior). The audit
  readout at END-of-run shows POST-DRAIN state (network empty) — occ/recv
  there are TOTALS, not the stuck state. To see the STUCK state you need
  mid-run reads (the PROG lines give eject counts over time — a plateau =
  stall).
- The DBG3 port order: 0=LOCAL, 1=E, 2=W, 3=N, 4=S (per noc_pkg.sv
  PORT_* constants).

## 8. THE BUILD-COLLISION WAR (4 incidents, now codified)

- **The box kills concurrent builds, not backgrounded ones.** Every
  "Terminated" mid-make was another agent's build (8-9GB) colliding with
  mine at 14GB total. NOT session cleanup.
- Rules in GATE-R1-COORD §8: unique per-agent Mdir names, mandatory
  -GT_DEPTH=64, `pgrep -c verilator` must be 0 before launching, free > 6GB
  before VCS≥4, GVCS=8 = 9GB never concurrent.
- **NEVER pkill/rm a dir you didn't create.** Someone's `pkill -f d3clean`
  + shared Mdir killed my builds twice.
- The detached-launch pattern that works:
  `setsid nohup script.sh < /dev/null > /dev/null 2>&1 &`

## 9. THE BIDIRECTIONAL BRIDGE STARVATION (the paper-worthy finding)

- Symptom: symmetric load, A→B 11% vs B→A 82% on the 2-deep bridge.
- Root cause chain: 2-deep bridge + 2-stage credit return < 3-flit
  CreditBased minimum → one direction starves → backs up into die-A's
  LOCAL buffers (occ=32) → global stall.
- The isolation approach (VA-restriction, attack Coffman's mutual
  exclusion) FAILED — it broke credit correlation and starved A→B worse
  (0/4). The depth-3 (attack hold-and-wait via buffer depth) WORKED (4/4).
- Reference: Preemptive VC (arXiv 2607.01430, Benini group, FlooNoC) —
  attacks Coffman's no-preemption; our depth-3 is their CreditBased rule.
- Small-cell-first discipline is mandatory: the 8-pkt cell caught the
  isolation regression in one run that the 5718-pkt cell would have
  confounded.

## 10. ROUTE TABLES (gen_route_tables.py)

- BookSim min_anynet = Dijkstra with std::map tie-break (ascending
  neighbor id, strict <). Python's min() over a set is ARBITRARY on ties —
  use `min(sorted(unvisited), key=dist)` to match.
- Anynet port numbering is FILE-ORDER, not geometric. The bridge link must
  be special-cased (die-A exit = E, die-B entry = W). A geometric-only
  derivation silently emits ports to links that don't exist (e.g. die-B
  (0,3)=67's W is the bridge, not a mesh link).
- The Dijkstra-exact table is NOT needed for the gate (the DOR routing
  passes); it's a reference tool + for future non-DOR topologies.

## 12. THE PHANTOM MESH EAST LINK AT THE BRIDGE NODE (B→A loop, 2026-08-16)

**THE B→A "vanishing flit" mystery is SOLVED — it was never a credit or
turn-map issue. It's a routing divergence into a bridge loop:**

- BookSim's anynet has BOTH `router 56 router 57` (mesh east, die-A row 7)
  AND `router 56 router 64` (the bridge) at die-A (7,0). The RTL SUPPRESSES
  the mesh east link (noc_2die.sv:164 — PORT_E at the bridge node IS the
  bridge). So the RTL topology has NO path from (7,0) to (7,1).
- route2d (DOR mode, no -DTWO_DIE_ROUTE_TABLE) didn't know: xy_dor at
  (7,0) returns PORT_E for ANY x>0 die-A target → the flit enters the
  bridge A→B direction → die-B (0,0) sees dst<64 → PORT_W → back across
  the bridge → die-A (7,0) E-in → PORT_E → **infinite loop through the
  bridge pipe**. Both bridge ends valid ~every cycle (recv≈8300 ≈ run
  cycles), die-A (7,1),(7,2),(7,3) recv=0, only x==0 targets delivered.
- This is the SAME ab55/F14 class Steve found: anynet links the RTL doesn't
  have. gen_route_tables.py's enforce_rtl_bridge_topology strips 56→57 in
  TABLE mode (with WARNING) — but DOR mode had no guard.
- **FIX (uncommitted at write time, router.sv route2d):** at die-A
  (Y_DIM-1, BRIDGE_COL), die-A-local targets: self → PORT_L, else PORT_S
  (detour down the bridge column, then DOR normally — the stripped-anynet
  shortest path).
- **Discriminator that nailed it (Jane/Junior's):** B→A to die-A row-7
  (7,1),(7,2),(7,3) = E→E straight, "must deliver even in a funnel" — they
  DIDN'T deliver, so the funnel theory died and the loop was proven.
- **DBG3/DBG4 port order trap:** the DBG3 header line says "ports
  0=local 1=E 2=W 3=N 4=S" — STALE/WRONG. noc_pkg.sv constants are the
  truth: PORT_E=0, PORT_W=1, PORT_N=2, PORT_S=3, PORT_L=4. Also the DBG3
  coordinate print is `d, x, y` not `d, y, x` — "D0 R7,0" is (y=0,x=7),
  NOT the bridge (y=7,x=0). Both traps wasted a read cycle.
- **Route-table N/S suspicion (to verify):** fresh gen_route_tables output
  says route_56[57]=N — but from (7,0) the way to (6,0) is PORT_S in the
  RTL. If the generator's N/S is flipped vs the RTL, table mode sends
  northbound traffic south — consistent with Steve's "table-mode hangs"
  (b_vc2 is single-die; DOR completes). DOR is the verified path; treat
  tables as suspect until cross-checked against a DOR-known-good cell.

## 12b. RESOLUTION (verified 2026-08-16, laura's 3ccbe59)

**FULL VERIFICATION PASSED — the complete bidirectional bridge delivers
100% both ways with tier-2 timing at gold:**

| Check | Result |
|---|---|
| 2-die big cell (5718 pkts) | A→B **2838/2838** + B→A **2880/2880**, SIM COMPLETE |
| Small discriminator cells | 8/8 and 8/8 (both B→A patterns) |
| b5_vc1 tier-2 | 44274/44274, exact 98.12%, mean Δ 0.00 |
| vc1 row | b5 98.12 / b10 83.32 / b20 84.45 / b40 99.58 / b80 98.09 — identical to pref13 gold artifacts |

**The two fix commits (mine, in laura's tree):**
- `87bf45c` — B→A loop: at die-A (7,0), die-A-local targets → PORT_L
  (self) else PORT_S (detour down bridge column). Killed the bridge loop.
- `5e492c6` — A→B void (mirror): die-A row-7 east sources (X>BRIDGE_COL),
  west-bound targets → PORT_S detour first. Fixed NICs 57-63 0/333 → all.
- Laura's `3ccbe59` = her F2 reorder swap (tier-2 timing) + TWO_DIE gating
  of my detours (single-die safety: noc_mesh passes TWO_DIE=0, noc_2die
  passes TWO_DIE=1).

**Post-fix corrections to earlier readings (all verified by the full run):**
- Jane's "PORT_S from (7,0) is a dead port" — WRONG: (6,0)'s N-input
  consumes f_st2[0][56][PORT_S]; the 2880/2880 B→A run proves it.
- Jane's "RTL keeps 57→56" (directed anynet) — WRONG for the current RTL:
  56's E-input is overridden by br_f3b AFTER the mesh wiring (noc_2die.sv
  always_comb last-assign-wins), so f_st2[0][57][PORT_W] has NO consumer.
  The 56↔57 link is fully removed in both directions. Her directed-anynet
  edge 57→56 would need RTL wiring to match.
- My earlier "in_use leak at die-B (0,0) W-in" (big_d3_findings.json) — that
  was the LOOP's residue, not a separate leak: the looping flit's W-in VC3
  sat S_VA_REQ op=W forever because the loop saturated the bridge. With the
  loop gone, no in_use leak appears. The findings JSON's "two bugs" framing
  should be read as ONE root cause (routing void) + the depth-3 starvation
  fix (9ae11d1, separate, real).

**Build-collision postscript:** THREE more OOM kills of dave builds (dave_d3_64
final, dave_d3_fix at obj 540, head_build/d3fix at obj 202 of Slow phase) —
all from laura's builds launching without a pgrep check (laura_final_2die,
laura_final_1die, laura_vc2). §8 rule is still being violated; the pattern
kills ~10-20 min of work each time. Check `pgrep -c verilator` is 0 BEFORE
launching, always.

## 13. SIM SPEED

- 128 NICs × run_cycles ≈ slow: ~1M cycles/min at T_DEPTH=64, -O3.
  The 5718-pkt cell (run 11601) takes ~2-3 min of sim after a 5-min build.
  At T_DEPTH=2048 the pump alone is ~4 min before ANY output — always use
  T_DEPTH=64.
- PROG lines print every 500 cycles — use the last PROG's ej count to see
  if delivery is progressing or plateaued (plateau = stall).

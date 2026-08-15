# LAURA STATE HANDOFF — 2026-08-15 ~21:20 (pre-compaction)

Author: Laura (opencode senior). Read this FIRST when resuming. This is the
complete live state, my in-flight work, and the business context.

---

## 0. THE URGENT THING (what I was doing when this was written)

**The tier-2 verification build was launched at 21:19:35 in tmux session `t2`.**
It verifies commit `bd5b89c` (my tier-2 eject-queue fix). Check it FIRST:

```
tmux ls            # is t2 alive?
grep -c BUILD_DONE /var/tmp/r1work/fork_gate/builds/b_t2.log
ls -la /var/tmp/r1work/fork_gate/builds/b_t2/Vnoc_tb
```

When the binary exists: run b5_vc1 tier-2 gate and compare against the
BROKEN baseline (mean Δ −14..−91, exact% 13%). EXPECT the fix to restore
exact% toward ~98% and flatten the delta profile. Then the full vc1 row,
gf_8 fork gate, and 2-die gf_bridge_on regression.

---

## 1. VERIFICATION STATE (all lanes)

### Delivery tier: GREEN (15/15) — junior's milestone 21:00
Committed tree delivers EXACTLY the BookSim targets:
- vc1 5/5 (b5 44274, b10 71832, b20 61748, b40 78947, b80 111291)
- vc2 3/3 F13-verified (b5 43860, b10 38750, b20 45401)
- vc4 5/5 (b5 43799, b10 44442, b20 43950, b40 58725, b80 71579)
All injected==ejected, SIM COMPLETE.

The three commits that made it possible:
- `b2bbc35` — F15: eject FIFO removed (the FIFO was silently killing
  single-die burst cells: b5_vc1 stalled at 346/44274)
- `0b0d332` — F13: pid concat was 37-bit (idx is int), 0x8000 bit truncated;
  explicit OR form `16'h8000 | (tptr+idx)`
- `8ca1308` — the VCS≥8 build wall was `dbg_router_t` VC dim `[3:0]`→`[7:0]`
  (OOB debug assigns at VCS=8). **This broke the VCS≥4 build wall.**

### Timing tier (4d3b): MY LANE — fix committed bd5b89c, building NOW
- Root cause: eject-QUEUEING missing after FIFO removal. BookSim's output
  buffer queues ejects under burst; no-FIFO drains immediately → RTL ejects
  earlier. Delta GROWS with burst (−14 B5, −18.5 B10, −24.4 B20, −39 B40,
  −91 B80) = queueing, NOT a fixed stage (per-flit −1..−3.5).
- Fix (bd5b89c): re-add eject FIFO from 4f951e1~1 (verified version) +
  copy-bit marker in flit_t + NIC eject credit gated on `!copy` (F8 leak
  fix: unconditional credit drifted credit_free[PORT_L] to saturation) +
  S_ROUTE head-guard.
- Lint clean both modes. Verification build in tmux `t2`.

### 113b col-0 corner: fixed in bd5b89c (my analysis → jane's evidence)
- jane's DBG4: stuck heads at R(2,0)/R(7,0) E-inputs, occ=8, op=N (impossible
  via route2d at row 7 for A→B dsts), heads in S_SA_HOLD.
- My find: S_ROUTE tail-pop path routed `qbuf[(hp+1)].dst` WITHOUT checking
  it's a head (asymmetric with the S_ACTIVE path). A body there → garbage
  out_port → op=N → SA wedge. FIXED in bd5b89c.
- jane's discriminators answered my credit hypotheses: bridge output EMPTY +
  credits full at stall → NOT credit-starved; heads in S_SA_HOLD → NOT
  va_grab race. The SA-stage/funnel-head wedge was the real mechanism.
- Dave's lane: A→B fixed 4/4 by bridge depth 2→3 + isolation removal
  (`70abd1a`); Preemptive VC (arXiv 2607.01430, Benini 2026) identified as
  the bidirectional-bridge fix direction; his VC-isolation VA-restriction was
  REVERTED (`0cad337`, starved A→B).

### F1-F15 all closed. The saga:
crossed credit lanes (b8531ac) → F1 fork XT collision (edec5c1) → F2
reorder deadlock (edec5c1/4f951e1) → F13 pid truncation (0b0d332) → F14
deadlock = BRIDGE_COL mismatch (Dave, 35e73dd) → F15 eject FIFO kills bursts
(b2bbc35) → tier-2 timing (bd5b89c, in flight).

---

## 2. TOOLING / PROCESS (working well, keep using)

- **comm/**: p2p `send.sh -f <you> <to> "<subj>"`; pub-sub `publish.sh -f <you>
  <topic> "<subj>"` (topics: status/decisions/alerts/questions);
  `check.sh <name>` (inbox), `read.sh <topic>`. Git-native text files.
- **AGENTS.md startup ritual**: `comm/check.sh <name>` + `comm/read.sh status`
  + `comm/read.sh alerts` at every session start.
- **seeds** (`sd`): durable tracker. **mulch** (`ml`): expertise records.
  `sd doctor` must be 12/12.
- **Build rules (codified after 4 OOM collisions)**: ONE build at a time;
  `-GT_DEPTH=64` (light, ~5min) unless a cell needs 2048; unique Mdir names
  (prefix with agent name); NEVER `pkill -f` (self-match kills own shell +
  other agents' builds); check comms alerts + `free -g` before launching;
  kill by exact PID.
- **Box facts**: 14GB RAM (builds die at ~0 avail), 12 cores, RTX 3050 4GB
  (NOT useful for Verilator — no GPU backend; would break the RTL-oracle
  credibility chain). /tmp is RAM-backed tmpfs (never use — wiped builds).
  All work in /var/tmp/r1work/. Long builds: tmux new-session -d, or
  `setsid bash -c '...' < /dev/null & disown` with a BUILD_DONE marker via
  `&&`.
- **Verification discipline** (the playbook): audit before claim; close on
  ARTIFACT EVIDENCE not commit presence; check data before code; verify the
  generated .cpp not the source; the 7-rung ladder (freshness → cell intent →
  binary/source match → config/model match → format → mechanism vs timing →
  classify).

---

## 3. KEY ANALYSES IN FLIGHT (resume these)

1. **tier-2 verify** (the immediate one, see §0).
2. **--threads speedup**: Verilator 5.032 supports `--threads N` (12-core
   box, NoC is spatially parallel). Plan: verify `--threads 4` on one cell
   (b5_vc1, compare 44274/44274 vs single-thread gold), then apply to corpus
   builds + run 5 vc1 cells in parallel (~10-20× wall).
3. **Real-trace leg**: Chakra→our-hex converter doesn't exist yet (seed 1ab3).
   The closed loop (real Qwen3-30B trace → RTL → gate) is THE missing demo.
   Every stage works in isolation; the converter is the final mile.
4. **S_ROUTE head-guard**: fixed in bd5b89c — but should be regression-
   verified on the two-class cell (was it the real 113b loss source?).

---

## 4. BUSINESS CONTEXT (the user's real goal — IMPORTANT)

**The goal is NOT a research paper. It's a services play:**
> client names a workload → we produce verified NoC RTL for them.

- **FlooNoC** (PULP/ETH, open-source, Solderpad): the credible open base.
  Silicon-proven (12nm), AXI-based, four networks (Control/Streaming/
  Optional/Chiplet). Used as calibration anchor already ("FlooNoC-calibrated,
  1.37× vs 12nm").
- **FlexNoC** (Arteris): the incumbent. A licensed CONFIG-DRIVEN NoC IP
  GENERATOR (GUI frontend → topology/protocol/QoS config → generated RTL +
  automated TBs). Physically aware, AMBA5/AXI/OCP, up to 2000 NIUs, 4B chips
  shipped. NOT open RTL — a licensed tool.
- **The product vision** (user's words): make NoC IP generation as easy as
  FlexNoC (GUI/config frontend) — with OUR credibility machine as the
  differentiator: every generated NoC ships with a workload-derived,
  RTL-gated verification report. FlexNoC sells generation speed; nobody
  publishes per-flit characterized fidelity. THAT's the wedge.
- **The gap to that vision**: we have CLI-only config (no GUI), raw-flit
  protocol (no AXI), no QoS/power domains, no physical awareness. Path:
  config frontend → parameterized RTL (we have the knobs) → gate as default
  output. Protocol support via FlooNoC base.
- **GPU verdict**: RTX 3050 4GB — not useful for Verilator (no GPU backend);
  a CUDA port would break the "RTL is the oracle" chain (third model needing
  its own validation). CPU `--threads` + parallel cells is the speedup.
- **The honest pitch**: "we verify interconnects" — the toy proved the
  engine (F1-F15 = real bug classes found in a week). The toy is the test
  rig, the method is the product, scale-up is parameter flags + a real box.

---

## 5. OPEN SEEDS (P1)

- `4d3b` tier-2 timing — fix committed bd5b89c, verify pending (mine)
- `ee61`/`df18` F13 — verified at vc2, vc4 done after 8ca1308 (mostly closed)
- `1ab3` serving leg: Chakra ET → ASTRA-sim with our BookSim2 mcast (the
  real-trace demo — the big one)
- `113b` col-0 — delivery 98.96%→100% after fixes; S_ROUTE guard in bd5b89c

---

## 6. IMMEDIATE NEXT STEPS (in order)

1. Check tmux `t2` build (b_t2) → run b5_vc1 gate → tier-2 PASS expected
2. Full vc1 row + gf_8 + 2-die regressions on bd5b89c
3. Close 4d3b with artifact evidence
4. `--threads` verification + parallel-cell runs
5. The real-trace demo (1ab3): write the Chakra→hex converter
6. Business: scope the config→verified-NoC pipeline; evaluate FlooNoC as
   the protocol-compliant base

# DAVE STATE HANDOFF — 2026-08-15 ~21:30 (pre-compaction)

Author: Dave (opencode senior). Read this FIRST when resuming. Complete live
state of my lanes: the bidirectional-bridge starvation fix, the trace
pipeline, paper evidence, and the build-collision war.

---

## 0. THE URGENT THING (what I was doing when this was written)

**The big-cell verification build `dave_d3_64` was in flight** (VCS=4,
2-die, col-0 bridge, depth-3 bridge channels, NO isolation, T_DEPTH=64).
Check FIRST:

```
pgrep -c verilator                    # 0 = box free
ls -la /var/tmp/opencode/trace_rtl_cell/dave_d3_64/Vnoc_tb   # binary exists?
tail -c 100 /var/tmp/opencode/dave_d3_64_build.log           # progress
```

When the binary exists, run the big bidirectional cell:

```
bash /var/tmp/opencode/test_big_d3.sh
```

Expect: A→B substantially improved vs the pre-fix baseline (321/2838 →
should be much higher with depth-3). The pre-fix numbers to beat:
- VCS=4 pure baseline: A→B 321/2838 (11%), B→A 2370/2880 (82%)
- The SMALL-CELL proof already passed: 4/4 A→B delivered (was 0/4).

---

## 1. WHAT I PROVED (small-cell evidence, committed)

**The A→B starvation fix is REAL, isolated, and committed:**
- `9ae11d1` — bridge depth 2→3 (CreditBased min-FIFO rule, arXiv 2607.01430
  §III-3: with registered credit return, downstream FIFO must be ≥3 flits
  deep or throughput drops up to 33% and one direction starves).
- `0cad337` — REMOVED the bridge-VC isolation VA-restriction (`c9ab55e`).
  **The isolation was the A→B killer**: small cell 0/4 A→B with it vs 4/4
  without. It made die-A's bridge exit request only VCS-1, breaking the
  credit/in_use bookkeeping.
- `70abd1a` — evidence JSON: smallcell_d3_ab_fix.json (8-pkt cell, A→B 4/4).

**The small-cell result (vbuild_d3clean era, T_DEPTH=16):**
- 8 packets: 4 A→B (0→64,1→65,2→66,3→67) + 4 B→A (64→0,65→1,66→2,67→3)
- injected=8, delivered=5: A→B 4/4 DELIVERED, B→A 1/4 (only 64→0)
- **Remaining open item: B→A direction** (die-B NICs 65-67 inject but flits
  never reach die-B (0,1)-(0,3) routers' LOCAL; the wiring is provably
  correct, so it needs RTL runtime tracing — see §3).

**The Preemptive VC research (why depth-3, not isolation):**
- docs/research/preemptive-vc-bridge-fix.md — the ETH paper (arXiv
  2607.01430, Leone/Colagrande/Benini, FlooNoC v0.8.0) formalized our exact
  problem: traffic-class interaction deadlock at a shared resource even with
  deadlock-free routing. Their Preemptive VC attacks Coffman's no-preemption.
  Their CreditBased analysis gives the depth-≥3 rule we applied.
- Published to alerts topic 13:34.

---

## 2. THE TRACE PIPELINE (epic veritx-research-e77a, CLOSED)

**The full chain works end-to-end** (LLMServingSim → Chakra → BookSim → RTL):
- Toolchain in /var/tmp/opencode/LLMServingSim + llmssim-venv (Python 3.14).
  Setup notes + install fixes in docs/research/llm-serving-trace-pipeline.md.
- `tracks/t3-topology/scripts/trace_to_matrix.py` (committed 9fb248d) —
  LLMServingSim trace → BookSim matrix.
- Qwen3-30B-A3B TP2/EP2: 1,178 serving batches, 24.2GB inter-die,
  ALLGATHER 34.7% / ALLREDUCE 32.7% / REDUCESCATTER 32.7%.
- Bridge saturation: single bridge link caps at ~1.0 link capacity,
  latency 68→381 cyc (5.6×) — results/trace_pipeline/trace_bridge_saturation.json
- Serving-level headroom: 3.43× tok/s with bridge-fork vs source-fork
  (13,280 vs 3,873 tok/s) — results/trace_pipeline/serving_level_headroom.json
- Fork-vs-source on the col-0 protocol topology: 8-9% latency win at all
  loads — results/trace_pipeline/fork_vs_source_col0.json

**Framing decision (committed, seed veritx-research-1524):**
The paper leads with **dispatch + collectives** (ALLGATHER/ALLREDUCE), KV
demoted to one class. The mechanism (bridge-fork, placement law) is
traffic-class agnostic and survives.

---

## 3. THE B→A OPEN ITEM (what I was chasing)

**Symptom (small cell):** die-B NICs 65,66,67 fire + inject (VC lines
present) but their flits never appear in die-B (0,1),(0,2),(0,3) routers'
LOCAL buffers (DBG3 recv=0). die-B (0,0)'s flit (64→0) delivers.

**What I verified:**
- The TB→noc_2die→router inject wiring is correct (inj[d][y][x] →
  inj_st1[d][e] → inj_st2[d][e] → rf_in[d][n][PORT_L], e = y*8+x, n = e).
- The NIC's inject_valid/pkt_ready/credit path is standard.
- The FIRE "n%d" prints use LOCAL coords (die-A NIC 1 and die-B NIC 65 both
  print "n1") — a log-interpretation trap.

**Hypotheses not yet tested (need the build + runtime trace):**
1. The flit sits in inj_st1/inj_st2 and the router's LOCAL input doesn't
   accept it (router-side gating).
2. A DBG port-index misread (Junior fixed DBG4's index bug once; verify the
   DBG3 readout with the fix).
3. The inject_credit path for die-B (injc_st1[1][e] ← rc_out[1][e][PORT_L])
   — check the die-B router's LOCAL credit_free at runtime.

**Debug plan when the box frees:** rerun the small cell with the fixed
DBG2/3/5 (F9, commit 409f1f7, already in HEAD) and read die-B (0,1)'s
per-port occ/recv/pop + the DBG5 credit audit during the run, not just at
the end (the end-of-run audit shows post-drain state — misleading).

---

## 4. THE BUILD-COLLISION WAR (4 OOM incidents, now codified)

**Every "crash"/"killed mid-compile" of 2026-08-14/15 was an OOM build
collision, NOT session cleanup.** The box is 14GB; two concurrent builds
kill each other. Evidence:
- vbuild_iso killed when Junior's vbuild_abfix_vc4 (8.4GB) ran.
- dave_d3_64 killed at obj 53 when b_vc4_f13 (GVCS=8, 9GB) ran.
- 4 total incidents; all same signature: `Terminated` mid-make, box at 0MB.

**Codified in GATE-R1-COORD §8 (commit 61d8499):**
1. UNIQUE build dirs per agent: /var/tmp/opencode/trace_rtl_cell/<agent>_<name>
   (a shared Mdir name + `pkill -f <name>` from another agent killed mine twice)
2. MANDATORY -GT_DEPTH=64 (or smaller) on 2-die builds. The 2048 default is
   the OOM class (~8GB, 60min). T_DEPTH only sizes trace BRAM; pump drops
   262K→8K cycles at 64. **T_DEPTH must be ≥ max trace entries per NIC** —
   the 5718-pkt cell needs 64 (16 overflowed: "$readmem file address beyond
   bounds").
3. ONE build at a time: `pgrep -c verilator` must be 0 before launching.
4. Preflight: free > 6GB before VCS≥4.
5. GVCS=8 = 9GB: never concurrent, prefer GVCS=4 unless required.

**Build speed tips (all verified):**
- -O3 + T_DEPTH=64: ~5-8 min (vs 60+ min at T_DEPTH=2048)
- -j2 is safe when free > 6GB (the "NEVER -j2" rule predates T_DEPTH=64)
- Foreground with a long timeout survives; background (nohup/setsid/tmux)
  is unreliable — but the REAL killer is concurrent builds, not backgrounding
- Detached pattern that works: `setsid nohup script.sh < /dev/null > /dev/null 2>&1 &`

---

## 5. TEAM STATE (from comms, 21:00)

**Junior — MILESTONE: 15/15 delivery matrix GREEN on the committed tree:**
- vc1 5/5, vc2 3/3 (F13-verified), vc4 5/5. All injected==ejected, SIM COMPLETE.
- Three commits: b2bbc35 (F15 eject FIFO removed), 0b0d332 (F13 pid OR),
  8ca1308 (dbg_router_t VC dim [3:0]→[7:0] — the VCS≥8 build wall).
- Remaining: tier-2 TIMING (the eject queue, 4d3b — Laura's lane).

**Laura — tier-2 eject-queue fix committed bd5b89c, building in tmux t2:**
- Root cause: eject-QUEUEING missing after FIFO removal (delta grows with
  burst: −14 B5 → −91 B80 = queueing, not a fixed stage).
- Also fixed 113b col-0 corner: S_ROUTE tail-pop routed qbuf[(hp+1)].dst
  without checking it's a head (asymmetric with S_ACTIVE path) → garbage
  out_port → SA wedge.
- Her playbook: handoffs/laura-playbook-bughunting.md (worth reading).

**Steve/Jane:** Jane's forensics (fix2, VCS=2): 501 A→B flits lost, 79% from
die-A ROW-7 sources; bridge node (7,0) S-input full; delivery stops dead at
t=14,000; her discriminator = VCS=4 rerun (which is exactly dave_d3_64).

---

## 6. CREDENTIALS / PATHS / TOOLS

- **GitLab token**: stored in ~/.git-credentials (600), scoped to
  internal-devrepo.datavex.ai. Internal GitLab: git@internal-devrepo.datavex.ai
  (SSH sometimes down; HTTPS + token works). Remotes: datavex (internal),
  origin (gitlab.com), github.
- **Cell dirs**: /var/tmp/opencode/trace_rtl_cell/ (route tables, binaries,
  cell configs). Route tables: /var/tmp/opencode/route_tables/ (generated by
  gen_route_tables.py from the anynet, Dijkstra-exact with sorted tie-break).
- **Trace evidence**: /var/tmp/opencode/trace_evid/ (5718-pkt bidirectional
  cell, trace.txt + trace_n*.hex + run_cycles).
- **Key binaries**: vbuild_vc4 (VCS=4 baseline), vbuild_col0 (VCS=2 col-0),
  dave_d3clean (VCS=4 + depth-3, T_DEPTH=16 — the A→B 4/4 proof),
  dave_d3_64 (VCS=4 + depth-3, T_DEPTH=64 — the big-cell build, was in flight).
- **Paper framing**: tracks/t3-topology/paper_draft.md — claim scope section
  updated (network-level demand reduction claimable; end-to-end serving NOT).
- **Business**: docs/business/company-vision.md — VeritX Core/Fabric/Verify.
  The three-plane + telemetry/compiler architecture idea (data/control/
  compiler-telemetry) noted for the product doc — NOT yet written up.

---

## 7. NEXT STEPS (ordered)

1. **Finish the big cell** (dave_d3_64): run test_big_d3.sh, record A→B vs
   B→A. The depth-3 + no-isolation fix should show A→B far above 321.
2. **B→A debug** (small cell, fixed DBG2/3/5): find why die-B NIC 65-67
   flits vanish before their routers' LOCAL.
3. **Update the paper evidence** with the final bidirectional numbers +
   the Preemptive VC citation (arXiv 2607.01430).
4. **Write up the three-plane architecture** (data/control/telemetry-compiler)
   as an ADR for the business vision (user asked to note it down).
5. **sd sync + push** before any compaction.

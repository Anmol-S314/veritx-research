# Srota three-level arbiter — measurable claim M3

ROUTE-001 rev 0.3 §16.4 defines M3 as "slack-arbitration critical-class
latency vs RR/age baselines" and names three ingredients. All three now
exist, so M3 is answerable. The answer is qualified, and the qualification
is the result.

| Ingredient (§16.4) | Where it is |
|---|---|
| 2-bit slack tag in the packet format matching §8.2 | `Flit::slack` / `batch` / `golden_id`, carried per packet from the trace |
| The three-level arbiter as an allocator variant replacing islip/RR | [`allocators/srota_arb.cpp`](../../../third_party/booksim2/src/allocators/srota_arb.cpp), selected with `sw_allocator = srota_arb` |
| A baseline on identical traffic | the `islip` arms below: same trace, same fabric, same seed |

Reproduce with [`scripts/srota_m3.py`](../scripts/srota_m3.py). Every number
below comes from a run that passed
[`scripts/srota_trust_check.py`](../scripts/srota_trust_check.py).

---

## 1. Headline

**The arbiter improves critical-class p95 only below saturation, by a few
percent, and above saturation it loses on latency and on throughput.**

At the unsaturated point it buys 6.7% on critical p95 and pays for it with
roughly double the bulk-class tail. It does not improve critical p99 at any
load measured.

M3 should not be quoted as a win without naming the load regime it was
measured in.

---

## 2. Setup

16 nodes, k=4 c=1, the Srota fabric of `srota16.cfg`, driven by
`moe_traffic.py --emit-trace`: Mixtral-8×7B expert-parallel MoE, Zipf skew
1.2, hot experts in mesh column 2, 4 decode steps over an 8000-cycle span.

Slack follows the workload rather than being assigned for effect. Token
dispatch and combine sit on the decode critical path and carry slack 0;
weight broadcast is bandwidth-hungry and latency-tolerant and carries slack
2. Load is varied by the packet budget at fixed span.

Latency is the honest ruler throughout, `arrival − request_time`. Because
the population is finite and conserved, the saturated rows below are
legitimate in a way a rate sweep's saturated rows are not: every packet is
counted, so an arm that collapses cannot read as fast by dropping the
packets that would have been slow.

---

## 3. Load sweep

Cycles. `crit` is slack 0, `bulk` is slack 2. `horizon` is the last
arrival, so it measures drain time and therefore throughput.

| packets | arm | crit p95/p99 | bulk p95/p99 | horizon |
|---|---|---|---|---|
| 2400 | islip / RR | **89 / 136** | **40 / 62** | 8019 |
| 2400 | srota_arb, all levels | **83** / 139 | 79 / 157 | 8019 |
| 2400 | srota_arb, L1 only | **83** / 138 | 50 / 88 | 8019 |
| 3200 | islip / RR | 202 / 306 | **152 / 232** | **8028** |
| 3200 | srota_arb, all levels | **201 / 292** | 230 / 278 | **8028** |
| 3200 | srota_arb, L1 only | 216 / 347 | 507 / 544 | 8083 |
| 4000 | islip / RR | **360 / 677** | **744 / 768** | **8632** |
| 4000 | srota_arb, all levels | 418 / 967 | 1026 / 1052 | 8909 |
| 4000 | srota_arb, L1 only | 426 / 970 | 1026 / 1052 | 8912 |
| 4800 | islip / RR | 545 / **2043** | **2245 / 2264** | **10251** |
| 4800 | srota_arb, all levels | **529** / 2639 | 2843 / 2862 | 10849 |
| 4800 | srota_arb, L1 only | 542 / 2761 | 2965 / 2984 | 10971 |

Two things to read off it.

**The critical-class gain is small and does not survive load.** 6.7% on p95
at 2400, a wash at 3200, negative at 4000. Critical p99 is never improved.

**Above saturation the arbiter costs throughput.** The horizon grows from
8632 to 8909 at 4000 packets and from 10251 to 10849 at 4800 — the same
work takes 3% and 6% longer to drain. That is not a latency redistribution;
it is less work done per cycle.

---

## 4. Why throughput drops, established rather than assumed

Each level intersects the candidate set before the round-robin tiebreak
runs. A narrowed set produces a smaller switch matching: an output that
would have granted a free input under round-robin instead grants the
minimum-slack input, which another output may also want.

This is confirmed rather than inferred. With all three levels disabled but
the trace still carrying non-zero slack, batch and golden fields,
`srota_arb` reproduces `islip` **byte-identically**. The allocator's
grant/accept structure is iSLIP's; the masks are the only thing that
differs, so the masks are the only thing that can be causing the loss.

The same test run the other way — a trace with all-zero arbitration fields
through `srota_arb` with every level enabled — is also byte-identical to
`islip`, which is the degenerate behaviour §11.2 implies: a field that is
uniform across all requests never discriminates and its level falls
through.

---

## 5. Which level does the work

At 2400 packets, each level alone against the same baseline:

| arm | crit p50/p95/p99 | bulk p50/p95/p99 |
|---|---|---|
| islip / RR | 22 / 89 / 136 | 22 / 40 / 62 |
| islip / age | 22 / 86 / 143 | 22 / 37 / 51 |
| all three levels | 21 / 83 / 139 | 23 / 79 / 157 |
| L0 golden only | 22 / 88 / 138 | 22 / 43 / 80 |
| L1 slack only | 21 / 83 / 138 | 23 / 50 / 88 |
| L2 STC only | 22 / 89 / 136 | 22 / 40 / 62 |

**L1 is the only level that moves the critical class.** L0 alone recovers
almost none of the gain (89 → 88) while already costing bulk (62 → 80).

**L2 is inert on this workload, correctly.** It is byte-identical to the
baseline because `batch` is the decode step and nearly every packet
contending at a given instant shares one. L2 is a starvation bound (F4);
a workload where it does nothing is a workload with no starvation to
bound, not a broken level.

**The level ordering costs more than it buys here.** L0 runs before L1, so
a bulk packet whose golden window is open outranks a critical packet.
That is deliberate — F3's bounded-delay floor is meant to outrank priority
— but on this workload the floor is being paid for continuously and
collecting nothing, because no flow is being starved.

Do not generalise the L1-only row past 2400 packets: at 3200 it is worse
than the full cascade on every column. Whatever the right level
combination is, it is load-dependent, which is itself an argument against
quoting a single M3 number.

### Golden epoch sensitivity

The L0 finding is not an artifact of one epoch length. All levels enabled,
2400 packets:

| `srota_arb_golden_epoch` | crit p95/p99 | bulk p95/p99 | all mean |
|---|---|---|---|
| 16 | 84 / 158 | 95 / 174 | 31.10 |
| 64 | 83 / 139 | 79 / 157 | 30.40 |
| 256 | 82 / 158 | 123 / 212 | 31.38 |
| 1024 | 81 / 172 | 133 / 213 | 32.02 |

Longer windows trade a point of critical p95 for a much worse critical p99
and a much worse bulk tail. No setting makes L0 a win here.

---

## 6. What this does not answer

**The two stages are not modelled.** TOPO-003 §7.3 builds the router from
two coupled ≤6-port allocators, and rev 0.3's RT-R9 has the first to
resolve publish `out_busy_mask` for the second to mask against. BookSim's
IQRouter drives one flat allocator, so `out_busy_mask` is identically zero
here. The three *levels* are modelled exactly; the two *stages* are not.
Closing this needs a custom Router subclass — the same vehicle the side
buffer needs, which is why the plan merges them.

**Credit is checked upstream, not in the cascade.** `credit_avail` in
§11.2's expression is already applied by IQRouter, which only raises a
switch request for a VC whose target has space. The term is satisfied by
construction rather than re-evaluated.

**One workload, one fabric size.** 16 nodes with k=4 is the size where
SROTA-EVALUATION §2.1 showed Srota and `flatfly16` are indistinguishable in
principle. A 6-port allocator at k=4 c=1 has few enough ports that
matching-size effects are large; the same sweep at k=16 c=4 may read
differently, and the arbiter is specified for that router, not this one.

---

## 7. Configuration

| Key | Default | Meaning |
|---|---|---|
| `sw_allocator = srota_arb` | `islip` | select the three-level arbiter |
| `srota_arb_l0_golden` | 1 | golden rotation mask, F3 |
| `srota_arb_l1_slack` | 1 | slack-class mask |
| `srota_arb_l2_stc` | 1 | STC batch-epoch mask, F4 |
| `srota_arb_golden_epoch` | 64 | cycles per golden window |
| `srota_arb_golden_windows` | 16 | windows in the rotation |

```sh
python3 tracks/t3-topology/scripts/moe_traffic.py -n 16 --grid-k 4 --grid-c 1 \
    --pattern mixed --skew 1.2 --hot-column 2 --broadcast-weight 0.35 \
    -o results/moe16.txt --emit-trace results/moe16_trace.csv \
    --steps 4 --trace-packets 2400 --seed 1

python3 tracks/t3-topology/scripts/srota_m3.py \
    --config third_party/booksim2/src/examples/srota_trace.config \
    --trace  results/moe16_trace.csv
```

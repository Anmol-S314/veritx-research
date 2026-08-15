# Preemptive VCs — the fix for the bidirectional bridge starvation

Source: **Leone, Colagrande, Benini (ETH Zürich), "Physically-Aware Preemptive
Virtual Channels for Deadlock-Free AXI Networks-on-Chip", arXiv 2607.01430,
July 2026** (FlooNoC v0.8.0, open-source: github.com/pulp-platform/FlooNoC).

## Why this paper is our answer

Our symptom: 2-die NoC, ONE bridge link, bidirectional unicast matrix.
A→B delivers 11% (321/2838), B→A 82% (2370/2880); unidirectional A→B flows
99%. Not a routing deadlock (Dijkstra-exact tables verified; BookSim delivers
at num_vcs=1). It is a **traffic-class interaction deadlock at the shared
bridge resource** — exactly the class of problem this paper formalizes:
*"protocol-level dependencies between traffic classes can create circular
waits at the network endpoints, even when the routing algorithm itself is
deadlock-free."*

## The four solutions they evaluate (and our mapping)

| Design | Mechanism | Applies to us? |
|---|---|---|
| **Multiplane** | duplicate physical link per class | NO — we have ONE bridge link (the whole point) |
| **Naive VC** | per-VC valid/ready, mask upstream valid with downstream ready | ready→valid combinational path kills frequency |
| **CreditBased** | credit counter per output VC, decrement on send, increment on downstream pop | Our current scheme! **Requires downstream FIFO ≥3 to sustain full throughput** — a 1-cycle credit-return delay loses up to 33% bandwidth |
| **Preemptive VC (their novel contribution)** | link ownership via round-robin among valid streams; a stream whose downstream receiver is NOT ready is **preempted** next cycle; registered downstream ready decides ownership | **YES — this is the fix** |

## The key insight (Coffman's conditions)

Classic deadlock theory (Coffman): deadlock requires mutual exclusion +
hold-and-wait + **no-preemption** + circular wait. VC isolation attacks mutual
exclusion (we tried — failed, credit correlation). Credit-based flow control
attacks hold-and-wait (we have it — but the credit-return latency creates a
feedback window that starves one direction unless the downstream FIFO is deep
enough). **The Preemptive VC attacks no-preemption**: no stream may hold the
shared link while blocked — a stalled stream is evicted next cycle and another
valid stream takes the link. No circular wait can persist.

Quote (their §III-4): *"To the best of our knowledge, prior VC designs have not
targeted Coffman's no preemption condition... any valid input may acquire the
shared physical link, but can be preempted by another valid stream if its
downstream receiver is not ready."*

## Cost (their TSMC 7nm numbers)

Preemptive: 100% BW utilization, +3% router area, 1.70 GHz (no freq loss),
+1% routing tracks vs the naive VC's -16% freq. CreditBased-3-buffer: +28%
area. Multiplane: +76% routing. **Preemptive is the cheapest deadlock-free
design.**

## What we implement

Our bridge already has per-direction credit loops (br_c1/c2, br_c1b/c2b) and
2-stage channels. The fix: make the bridge-entry routers' SA **preemptive**
across the two directions — when die-A's EAST (bridge) has no downstream
credit, the arbiter must still let die-B's WEST (bridge) proceed (and vice
versa), with round-robin ownership and registered ready. Effectively: the
bridge is a shared link with preemptive ownership instead of two independent
credit-gated channels.

Also relevant: their CreditBased analysis says our VC_BUF_DEF=8 should be
deep enough to hide the credit-return delay — so the starvation is NOT buffer
depth; it is the missing preemption at the shared bridge resource. The
circular wait: A→B holds die-A column credit waiting on bridge credit that
B→A's occupancy prevents returning, and vice versa.

## Action

1. Implement preemptive bridge ownership in noc_2die.sv (round-robin arbiter
   over the two bridge directions; registered ready; preempt blocked stream).
2. Verify on the bidirectional cell: expect both directions >90%.
3. Cite this paper in the related work (it is 2026, Benini group, FlooNoC —
   the same FlooNoC our plane-separation work already cites).

Filed by Dave 2026-08-15. Status: pending implementation.

# T2 — Deadlock Avoidance with Booksim 2.0

> **2026-08-05 — v2 role: deadlock-claim validation case study.** The deliverable
> is no longer a NOCS paper; it is a worked audit of a deadlock-freedom claim
> (config → sweep → gate → verdict), published as case study #3 in the services
> portfolio (see [docs/business/programme-v2.md](../../docs/business/programme-v2.md)).
> The study below is the material; the *product* is the discipline of validating
> the claim, not the XY-vs-UGAL ranking itself.

Study routing deadlock in 2D mesh NoCs: how virtual channel count, routing algorithm, and injection rate interact.

## What You Edit

| File | What it does | Your research |
|------|-------------|---------------|
| `configs/*.cfg` | Topology, routing, VC params | Add your own configs for new routing schemes or VC configurations |

The Booksim source (with the `matrix()` traffic pattern) is at `/opt/booksim2/` inside the container. You can add custom routing functions (C++) and recompile with `make -C /opt/booksim2/src`.

## Research Questions

- Minimum VCs to avoid deadlock for DOR vs adaptive vs Valiant routing on an N×M mesh?
- How does deadlock threshold shift with injection rate?
- Can a simple VC allocation scheme outperform a complex one for AI traffic patterns?
- What is the throughput cost of deadlock freedom (extra VCs)?

## CI Pipeline

```
make setup   → verify Booksim binary exists
make lint    → syntax-check configs
make test    → single sanity run (mesh 4×4, uniform, one rate)
make sim     → full sweep: 5 injection rates × all configs
```

Results are uploaded as CI artifacts (`results/*.json`).

## Expected Output

```
  mesh4x4 @ 0.05 → latency=21.3
  mesh4x4 @ 0.10 → latency=42.8
  mesh4x4 @ 0.20 → latency=185.2
  mesh4x4 @ 0.30 → None  (saturated)
  mesh4x4 @ 0.40 → None  (saturated)
```

Latency `None` at high injection rates = the network is saturated (expected physics). The saturation point itself is a key research metric.

## Example Experiment

Try adding a `mesh4x4-dor.cfg` with `routing_function=dim_order` and a `mesh4x4-adaptive.cfg` with `routing_function=adaptive_local`. Compare the saturation throughput.

## Files

| File | Purpose |
|------|---------|
| `configs/mesh4x4.cfg` | 4×4 2D mesh (n=2 → 16 nodes) |
| `scripts/run_experiments.py` | Injection rate sweep across all configs |
| `scripts/sanity_test.py` | Single-point validation |

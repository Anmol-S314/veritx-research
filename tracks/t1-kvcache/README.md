# T1 — KVCache QoS (Deferred)

**Status: Stub.** gem5 + Garnet + ASTRA-sim require a 4-6 hour build. The Docker image does not yet include gem5.

## Scope (When Ready)

- Model an AI accelerator's memory hierarchy with gem5
- Study KVCache quality-of-service under different NoC arbitration policies
- Garnet for network simulation, ASTRA-sim for collective communication patterns

## Current Files

| File | Purpose |
|------|---------|
| `scripts/sanity_test.py` | Placeholder — prints "gem5 not available" |

## CI Behavior

The T1 CI cell runs `setup → lint → test` — all pass trivially (no gem5 dependency). `sim` is skipped until gem5 is added to the Docker image.

# Serving Qualification (C7)

Status: **OPEN**. Scheduling and protocol behaviour are tested; the
production serving envelope (parallelism, network-execution evidence,
multi-instance liveness) is not yet qualified. This file states exactly
what is proven and what is owed.

## Scheduling (what exists)

- The serving loop drives prefill/decode rounds over the canonical fabric
  and retires requests; protocol framing (startup burst, `Waiting`
  terminator, EOF semantics) is pinned by `test_serving_protocol.py`
  against a real child process over real pipes (35 tests, deterministic
  after C7.1).
- TTFT / latency definitions and batch formation are the subject of C7 and
  are not yet independently validated against a hand-derived oracle.

## Parallelism (owed)

TP membership, DP groups, EP/MoE dispatch/expert/combine, rank reuse and
"no rank multiplication" must each be proven from a runtime ledger, not
from the lowering code. Owed.

## Network execution evidence (owed)

The runtime ledger must match collective kind, payload, communicator
membership, round, rank, endpoint and completion. A dispatched batch with
no network-execution evidence must **fail**. This is the serving analogue
of the BookSim conservation gate and is owed.

## Multi-instance (owed)

Prove all instances progress, no permanent `Waiting` loop, sim time
advances, requests retire, no unsent batch retires, and no pass echo
creates false progress. The `waiting_without_progress` livelock fixture
exists as diagnostics; the multi-instance proof is owed.

## Test reliability (C7.1 — landed)

- `test_crash_mid_session`: the client now reaps the child after stdout EOF
  before building the error, so the exit code is deterministic.
- stderr-flood quiescence: asserts bounded completion, not a racy answer.
- Per-test timeouts (`pytest-timeout`, 900 s default, 30 s protocol).
- Release gate fails on release-critical skips (`.et` fixtures,
  `VERITX_ASTRA_REF_BIN`).

## Blockers

- The six `test_full_pipeline.py` integration tests need LLMServingSim
  Chakra `.et` fixtures that are not vendored. Until vendored or generated
  deterministically, the integration domain is explicitly UNSUPPORTED and
  the release gate fails on the skip.

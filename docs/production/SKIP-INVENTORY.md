# VERITX Skip Inventory

Every skip is classified. A skip is not automatically acceptable; the
release-critical column states whether the skipped functionality is
required for the production gate. Unclassified skips are forbidden.

Classification values: `OPTIONAL_BACKEND`, `PLATFORM_UNSUPPORTED`,
`LEGACY_ONLY`, `DEPRECATED`, `TEMPORARY_BLOCKER`.

## Active skips (fast tier, `-k "not real"`)

| test | reason | class | release-critical | owner | removal condition |
|------|--------|-------|------------------|-------|-------------------|
| `test_wave_d_authenticity.py:27` | historical v1 `LogicalMessageArtifact` deleted; V2 covered | LEGACY_ONLY | no | wave-d | never (historical) |
| `test_wave_d_physical.py:61` | historical v1 logical/physical artifacts deleted; V2 covered | LEGACY_ONLY | no | wave-d | never |
| `test_wave_d_seal.py:50` (x2) | historical v1 WaveD artifacts deleted; V2 covered | LEGACY_ONLY | no | wave-d | never |
| `test_wave_d_semantics.py:35` | historical v1 artifacts deleted; V2 covered | LEGACY_ONLY | no | wave-d | never |
| `test_wave_d_contract.py:102` | historical astrasim_adapter heuristic superseded by `derive_logical_dimensions` | DEPRECATED | no | wave-d | never |
| `test_astra_runtime.py:361` | `VERITX_ASTRA_REF_BIN` not set (two-binary 16/16 differential) | OPTIONAL_BACKEND | yes (external validation) | backend | provide the reference binary in the release environment |
| `test_full_pipeline.py:132,149,191,236,304,357` (6) | event_handler `.et` / Qwen3 batch trace not present in the vendored LLMServingSim data | TEMPORARY_BLOCKER | yes (integration) | serving | vendor the trace fixtures or gate behind a fixture-fetch step |

## Deselected live-backend tier (`-k "real"`, 160 tests)

These are deselected from the fast tier because a real BookSim/ASTRA
execution can take up to 600 s. They are NOT optional: the release
battery must run them as a separate T4 job with a hard per-test timeout.

```text
test_backend_astra_machine.py::test_real_*        (real ASTRA rounds)
test_backend_booksim_execution.py::*              (real BookSim rounds)
test_serving_loop.py real live gate (VERITX_LIVE_SERVING=1)
test_serving_canonical.py real live gate
```

## Flaky (not skipped) — real-time subprocess timing

Two serving-protocol tests were timing-sensitive under load. Both are now
deterministic (`C7.1`):

| test | former symptom | fix | status |
|------|----------------|-----|--------|
| `test_serving_protocol.py::TestStderrQuiescence::test_quiescence_is_bounded_under_a_permanent_stderr_flood` | asserted `result is False`; a scheduling gap could legitimately look idle | assert BOUNDED completion (the real hazard is a hang), not a particular answer | FIXED |
| `test_serving_protocol.py::TestProtocolViolations::test_crash_mid_session` | EOF observed before the exit code under load, so "exit code 7" was missing | the client now waits (bounded) for the child to reap after stdout EOF before building the error | FIXED |

Both carry `@pytest.mark.timeout(30)`; `pyproject.toml` declares
`pytest-timeout>=2.2` and a 900 s default timeout so a hung backend fails
the job rather than stalling CI.

## Release-gate skip enforcement (C10.1)

`tests/conftest.py` fails the whole test session when
`VERITX_RELEASE_GATE=1` and a skip names a release-critical dependency
(serving `.et` fixtures, `VERITX_ASTRA_REF_BIN`). The T4 `backend-gate` and
`clean-clone` release jobs set that variable, so a clean clone cannot
qualify while these domains are unproven.

## Open risks surfaced by this inventory

1. `test_astra_runtime.py` differential is gated on an external binary;
   if that binary is never provided, no independent ASTRA numerical
   validation exists. This matches `ENGINE-QUALIFICATION` status
   "ASTRA numerical validity NOT_ESTABLISHED". Under
   `VERITX_RELEASE_GATE=1` this skip now FAILS the gate rather than being
   tolerated.
2. Six full-pipeline integration tests depend on trace fixtures that are
   not vendored (LLMServingSim must generate real Chakra `.et` files). A
   clean-clone release test now FAILS on these skips under the release
   gate, so the integration domain is explicitly unsupported until the
   fixtures or a deterministic generator are provided — it does not
   silently pass.
3. Per-test hard timeouts are now configured (`pytest-timeout>=2.2`, 900 s
   default, 30 s on the two protocol tests), so a hung backend fails the
   job.

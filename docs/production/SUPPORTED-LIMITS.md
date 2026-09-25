# VERITX Supported Limits

The measured, honest envelope of the current release candidate. Anything
outside this is refused (fail-closed) or labelled unsupported, never
silently approximated.

## Network execution (BookSim)

| limit | value | source |
|-------|-------|--------|
| trace injection rate | at most one flit per cycle per source port | `trace_injection_horizon`, fork trace model |
| convergence window | per-source injection horizon + 1000-cycle drain margin | `trace_schedule` (F-0007) |
| drain margin | fixed heuristic, not a physical bound | `_SAMPLE_PERIOD_MARGIN` |
| route observation | first hop only (fork dumps one hop) | `route_observation.py` |
| certified profiles | native mesh DOR_XY and AnyNet min-hops | `booksim_projection.py` |
| packet size | ≤ 8 flits | `PacketFormatArtifact.max_packet_flits` |
| flit width | profile/design dependent (64 b in baseline) | packet format artifact |

A workload whose required drain exceeds the 1000-cycle margin is refused
by the conservation gate; it is not silently truncated.

## Workload / collective semantics

| limit | value |
|-------|-------|
| collectives | ALLREDUCE, REDUCESCATTER, ALLGATHER, ALLTOALL, BROADCAST |
| collective claim | network-level schedule only |
| chunk ownership / rotation | **not modeled** — no full data-semantic collective claim |
| BROADCAST root | explicit declared source; `participants[0]` is never a law |
| ring divisibility | `B % k == 0` required (ALLREDUCE/REDUCESCATTER/ALLGATHER/ALLTOALL) |

## Timing claims

- `completion_cycles` is the cycle of the last ejected flit under a
  projection-defined injection schedule. It is **not** end-to-end
  application runtime (F-0003).
- ASTRA absolute timing is excluded (numerical validity NOT_ESTABLISHED;
  see `ENGINE-QUALIFICATION.md`).

## Serving

- Multi-instance liveness, scheduling and network-execution evidence are
  the subject of C7; the current candidate does not yet claim a qualified
  serving envelope.
- Integration `.et` fixtures are not vendored; the release gate fails on
  their absence rather than passing on a skip (C7.1/C10.1).

## Reproducibility

- A clean-machine release has not been qualified (C8). The container image
  is a moving tag in CI; external Docker dependencies are not all pinned by
  digest/commit. `release-manifest.json` is owed.

## Resource envelope

- Not measured (`docs/production/SUPPORTED-LIMITS.md` records only
  correctness limits; wall/memory envelopes are owed in C8).

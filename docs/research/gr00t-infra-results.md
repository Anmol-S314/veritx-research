# GR00T source/simulator infrastructure validation

## Scope

Source-only infrastructure for the pinned G1 apple-to-plate episode, not yet an internal GR00T operator/weight/activation extractor. No desktop changes or paid compute. Six GPT-6 Luna children inspected, implemented and reviewed; parent repaired the initial incomplete implementation. The child made an unrequested commit `e86f515b`; it was disclosed and left intact rather than rewriting history. Parent repairs remain uncommitted.

## Executed checks

- `gr00t_pipeline.py fetch`: exit 0; only episode-0 Parquet + MP4 downloaded from revision `ea7ac0b68f87da62f1e726771bba0fe74300802f`; exact sizes and hashes verified.
- `gr00t_pipeline.py export`: exit 0; regenerated 683-frame ledger is byte-identical to the audited source artifact, SHA-256 `0e4001d4554ae9d0519b336e5bdf2085b571ce5a6f4039c66daa7c2b4c7d8a96`.
- `gr00t_pipeline.py run-booksim`: exit 0; one observation projected onto an authored 2×2 mesh, 32-byte flits, max 16 flits/packet. **33 packets / 511 flits** all retired, individually reconciled against exact input source/destination/issue-time/size tuples. Last arrival **509 cycles**; request latency mean **41.7273**, p50 **43**, p95 **44**, p99 **47** cycles (nearest-rank percentiles over all 33 packets).
- Timeloop source sandbox build: `scons -j2`, exit 0 after three small compatibility substitutions in the copy (one missing `<cstdint>` include; two explicit string copies to satisfy modern `-Werror`). Vendor source unchanged. Timeloop mapper executable SHA-256 `b715f3a5cd8faa5b82a48711d74dc733a2b7f0f457aa636ed1b75d65f89209f7`.
- `gr00t_pipeline.py timeloop-smoke`: exit 0; 16×16×16 GEMM reports **4,096 actual computes / 4,096 modeled cycles**. Tiny illustrative architecture, not a GR00T layer or Thor calibration. PAT energy/area are uncalibrated and not promoted as results.
- Focused CLI tests plus existing BookSim parser and traffic-profile suites: **132 passed**, 0.30 s, including a real native trace-manager/retirement integration test. One warning: project pytest config names `timeout`, but pytest-timeout is not installed in this interpreter.
- `bash -n tracks/t3-topology/tools/build_timeloop_sandbox.sh`: pass; scoped `git diff --check`: pass. The new sandbox builder encodes the same successful fixes; its complete fresh build has not been separately repeated beyond the manual sandbox build.

## Saved evidence

`runs/gr00t-infra/2026-11-05-smoke/` contains:

- `booksim/`: config, trace, projection manifest, complete stdout/stderr, retired-packet CSV, result JSON with hashes.
- `timeloop/`: tiny GEMM config, complete logs, mapping/stats files, result JSON with hashes.
- `regenerated-episode.jsonl`: byte-identical source reconstruction.
- `timeloop-compatibility.patch`: exact scratch-only source substitutions.
- `checksums.json`: digests of the saved files.

Input paths inside configs/results identify the original temporary run directory. Use the documented commands with a fresh run directory to reproduce; do not treat copying the directory as rewriting execution history.

## Native BookSim mode check

A reviewer initially flagged the base builder's `traffic=uniform(...)` field. Native source inspection establishes that `sim_type=trace` dispatches to `TraceTrafficManager` (`trafficmanager.cpp:47–59`), whose constructor replaces that base traffic pattern and loads `trace_file` (`tracetrafficmanager.cpp:8–28`). Exact retirement-log reconciliation and a real native integration test verify that this run executes the projected trace. Switching to `sim_type=latency` would select a different traffic manager. The reviewer re-evaluated the native path, retracted that finding, and returned **no findings / verdict OK** (run `40229df1-558f-4b0d-b353-775c175a30f1`). Durable review: `/home/datavex/.pi/agent/sessions/--home-datavex-bruh-veritx-research--/subagent-artifacts/outputs/4b958775-86bc-44b6-9bea-9ab9b9aede93/.pi/gr00t-infra/correctness-review.md`.

## Boundaries and next step

The BookSim results apply to a **dataset-derived sensor/trajectory projection**, with no model computation. The Timeloop results prove tool execution for a GEMM fixture only. Neither supplies a complete GR00T inference trace, real robot performance, calibrated Thor power, or a compute/network total.

The next substantive stage is extracting a pinned GR00T operator graph and intermediate tensor shapes for a real observation, then mapping supported tensor operations through Timeloop and deriving communication under the chosen hierarchy. Unsupported operations and cache/scheduling assumptions must stay explicit.

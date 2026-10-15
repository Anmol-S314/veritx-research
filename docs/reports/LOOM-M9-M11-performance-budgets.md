# Loom UI performance budgets (proposal; not a test result)

These are explicit candidate acceptance budgets for M9-01. They are engineering targets, **not measured performance claims**. Before treating M9-01 or a downstream benchmark/gate as passed, the release owner must approve the budgets, pin the reference machine/browser/OS, build the reproducible harness, and attach raw results. If measurements miss a target, record the miss; do not revise budgets after measurement to manufacture a pass.

| Operation | Target fixture | Candidate budget | Measurement contract |
|---|---|---:|---|
| Project load to interactive editor | 256 nodes / 512 edges | P95 ≤ 2,000 ms | cold and warm runs reported separately; 30 repetitions; start at file selection, end at usable canvas |
| Pan/zoom | 256 nodes / 512 edges | ≥ 50 FPS P95; no interaction gap > 100 ms | 10-second scripted pan/zoom; record frame-time distribution, not an average-only claim |
| Matrix interaction | 10,000 access cells | P95 ≤ 100 ms per edit; visible-cell rendering | 100 selection/edit actions; include DOM/cell count and keyboard path |
| Trace seek | 100,000 trace frames | P95 ≤ 100 ms | deterministic fixture; report parse/index separately from seek; use same indexed trace for seek measurement |
| Peak app memory | graph + matrix + 100,000-frame trace | ≤ 1 GiB renderer working set | report browser process measurement method and fixture sizes; no extrapolation from smaller fixtures |

## Status

Proposed only. No reference hardware is named or approved and no benchmark result has been collected here. These targets are provisional and do **not** close M9-01, M9-09, M9-10, M9-11, or M11-36. The specific thresholds require product/release-owner review before they can be acceptance criteria. EOF

# GR00T simulation demo — completion handoff

## Goal and finish line

User authorized GPT-6 Luna subagents to finish: actual G1 dataset observations -> pinned GR00T architecture/operator/tensor-movement trace -> supported tensor operations through Timeloop -> mapped communication through BookSim -> reproducible comparison consumable in Studio. This is architecture-derived simulation, not claimed Thor measurement. Infrastructure smoke alone is NOT completion. Never claim real numerical GR00T inference if only static/meta shape tracing was possible.

## Working constraints

- Repo `/home/datavex/bruh/veritx-research`, branch `integration/studio-reconciliation`, HEAD `e86f515b5d790eb2f4a3f6feded898fcbda30072` at launch. About 593 existing changed/untracked paths. Preserve all concurrent changes.
- NO git commits, staging, resets, stashes, clean, branch switching, pushes, or broad formatting. Previous lean-delivery child violated no-commit instruction with e86f515b; user informed. Parent must check HEAD/index after writers. Use `worker`, fresh context, no inherited skills.
- Single repository writer at a time. Parallel scouts/reviewers are read-only. Dirty source prevents managed Git worktrees. Do not add packages/binaries to desktop bundle. No paid compute/provisioning, no large model/checkpoint/dataset download without justification/approval. Model configs/index headers and source are fine; do not execute arbitrary remote model code blindly. No physical robot commands.
- Stop and contact supervisor for architecture/product decisions or an unresolvable source/model mismatch rather than inventing sizes or silently weakening acceptance.

## Done and verified

- `tracks/t3-topology/tools/gr00t_pipeline.py`: pinned fetch (~3.1MB source), source Parquet+MP4 export -> byte-identical checked-in ledger, hash validation, deterministic bounded sensor packet projection, actual native BookSim smoke, optional Timeloop doctor/GEMM smoke.
- `tracks/t3-topology/tools/build_timeloop_sandbox.sh`: copies vendor source and applies <cstdint> and two explicit string copies for modern compiler. Only shell syntax tested; manual equivalent sandbox build passed.
- Native BookSim one-observation sensor smoke: 33 packets,511 flits,509cycle lastarrival, exact perpacket request/src/dst/size reconciliation. This is NOT GR00T internal model traffic.
- Timeloop sandbox `/tmp/srota-timeloop-build.yAXlOe`, mapper at `build/timeloop-mapper`, dynamic library at `lib/libtimeloop-model.so`. Real 16^3 GEMM smoke:4096 computes/cycles. This is NOT a GR00T layer result.
- `PYTHONPATH=tracks/t3-topology/dse python3 -m pytest -q tracks/t3-topology/dse/tests/test_gr00t_pipeline.py tracks/t3-topology/dse/tests/test_booksim_parse_output.py tracks/t3-topology/dse/tests/test_traffic_profile.py`:132passed. Warning:pytest-timeout absent.
- Source+result docs: `docs/research/nvidia-robotics-vla-workloads.md`, `gr00t-infra-results.md`. Existing plan `gr00t-infra-plan.md` completed.
- Saved evidence `runs/gr00t-infra/2026-11-05-smoke/` includes logs/configs/manifests/stats/checksums.
- GPT-6 Luna final infrastructure correctness review run40229df1-558f-4b0d-b353-775c175a30f1: no findings/OK. Reviewer initially wrongly claimed trace mode used uniform traffic; native TrafficManager::New selects TraceTrafficManager, whose ctor replaces traffic_pattern and loads trace_file. Keep native trace mode, don't change to latency based on that false positive.

## Pinned dataset facts

- HF `nvidia/PhysicalAI-Robotics-GR00T-X-Embodiment-Sim`, revision `ea7ac0b68f87da62f1e726771bba0fe74300802f`, subset `unitree_g1.LMPnPAppleToPlateDC`,episode0,CC-BY-4.0 attribution NVIDIA.
- Actual inputs `/tmp/srota-g1-fetch.C0fk4E/episode_000000.parquet` and `.mp4`; also HF cache `/tmp/gr00t-g1-dataset-audit/hf-cache`.
- Task: pick up apple, walk left, place on plate. 683 frames,640x480,H264,50fps;float32 timestamps0..13.64,frame_index1..683;43-D float64 state/action,344rawbytes each. Recorded action is demonstration, not model output. Full subset375MB,103matchingepisodes despite card102/metadata train0:100.
- Source ledger `tracks/t3-topology/data/public-robotics/gr00t-g1-apple-to-plate/episode_000000.events.jsonl`,SHA0e4001d4554ae9d0519b336e5bdf2085b571ce5a6f4039c66daa7c2b4c7d8a96. It stores summaries, not input values.
- H264 Bframes reorder demux/decode vs presentation: match decoded frame by PTS/timestamps, not file order.

## Model/source starting points

- Cached Isaac-GR00T repo `/tmp/pi-github-repos/runtime-eR3U34/c0cfdd02a19b04a265e6ace6e45dbcdf03442b11d882b547964efa239429692c`. Inspect actual revision and code; pin exact source/configs.
- Official NVIDIA model https://huggingface.co/nvidia/GR00T-N1.7-3B ; model card Thor onecam4denoise reports8.21/28.89/56.64ms stages,93.8ms total. Hardware guide says12.4Hz so don't combine versions/harnesses.
- G1 reference https://github.com/nvidia-isaac/isaac-os/blob/v0.11.0/operators/gr00t_n1_7/config/n1_7_g1.yaml declares ApplePnP checkpoint refs/pr/2; mock/hardware5models oneCUDAstream,ego float32[1,480,640,3],preprocess pixel_values[256,1536],inputids[1,77],backbonefeatures[1,77,2048],state/noise/actionlatent[1,40,132],decodedchunk16,43statejoints;action_head export owns whole denoise loop. Comments are declared bindings not verified runtime shapes.
- Separate appleSIM model outputs40steps and0.7sinference; mock/hardware0.2s. Do not mix with base model/1cam256x256 metadata.
- Actual architecture includes visual encoder, language backbone, flow matching action head; need extract supported operations/weights/activation shapes, dependencies and repeats from pinned real source/config/index or model shape propagation, not hand-written traffic constants.
- Existing `examples/gr00t_vla_robotics-v4.json`: basecard compute timing + authored8rankmesh,1kHzcontrol. NOT the G1 workload and no internal modeltraffic proof.

## Planned sequence with acceptance checks

1. [ ] Four parallel source/code scouts: model extraction feasibility, tensor-to-Timeloop, BookSim integration/scalability, Studio integration. Return exact contracts and unresolved facts. No repo mutations.
2. [ ] One backend writer: implement the smallest coherent pinned model-derived trace pipeline and comparison export; real source/input verification, explicit operation coverage/unsupported ops, no invented physical traffic, tests plus actual Timeloop/BookSim execution. Start one observation/explicit region, scale only where runtime/memory permit. A region-only result must state partial coverage; don't call full-model trace done. Ask supervisor if blocked.
3. [ ] Backend correctness/evidence review before UI work. Fix actual blockers sequentially, preserve source facts. Acceptance: same operator graph/assumptions bound to comparisons, commands logs and hashes, coverage explicit.
4. [ ] One UI writer wires the exported comparison into existing Studio workflow using discovered seam (not a separate toy app). Reuse visual language, show source-derived/modeled/simulated categories, operation coverage, timings, comparison controls/results. No fake live backend, no seeded results disguised as execution. Run TS/tests/build and browser gate if available.
5. [ ] Two independent reviewers + parent gates: full CLI path with pinned observation and available binaries, crosscheck shape/bytes/counts, Studio rendered flow/import/results, failure paths. Finish report only for met criteria; list any remaining model-extraction blockers explicitly.

## Scope limits

No claim of validated cache/memory transactions, kernel scheduling or real robot success without measurement. Model-derived ops can be static/meta traced and labeled architecture-derived. Distinguish hardware mapping choices from source model graph. Keep unsupported nonlinear ops visible rather than silently omit them. Do not naively add Timeloop and BookSim cycles: map clock domains and avoid double-counting memory/communication; report separate components if overlap unknown. Do not grow scope into new cloud providers, installers, autonomous robot control or more generic dataset research.

## Integration review / ROI simulation follow-up (2026-11-05)

- Fixed Studio importer P2: per-graph `timeloop_mapped_node_count` is bounded by node count, aggregate mapped coverage equals the sum of graph counts, and imported ROI results are checked against ONNX digest/index and common BookSim packet/flit counts.
- Added `tracks/t3-topology/tools/gr00t_roi_simulation.py`. It infers the pinned action-head graph and reads `node_MatMul_916` tensor shapes and dtype directly; inputs are float32 `[1,32,41,41]` and `[1,32,41,48]`, output `[1,32,41,48]`. A stale 8-bit `timeloop.stats.txt` was discovered alongside the newer 32-bit mapper output; this ambiguity is removed in the published result directory. The tool now checks Timeloop's resolved arithmetic and three storage widths against ONNX precision, and the result records the validated widths and authoritative stats filename. Fresh mapper stats resolve to 32 bits at all four arithmetic/storage levels. Timeloop maps one 41x48x41 matrix: 80,688 actual computes and 80,688 modeled cycles. Batch count is 32; no aggregate batch latency is claimed.
- The ROI transfers contain 718,976 bytes across 1,405 packets / 22,468 flits. Native BookSim ran the byte-identical hashed trace under two authored mesh layouts; both retired all packets/flits. Request-latency averages are 26.3922 cycles (2x2) and 24.9915 cycles (4x1), p95 29 and 25 respectively. These are diagnostic topologies, not hardware calibration. Traffic uses open-loop issue scheduling: each source's transfer stream starts at cycle 0, and output transfer is not gated on Timeloop completion. Therefore no causal end-to-end or total-latency claim is made.
- Clean ROI execution evidence is in `runs/gr00t-model/staticpick-v1-observation/action-head-roi-simulation/`; the superseded mixed-precision directory is preserved separately at `runs/gr00t-model/staticpick-v1-observation/superseded-mixed-precision-roi/`. `gr00t_model_trace.py --roi-result` now verifies graph identity/node shapes, resolved Timeloop stats and configs, trace digest, and both BookSim configs/packet logs before attaching the ROI. The updated run bundle and Studio public bundle contain the verified ROI and, after the full-graph expansion below, per-node static matrix mappings. Studio recorded-bundle loading uses the same strict size and digest validation as user imports.
- Final ROI-only validation before expansion: backend focused pytest 137 passed (one existing pytest-timeout warning); Studio 45 files / 289 tests, production build, and one focused GR00T Playwright test passed. The expanded validation below supersedes these counts.

## Full-graph static compute mapping expansion

Goal: map every statically shape-resolved MatMul/Gemm instance through Timeloop by deduplicating equivalent matrix signatures; publish per-node and graph-wide coverage without treating unsupported or dynamic operators as mapped.

Pinned ONNX shape inference finds 1,126 action-head MatMul/Gemm nodes with static inputs/output and 24 unique signatures; 96 backbone nodes with static shapes and 4 signatures (one signature is shared across graphs); 201 further backbone Gemm nodes have unresolved activation dimensions. No large weights are needed for shape-derived mapping. Other ONNX operators need an explicit supported/unsupported accounting, not a GEMM proxy.

1. Extend source extraction with tensor dtypes and robust MatMul/Gemm shape semantics (including Gemm transpose attributes); unit-test static/dynamic and batched shapes.
2. Map unique static signatures with Timeloop at source precision; validate resolved word widths and compute counts; bind each result to source graph digest/node IDs and report unresolved remainder.
3. Extend Studio bundle validation and display to show complete graph inventory, Timeloop-mapped supported-op count, dynamic/unsupported counts, and per-op mapping results. Keep BookSim as the existing bounded ROI until tensor placement/scheduling assumptions are explicitly justified.
4. Re-run backend/Studio tests and one complete static-signature mapping batch. Stop with a precise coverage statement; do not claim full-model or hardware validation.

Expansion result: 1,222 static MatMul/Gemm nodes mapped from 27 unique signatures. A fresh Timeloop rerun reproduced all 27 configs and stats bit-identically; mapper source, graph inventory, per-signature config/stats digests, and resolved widths are recorded. The run and Studio bundle bind per-node coverage and report 1,423 matrix candidates (1,222 mapped, 201 with unresolved shapes) and 10,693 other unmodeled nodes. The one-node BookSim ROI remains separate; full-model movement and communication are not simulated.

Final expansion validation: backend focused pytest **142 passed** (one pre-existing pytest-timeout warning); Python compilation passed; final bundle manifests and run/public comparison hashes verify. Studio Vitest **45 files / 290 tests passed**, `npm run build` passed, and the focused GR00T Playwright test passed. Mapping is still architecture-derived on the authored 16-PE template, not calibrated hardware, and there is no numeric inference, whole-graph schedule, or full-model latency. The next meaningful network step requires an explicit compute/tensor placement policy and target topology.

## Same-trace topology comparisons (curated presets complete; family coverage partial)

Goal: compare every declared `SWEEP_TOPOS` preset on the same saved ROI packet trace, preserving the authored memory/compute/consumer endpoint IDs. Use common router parameters where valid (8 VCs, 8-flit VC buffers); record topology-specific required settings. Keep 16-endpoint and 64-endpoint results in separate size groups. Rank by retired request-latency average/p95 under this trace only, not as a universal hardware winner.

1. Implement a sweep runner over the existing seven `SWEEP_TOPOS` entries; save configs, simulator logs, packet retirement logs, topology dimensions, and hashes. Acceptance: each successful variant conserves all source packets/flits and reports exact config/topology.
2. Attach the verified sweep to the comparison bundle and expose a Studio leaderboard grouped by endpoint count, including failed variants and limitations. Acceptance: importer rejects mismatched trace/artifact digests and UI labels diagnostic results honestly.
3. Run the seven presets and the backend/Studio checks. Stop at the ranking; do not infer a real chip winner without calibrated physical parameters, placement, and a more representative full-model traffic schedule.

Scope clarification: this result covers the seven entries in `SWEEP_TOPOS`, representing only mesh, torus, flatfly, and GEC families. The BookSim registry has 12 families (mesh, torus, cmesh, fly, qtree, tree4, fattree, flatfly, anynet, dragonflynew, GEC, SROTA); the seven-preset result is not an all-family comparison. AnyNet additionally needs a concrete graph file, and parameterizations/sizes must be evidenced rather than guessed. The existing ROI traffic touches only endpoints 0,1,2, so results answer only which exact configs route this adjacent-hop transfer pattern best.

Sweep result: **7/7 presets completed**, each retiring the same 1,405 packets / 22,468 flits from trace SHA-256 `8a5ba9059f55d13ac9f8f40a8efb0d3481f2595cdb7729935298d05aeece3a7f`. Within the 64-endpoint group, `mesh_8x8` ranks first (request average 24.991 cycles, p95 25), followed by `gec_express_k8` and `gec_mesh_k8` (26.991 / 27); `flatfly_64` (110.454 / 452), `torus_8x8` (412.910 / 872), and `gec_mecs_k8` (3,085.292 / 6,763) follow. The 16-endpoint `mesh_4x4` is ranked separately (24.991 / 25), not compared directly with 64-endpoint presets. Ranking is diagnostic only; it includes each preset's routing and GEC latency settings and uses fixed endpoints 0→1→2. The trace is open-loop; no end-to-end latency or physical best-topology claim.

Final curated-sweep checks: backend focused pytest **146 passed** (one pre-existing pytest-timeout config warning); Python compilation and `git diff --check` passed. Studio Vitest **45 files / 294 tests passed**, production build passed, and GR00T Playwright passed. The run/public bundle comparison JSONs are identical and both manifest file digests verify.

SROTA 8×8 paired run: the repository already contains `tracks/t3-topology/configs/srota64_rowcol.cfg` (k=8,c=1). On the same ROI trace, a SROTA config and 64-terminal mesh `min_adapt` control both used 4 VCs, 8-flit buffers, use_noc_latency=0, and routing_delay=1. Each retired all 1,405 packets / 22,468 flits. Both measured 26.991 average / 27 p95 / 14,607 last-arrival cycles, with identical packet-log hashes. The trace contains only 0→1 (913 packets) and 1→2 (492) traffic, so it does not exercise long-distance MECS express paths; this tie is not evidence that SROTA offers no benefit for nonlocal traffic. Artifacts and tool/template digests are stored in `runs/gr00t-model/staticpick-v1-observation/srota-paired-comparison/`. The verified pair is attached to both Studio bundles; run/public comparison files match and both manifest digests verify. Vitest, production build, and GR00T Playwright passed.

Remaining topology coverage: expand from the seven curated presets to one evidence-backed parameterization per registered family where available. Keep AnyNet tied to an explicit graph file and Dragonfly's 72-terminal minimum in a separate size group; never synthesize a universal family ranking from unmatched configs. Product direction: a source-to-NoC-IR pipeline with provenance/confidence per field, explicit unresolved assumptions, deterministic workload/config generation, and simulation evidence; defer RTL generation until the IR is validated and a synthesis/formal backend exists.

# Release evidence pin census — 2026-11-10

Method: read-only. Every row re-verified in this session by `sha256sum` / JSON parse / `runs/` artifact read. No builds, no simulations, no test-suite runs. Replaced the sub-agent lane that died on the provider outage; the work was done inline instead.

## A. Pinned artifacts (byte-exact)

| Artifact | sha256 (measured) | Pin source | Verdict |
|---|---|---|---|
| `docs/product/evidence/mixtral-74-81-8-162/revision-p-fd7e5e31be77-r02.json` | `51ebbc5429011b5f394cd216554d2cfc4022b3d5ae884facbdc4ca52380fef4a` | `tests/test_release_evidence_mixtral.py:PINNED` | **VERIFIED** (equals the pin) |
| `docs/product/evidence/mixtral-74-81-8-162/topology-p-fd7e5e31be77-r02.json` | `4315ad69bab4035251ca1bb3fec6c2219fcc6ad0132452c4684269298d5d9a82` | same | **VERIFIED** |
| `docs/product/evidence/release-workloads-20261110.json` | `8a89ccd32176eac7552ce2e42f4b49b5f2682607c22fd8e2ffdfecf5f3df4547` | not pin-tested; re-measured here | VERIFIED (sha256 recorded for future pinning) |
| `docs/product/evidence/toolchain-20261110.txt` | `0a8e90a6bb2175eb466e2e3bddedb32300e9f9fe22f5c1b9c030ba9e8f7d4010` | new this session | VERIFIED |
| `docs/product/evidence/suite-recheck-20261110.log` | `f84736edc304e70c94a92dcbb72a45795db72d8b157a100715f4d3ffcca33021` | new this session | VERIFIED |

## B. Contract numbers quoted in docs (re-derived here)

| Claim | Measured | Verdict |
|---|---|---|
| design_hash `sha256:ab7bce8f…ad392f0` | identical in revision JSON, topology JSON, and `DESIGN_HASH` in the pin test | **VERIFIED** |
| 74 endpoints / 81 routers / 81 seats / 162 shared links / 0 channels | `topology.counts = {channels: 0, endpoints: 74, routers: 81, seats: 81, shared_links: 162}` | **VERIFIED** |
| 17 approved workloads + 1 excluded input | parsed from the pinned JSON: `approved_workloads` = 17, excluded = 1 | **VERIFIED** (the earlier "16" figure was wrong; docs corrected) |
| GEC synth: 668,093 cells / 200,432 `dfxtp` / 4,263,268.8 µm² | `runs/chipyard-gec6/physical/runs/gec6-synth/06-yosys-synthesis/reports/post_dff.json` (`num_cells` 668093, `dfxtp_2` 200432) + `post_dff.rpt` ("Chip area for module '\CompiledGecPreview': 4263268.812783") | **VERIFIED** |
| router-slice: die 9,764.35 / core 6,718.94 µm²; 952 instances (95 sequential / 415 fill / 96 tap); util 82.1% | `runs/chipyard-router-physical/runs/router-slice/56-openroad-irdropreport/state_in.json` → sequential 95, fill 415, tap 96, `design__instance__utilization` 0.821043 | **VERIFIED** |
| router-slice: 55 max-slew violations at `max_ss_100C_1v60` | same file: `design__max_slew_violation__count__corner:max_ss_100C_1v60` = 55 (also 44 at `nom_ss_100C_1v60`) | **VERIFIED** |
| router-slice: setup WS **+0.564 ns** | `timing__setup__ws__corner:max_ss_100C_1v60` = 0.564176721 | **VERIFIED** (worst setup corner, not the default corner — the docs' "default corner" wording is imprecise; the number itself reproduces) |
| router-slice: hold WS **+0.118 ns** | `timing__hold__ws__corner:min_ff_n40C_1v95` = 0.117524548 | **VERIFIED** (worst hold corner) |
| Full-top post-CTS STA: setup WNS −4.424 ns / TNS −11,389 ns; hold 0/0 | `~/librelane-spike/project_top/runs/RUN_2026-11-10_07-07-09/36-openroad-stamidpnr-1/{wns.max.rpt,tns.max.rpt,wns.min.rpt}` | **VERIFIED** (measured earlier today) |

## C. Stale / imprecise pins found

| Item | Problem | Action |
|---|---|---|
| "16 approved workloads" (status doc, plan) | pinned JSON holds 17 | corrected in the status doc and plan checkpoint |
| "twelve capabilities" | `READY_CAPABILITIES` holds 11 | corrected |
| "frontend 310/311" / "318/318" | suite is 325/325 today | corrected |
| router-slice "+0.564/+0.118 (default corner)" | those are the **worst** setup/hold corners (`max_ss_100C_1v60`, `min_ff_n40C_1v95`); the default (nom_tt) values are +3.540/+0.340 | wording corrected in the plan table; numbers unchanged |
| "mesh8x8 PASS" | the log/artifacts lived only in `/tmp/opencode/mesh-rerun/` and were destroyed at the 2026-11-10 service restart; `runs/` has no copy | recorded as **unsubstantiated until the matrix re-run lands and is archived** |
| backend DSE full unit suite | has never completed cleanly this cycle (two attempts died: one at the service restart, one at 61% with no summary) | still **NOT RUN** as a gate; the failure count is unknown |

## D. Verdict

Every machine-checkable release artifact that exists in the tree reproduces byte-exact or numerically as documented. Nothing pinned has drifted; four *narrative* claims were stale and are now corrected. The open gaps are not pins — they are unrun gates (backend suite, release matrix) and unpinned logs, which is exactly what `scripts/sequential-gates.sh` exists to produce.

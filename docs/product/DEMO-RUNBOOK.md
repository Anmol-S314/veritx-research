# VERITX Demo Runbook

Commands that work at the release candidate. Run from the repository root
with the DSE package on `PYTHONPATH`.

## 0. Build the release backends

```bash
make release-build            # BookSim + ASTRA + Ramulator + manifests
ls third_party/booksim2/src/booksim.build-manifest.json
```

The manifest records source revision, dirty state, binary sha256/size,
compiler and recipe.

## 1. Compile a fabric (canonical, no backend)

```bash
PYTHONPATH=tracks/t3-topology/dse python3 -m veritx_dse.cli compile \
  --preset mesh4 --policy baseline_deterministic_v2 \
  --store /tmp/veritx-demo/store
```

Prints the resolved artifact hashes (`fabric_hash`,
`resolved_fabric_hash`) and explicitly states that backend execution and
verification are **not** performed by compile.

## 2. Exercise a qualified backend (real BookSim)

```bash
export VERITX_BOOKSIM_BIN=$PWD/third_party/booksim2/src/booksim
PYTHONPATH=tracks/t3-topology/dse:tracks/t3-topology/dse/tests \
  python3 -m pytest tracks/t3-topology/dse/tests/test_backend_booksim_execution.py \
  -q -p no:randomly -k "real"
```

The real mesh/anynet gates execute the fork, enforce packet/flit
conservation and observe the executed first-hop route, binding the route
dump digest into the evidence.

## 3. Run the independent validation corpus

```bash
export VERITX_BOOKSIM_BIN=$PWD/third_party/booksim2/src/booksim
PYTHONPATH=tracks/t3-topology/dse:tracks/t3-topology/dse/tests \
  python3 -m validation.harness.run \
  --all --mutations --metamorphic --engines --intervention
```

`V01`–`V14` PASS, mutations CAUGHT, engine gates pass, ASTRA numerical
`NOT_ESTABLISHED`. Reports land in `validation/reports/`.

## 4. Full fast tier

```bash
PYTHONPATH=tracks/t3-topology/dse:tracks/t3-topology/dse/tests \
  python3 -m pytest tracks/t3-topology/dse/tests -q -p no:randomly -k "not real"
# 3532 passed, 13 skipped
```

## 5. Certified optimization (reference)

`python3 -m veritx_dse.cli optimize --fixture <v3-request.json>
--evaluate booksim --binary <booksim> --run-root <dir> --study-out <dir>`
drives the certified path; an unqualified producer yields no EVALUATED
record and an empty Pareto (covered by
`test_certified_admission.py::test_optimizer_certified_boundary_refuses_unqualified_producer`).
A pinned binary and its manifest are required.

## 6. Live product flow (Studio gateway)

```bash
export VERITX_BOOKSIM_BIN=$PWD/third_party/booksim2/src/booksim
export PYTHONPATH=tracks/t3-topology/dse
uvicorn veritx_dse.gateway.app:app --port 8123
# in another shell:
cd apps/studio && npm install && npm run dev   # Vite proxies /gw -> 8123
```

Then, in the browser:

```text
create project -> choose workload -> edit draft -> Compile design
-> CompilationView + certificate PASS (10/10) -> Run Simulation
-> job polls QUEUED/PREPARING/RUNNING/FINALIZING -> EVALUATED
-> Run detail -> "Why can I trust this?" -> evidence + RunBundle
```

Product flow details: `docs/product/PRODUCT-API.md`.

## Known-good posture to communicate

- Compile is canonical and prints hashes; it is not a simulation.
- A metric's evidence (backend, producer, recipe, route observation) is
  inspectable; ASTRA absolute timing is not qualified.
- The release is **NOT READY** (`docs/production/PRODUCTION-SEAL.md`);
  this runbook demonstrates the working scientific core, not a release.

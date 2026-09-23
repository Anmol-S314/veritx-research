# VERITX-INTEGRATE — Reclamation Ledger

Product tree: `veritx-integrate` (this branch). One writer. Historical branches are
capability warehouses; nothing is merged wholesale. Every row records the source
ref/path and the reclamation status.

## 0. Source inventory (verified in this worktree)

| Ref | Commit | Verified |
|-----|--------|----------|
| integration/canonical (pin) | `2f727dd1503c00697b2afaeda75a7fa6947dd1c3` | yes |
| integration/canonical (local, 1 commit ahead of pin) | `96603ae21142ef48816ad9443701eb37ab8b3ddd` | yes |
| audit/wave-b-intent-identity | `3d70ffd93bc7a5a8b7491fa44191921b24329be1` | yes |
| audit/wave-b-mapping-artifact-wip | `5509b9dce5b05844c3596d7a427ea03bd4c98d20` | yes |
| wave-c/unified-control-plane | `8455c0450e27486ae034028b76c9a05b94f2ea72` | yes |
| wave-d/distributed-semantics | `d3f3bd63b952b54fb5cac688532caf83ca66c512` | yes |
| wave-e/system-performance | `16ebd71bde25e3045b51cba8f06f88c34ff1330d` | yes |
| wave-f/design-optimization | `d178c90ee0a08663538dce68b85d690a74ff1a15` | yes |
| audit/wave-f-parity-ledger | `fef627fa3e171ea37fb9f7f6cd5aefbd649184dd` | yes |
| integration/p1-product-rt-candidate | `26e6f9dcb1bba85e7d97f4663c5da29e14c9b721` | yes |
| integration/p1-product (pin) | `b1b6ed5579210a48a4617bb36bb3d82148446f43` | yes |
| p1/fabric-compiler-productization | `662e7ce6e4ec5462b7e710eece6a5a78e35093fb` | yes |
| p1b/verified-evaluation | `3def89c3a146490a91288210ba6252af51cd8eba` | yes |
| p1c/workload-requirements | `33703bd04df2a737c0cff6e75874274fa5d72425` | yes |
| p1x/product-contracts | `ec747ffe9a4f25c89335d0bae6dcc7f76d57664f` | yes |
| serving-leg | `ffee33334c7b9c24d6a5597d4e87cdb0c644b9d0` | yes |
| t3-rtl-noc-backup-20260815 | `f8ab4a63ff3ea5058d04f64ed6bb0338f58b0e70` | yes |

**Base-of-work decision.** The mandate pins canonical at `2f727dd1`. The local
`integration/canonical` is exactly one commit ahead (`96603ae2` "Serving: dense
data-parallel quorum semantics over the fixed canonical fabric", direct child of
the pin, canonical message). Per the newer-equivalent rule the integration is
built on `96603ae2`. Nothing older is promoted over it.

**Divergent remote tips (not used):** `origin/wave-e/system-performance`
(`fbc71d74`) and `origin/p1c/workload-requirements` (`24c2ab63`) are divergent
from their pins (neither ancestor nor descendant). The pinned commits are used,
per §1. `origin/p1b` tip `f67c2408` is older than its pin (the pin contains it).
`origin/integration/p1-product` tip equals the P1X pin `ec747ffe` (divergent from
the `b1b6ed55` pin); the RT candidate `26e6f9dc` carries the whole evolved RT
lineage and is the product source per §2 precedence.

**Environment note (pre-existing, not introduced here):** the BookSim2 binary was
built for the real-workload gates. Canonical test
`tests/test_cli_compile_surface.py::test_no_booksim_binary_needed_for_canonical_compile`
asserts the binary is ABSENT (a no-binary dev proof) and therefore fails in this
environment by design. It passes in its intended condition. Baseline full-suite
result before any integration work: **3088 passed, 13 skipped, 1 failed (that
test only)** in 1235s.

## 1. Reclamation rows

Statuses: KEEP_CANONICAL / COPY_VERBATIM / COPY_AND_ADAPT / TEST_ONLY /
RETAIN_RESEARCH / SUPERSEDED / REJECTED.

### Core spine support

| Capability | Source | Source path | Destination | Status |
|------------|--------|-------------|-------------|--------|
| canonical_json / sealed spec types | p1-product-rt-candidate `26e6f9dc` | veritx_dse/core/spec.py | veritx_dse/core/spec.py | COPY_VERBATIM |
| Wave-E exact rational time (QTime) | p1-product-rt-candidate `26e6f9dc` | veritx_dse/core/time.py | veritx_dse/core/time.py | COPY_VERBATIM |
| sealed Pareto gate (pareto_with_scope) | p1-product-rt-candidate `26e6f9dc` | veritx_dse/core/comparison.py | veritx_dse/core/comparison.py | COPY_VERBATIM |
| typed refusal classes (TimeoutError/BackendFailure/BackendTimeout) | p1-product-rt-candidate `26e6f9dc` | veritx_dse/core/errors.py | veritx_dse/core/errors.py | COPY_AND_ADAPT (additive merge; canonical docstrings kept) |
| run-directory paths (VERITX_RUNS_DIR/RESULTS_DIR/SYNTH_DIR/new_run_dir) | p1-product-rt-candidate `26e6f9dc` | veritx_dse/core/paths.py | veritx_dse/core/paths.py | COPY_AND_ADAPT (additive merge) |
| content_id/content_hash/FrozenMap/freeze | current canonical | veritx_dse/core/artifact.py | (already present) | KEEP_CANONICAL |
| CompileRequest / validation / semantics v2 | current canonical | veritx_dse/model/compile_model.py | (already present) | KEEP_CANONICAL |
| canonical compiler (CompiledFabric) | current canonical | veritx_dse/compiler/canonical.py | (already present) | KEEP_CANONICAL |
| ResolvedFabric / fabric artifact / route model | current canonical | veritx_dse/model/* | (already present) | KEEP_CANONICAL |
| authenticated backend evidence | current canonical | veritx_dse/backend/evidence.py | (already present) | KEEP_CANONICAL |
| WorkloadGraph / ParallelismShape / rank namespace | current canonical | veritx_dse/workload/graph.py | (already present) | KEEP_CANONICAL |
| messages / traffic / ParticipantEndpointMapping | current canonical | veritx_dse/workload/messages.py, traffic.py | (already present) | KEEP_CANONICAL |
| ASTRA projections/namespace/execution | current canonical | veritx_dse/backend/astra*.py | (already present) | KEEP_CANONICAL |
| BookSim preparation/execution | current canonical | veritx_dse/backend/booksim_*.py | (already present) | KEEP_CANONICAL |
| real request-driven serving loop + DP quorum + TP groups | current canonical (`96603ae2`) | veritx_dse/simulation/serving_*.py | (already present) | KEEP_CANONICAL |
| application service/store/resources/compile_intent | current canonical | veritx_dse/application/{service,store,resources,compile_intent}.py | (already present) | KEEP_CANONICAL |

(statuses below to be filled as each phase lands)

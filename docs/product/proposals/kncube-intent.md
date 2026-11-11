# KNCube general intent — audit and correction — 2026-11-10

Method: read-only inspection plus **direct execution** of the compiler and the composed-family path on a general KNCube intent. No sub-agent (the lane died on the provider outage); the work was done inline. No claim below is copied from a previous document — each was measured today.

## 1. Correction to the tree's own audit text

`tracks/t3-topology/dse/tests/test_family_bad_design.py` (`NOT_COVERED["kncube"]`) states:

> *"no kncube general-intent/native-equivalence checker exists: KNCUBE_BLOCKER is declared but never raised anywhere in project_top_rtl.py; kncube has no CompileRequestV4 topology intent class (structured family 'kncube' is not registered in STRUCTURED_FAMILIES, so no correct kncube intent can be compiled)"*

**That statement is false in the current tree.** Measured today:

| Claim in the note | Measured reality |
|---|---|
| "kncube is not registered in STRUCTURED_FAMILIES" | **It is registered** — `veritx_dse/model/topology_artifact.py:1228`: `"kncube": {"fields": ("radix", "dimensions", "wrap"), "minimums": {"dimensions": 1}, "bool_fields": ("wrap",), "build": lambda p: kncube_graph(radix=p["radix"], dimensions=p["dimensions"], wrap=p["wrap"])}` |
| "no CompileRequestV4 topology intent class" | **A general intent exists and validates** — `StructuredTopologyIntent(family="kncube", params={"radix":3,"dimensions":2,"wrap":True})` → accepted; `params()` → `{'family': 'kncube', 'params': {...}}` |
| "no correct kncube intent can be compiled" | **It compiles** — `FabricCompiler().compile(request)` → `status = COMPILED` (measured today, 3-agent request: 2 compute + 1 HBM, AXI5 intents, HBM0 window) |
| "no checker" | `_family_id_from_topology()` maps both `kind == "kncube"` and `kind == "structured" with family == "kncube"` → `"kncube"` (`project_top_rtl.py:4157`, `:4173`) |

**Material consequence:** the composed-family path accepts a *general* KNCube request end-to-end at the parameter level:

```
composed_family_params_from_request(kncube_request, compiled)
  → family = "kncube", n_routers = 9, routing_law = "ANYNET_MIN_HOPS", dst_w = 4
```

The KNCube row therefore **is not** blocked on a missing intent class. What is actually broken is narrow and fixable.

## 2. What was genuinely broken (measured) — and what is now fixed

1. **The release runner's kwargs were wrong — FIXED 2026-11-10.** `scripts/complete_design.py` `FAMILY_REQUESTS["kncube"]` passed `{"family": "kncube", "params": {"k": 3, "n": 2}}`; the registered field names are `radix` / `dimensions` / `wrap`, so the request raised `TopologyIntentError: family 'kncube' takes ['dimensions', 'radix', 'wrap'], got unknown ['k', 'n']`. It now passes `{"radix": 3, "dimensions": 2, "wrap": True}`.
2. **The release matrix hard-BLOCKED the row — REMOVED 2026-11-10.** The matrix emitted `BLOCKED / KNCUBE_BLOCKER` with the detail "no general saved-request KNCube topology exists; refusing the old torus-backed substitute" — now measured false. The row runs the generic path (real request → compile → compose), and the native-equivalence gap is recorded as a manifest blocker `KNCUBE_NATIVE_EQUIVALENCE_UNVERIFIED` instead of a false BLOCKED stage.
3. **The torus-derived harness special case is no longer used by the matrix.** `kncube_lint_and_sim()` remains as a refusal-guarded probe (`tests/test_complete_design.py::test_kncube_runner_refuses_a_torus_source_instead_of_substituting` asserts it refuses a torus source with `KNCUBE_GENERAL_INTENT_AND_NATIVE_EQUIVALENCE_CHECKER_MISSING`) — it must keep refusing, because substituting a torus fabric for KNCube is exactly the dishonesty this row exists to prevent.
4. **Binding conformance for KNCube now exists (landed by the parallel lane, 2026-11-10).** `tests/test_family_bad_design.py::test_kncube_saved_intent_binds_general_radix_and_dimensions` asserts the general intent binds (9 routers, 24 channels unwrapped / 36 wrapped, 3×3 coordinates) and that a **mismatched `wrap` is refused** by `check_composed_family_profile` with `UNSUPPORTED_COMPOSED_FAMILY`; `test_kncube_supports_arbitrary_dimension_count` asserts radix 2 × 3 dimensions → 8 routers / 24 channels / 3-D coordinates. The old "no intent class / not registered in STRUCTURED_FAMILIES" note in that file has been corrected.
5. **Still genuinely open:** native equivalence against the external Constellation KNCube source (`KNCubeSourceSpec`; the fork is operator-owned and absent from this checkout). The guard module `veritx_dse/product/family_binding_guards.py` (landed today) raises `KNCUBE_GENERAL_INTENT_AND_NATIVE_EQUIVALENCE_CHECKER_MISSING` by design rather than approximating that equivalence.

## 3. Proposed change (one line + one test + one doc fix)

| # | Change | File | Verification |
|---|---|---|---|
| 1 | `FAMILY_REQUESTS["kncube"] = ("kncube", "StructuredTopologyIntent", {"family": "kncube", "params": {"radix": 3, "dimensions": 2, "wrap": True}})` | `scripts/complete_design.py` | `make_family_request("kncube")` no longer raises; `run_composed_family` emits the family from its own bundle |
| 2 | Replace the `kncube` special-case branch in `release_matrix` with the generic path (keep `kncube_lint_and_sim` only as a fallback probe) | `scripts/complete_design.py` | the release-matrix row's verdict comes from a real KNCube request |
| 3 | Correct the `NOT_COVERED["kncube"]` note to state the true remaining gap (native-equivalence checker + binding guard), and keep it in `NOT_COVERED` (the guard does not exist yet) | `tracks/t3-topology/dse/tests/test_family_bad_design.py` | the suite's `set(NOT_COVERED) == FAMILIES14 - {"srota"}` assertion still holds |
| 4 | Add a test: a general KNCube intent compiles and composes; a corrupted `(radix, dimensions, wrap)` is refused by name | new test file or `test_family_bad_design.py` | pins the row's positive path, not only its refusal path |

## 4. Honest status of the KNCube row

- **General intent:** exists, validates, compiles — measured today.
- **Composed-family parameters from a general KNCube request:** exist — measured today.
- **RTL emission + simulation from a general KNCube request:** **MEASURED 2026-11-10 — lint PASS, sim PASS, 13/13 scenarios true** (`run_composed_family` on a real `StructuredTopologyIntent(family="kncube", params={"radix":3,"dimensions":2,"wrap":True})` request: allow_write_init0, allow_read_init0, deny_write_init1, allow_read_init1, error_miss, error_slv, ordering_stall, ordering_inorder, backpressure_stall, backpressure_release, concurrent, conservation, drain — all True).
- **Release-matrix row:** the wrong kwargs and the false BLOCKED row are fixed (2026-11-10); the row's verdict comes from a real KNCube request and will be recorded by the next `--release` run.
- **Native equivalence vs Constellation:** still blocked on the operator-owned fork.
- `final_implementation` remains `false`; no row is upgraded by this audit.

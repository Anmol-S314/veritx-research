# CMesh requalification — 2026-10-27

Durable evidence for `veritx_dse.application.booksim_qualification_registry`
record `CERTIFIED_BOOKSIM_CMESH_DOR_XY_V1`. This note closes the obligation
recorded when the capability was withdrawn: a clean attributable producer
build and re-pin, an exact canonical endpoint/native terminal bijection, and
executed conservation evidence.

## Producer build and re-pin

The producer source subtree `third_party/booksim2` was clean at the pinned
revision. A clean in-place build from that tracked source was performed with
the release recipe and reproduced the pinned bytes exactly:

```sh
make -C third_party/booksim2/src clean
make -C third_party/booksim2/src -j2 CXX=g++
python3 scripts/write_build_manifest.py third_party/booksim2/src/booksim \
    --recipe-version booksim2-fork/v2 --compiler g++ \
    --build-config Release --flag=-O3 --flag=-g \
    --source-path third_party/booksim2
```

The clean rebuild reproduced the pinned bytes exactly; the manifest written
beside the binary verifies:

| Fact | Value |
|---|---|
| `binary_sha256` | `ec80b469c885abfa2f15f78c2a94a45095ac32714c1ac0855321ba56d8d85d0e` |
| `binary_size` | `24884344` |
| `source_revision` | `f71b10b39892571e9d4ed907fef23e85360c62b6` |
| `source_paths` | `third_party/booksim2` |
| `source_dirty` | `false` |
| `recipe_version` | `booksim2-fork/v2` |
| `build_config` | `Release` |
| `compile_flags` | `-O3 -g` |
| `compiler` | `g++ (Ubuntu 15.2.0-16ubuntu1) 15.2.0` |
| manifest SHA-256 | `1c588e7a79f964ecf088b7f78a0d20660dcec86ada585097bfac7c217aebd1d2` |

`resolve_producer_identity()` verifies the manifest and
`assert_pinned_producer()` accepts it (`manifest_verified=True`,
`dirty=False`, known revision and recipe). The binary itself contains the
source guards `CMesh supports c = 2 or c = 4 only` and
`CMesh c = 2 supports dor_no_express only`.

## Endpoint mapping and conservation

The canonical terminal map is `veritx_dse.backend.cmesh_terminal_map`.
For a square `k x k` router grid with concentration `c` in `{2, 4}`, the
native terminal row-major grid is folded onto the router grid with
`cx = c // 2`, `cy = 2`. The map is a bijection over the full terminal
universe: canonical endpoints `0..E-1`, native terminals `0..E-1`, and
router/local-port seats all exactly once.

Executed against the manifest-pinned producer, on the shipped example
geometries:

| concentration | k | routers | endpoints | injected flits | accepted flits | native dump rows | ejection-port mismatches |
|---|---|---|---|---|---|---|---|
| 2 | 4 | 16 | 32 | 36064 | 36064 | 512 | 0 |
| 4 | 3 | 9 | 36 | 37520 | 37520 | 324 | 0 |

The executed route observation is `EXECUTED_ROUTE_OBSERVED`; every
`(router, native terminal)` ejection row was compared with the canonical
`(router, local port)` binding, including idle seats. Both runs produce
`execution_fidelity = QUALIFIED` with `producer_dirty = false` under
`require_pinned_producer=True`.

## Reproduce

```sh
cd tracks/t3-topology/dse
python3 -m pytest tests/test_booksim_cmesh_projection.py -q
```

The module asserts the pinned-producer path
(`test_manifest_pinned_producer_executes_c2_and_c4_with_exact_terminal_bijection`)
as well as the canonical mapping counterexamples, trace conservation and the
dirty-source diagnostic. A source-copy build remains diagnostic only; it is
not the authority for the pinned binary.

## Scope and limitations

Qualified only for `MaterializedFamily.CONCENTRATED_MESH`, square `k x k`,
uniform `seat_capacity` 2 or 4, routing class `DOR_XY` through
`dor_no_express`, one traffic class, identity VC transitions, unit link
weights and `use_noc_latency = 0`. Express links, parallel channels,
non-square grids, concentrations other than 2 or 4, and multi-class traffic
remain outside this envelope. The separate
`CERTIFIED_BOOKSIM_MESH_DOR_CLASS_VC_V1` profile is qualified under its own
evidence in `docs/product/CLASS-VC-REQUALIFICATION-2026-10.md`; it is not
covered by this note.

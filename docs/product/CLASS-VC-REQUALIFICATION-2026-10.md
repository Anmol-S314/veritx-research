# Class-VC mesh requalification — 2026-10-27

Durable evidence for `veritx_dse.application.booksim_qualification_registry`
record `CERTIFIED_BOOKSIM_MESH_DOR_CLASS_VC_V1`. This note closes the
withdrawal recorded when the producer source implemented per-class VC tables
but the manifest-pinned binary predated them. The obligation was a clean
attributable producer build, a verified manifest re-pin, and executed
evidence that the shipped binary accepts the canonical class-VC projection,
enforces each class's VC range, and conserves traffic.

## Producer build and re-pin

The producer source subtree `third_party/booksim2` was clean at the pinned
revision. A clean in-place build from that tracked source with the release
recipe reproduced the pinned bytes exactly:

```sh
make -C third_party/booksim2/src clean
make -C third_party/booksim2/src -j2 CXX=g++
python3 scripts/write_build_manifest.py third_party/booksim2/src/booksim \
    --recipe-version booksim2-fork/v2 --compiler g++ \
    --build-config Release --flag=-O3 --flag=-g \
    --source-path third_party/booksim2
```

The manifest written beside the binary verifies:

| Fact | Value |
|---|---|
| `binary_sha256` | `ec80b469c885abfa2f15f78c2a94a45095ac32714c1ac0855321ba56d8d85d0e` |
| `binary_size` | `24884344` |
| `source_revision` | `f71b10b39892571e9d4ed907fef23e85360c62b6` |
| `source_dirty` | `false` |
| `build_recipe_version` | `booksim2-fork/v2` |
| `compiler` | `g++ (Ubuntu 15.2.0-16ubuntu1) 15.2.0` |
| `build_config` / flags | `Release` / `-O3`, `-g` |

This is the same clean producer pin recorded in
`docs/product/CMESH-REQUALIFICATION-2026-10.md`. No historical run under
`runs/` was reused.

## Certified scope

| Fact | Value |
|---|---|
| profile | `CERTIFIED_BOOKSIM_MESH_DOR_CLASS_VC_V1` |
| projection semantics | `booksim2-fork+mesh-dor-class-vc/v1` |
| lowerer | `DORXY-MC/1` |
| family / geometry | `MaterializedFamily.MESH`, square `k x k`, `seat_capacity 1` |
| routing | `DOR_XY` through `dim_order` |
| traffic classes | two or more canonical classes, one disjoint VC per class |
| VC transitions | identity only |
| link latency | `use_noc_latency = 1` (native mesh links are latency 1 under this pin) |

Wider-than-one-VC class ranges still refuse: the profile's qualifier requires
`start == end` for every class because the current ABI has no VC-preserving
allocator. Non-identity transitions, non-mesh topologies, and other routing
functions also refuse.

## Executed evidence

The canonical design is a `k = 4` mesh with 16 routers and 8 endpoints, one
blocking dependency pair in each direction, and two collectives declaring
traffic classes `a0` and `b0`. The prepared config pins `topology = mesh`,
`routing_function = dim_order`, `num_vcs = 2`, `classes = 2`,
`use_noc_latency = 1`, and the class table
`mesh_class_vc_begin = mesh_class_vc_end = {1,0}`.

The dense class order is `('a0', 'b0')`, so the canonical class-to-VC ranges
are `((1,1), (0,0))`: class 0 (`a0`) owns VC 1 and class 1 (`b0`) owns VC 0.
The run was executed with `require_pinned_producer=True`:

| Evidence | Value |
|---|---|
| execution fidelity | `QUALIFIED` |
| producer revision | `f71b10b39892571e9d4ed907fef23e85360c62b6` |
| `producer_dirty` | `false` |
| route observation | `EXECUTED_ROUTE_OBSERVED` |
| route dump SHA-256 | `da69bf1fe6d078e0c49540672d0875244c0994a5bb12da381e5844c6839bef53` |
| expected / injected / accepted flits | `33376` / `33376` / `33376` |
| expected packets | `4256` |
| per-class flits | `a0`: 16688 injected, 16688 accepted; `b0`: 16688 injected, 16688 accepted |
| native class-VC observations | class 0: VC 1 × 5852; class 1: VC 0 × 5852 |
| completion cycles | `5195` |

Every observed native input VC is the single VC assigned to its class, and
the per-class observed classes are exactly the two declared classes. There
are zero ejection-port or route mismatches: the execution path returns
`EXECUTED_ROUTE_OBSERVED` only after the canonical/native route comparison
succeeds.

A deliberate diagnostic config confirms the shipped binary enforces the
table rather than merely accepting it. Setting a stock read-request VC of 0
for class 0, whose certified VC is 1, makes the pinned producer refuse with
`mesh class VC error: illegal VC for class 0`; it does not widen the class
range. The independently built source copy is also exercised against
out-of-range tables, incomplete tables, foreign trace class ids and a
non-mesh routing function, so the fail-closed guards are pinned separately
from the producer attribution.

## Reproduce

```sh
cd tracks/t3-topology/dse
python3 -m pytest tests/test_booksim_class_vc.py -q
```

The module asserts the qualification record and evidence paths, the live
assessment (`READY`), the pinned-producer canonical execution with exact
per-class VC membership and conservation
(`test_manifest_pinned_producer_executes_class_vcs_with_exact_ranges`), and
the shipped binary's refusal of a conflicting stock VC. The source-copy
builds remain diagnostic only and are not the authority for the pinned
binary.

## Scope and limitations

Qualified only for the envelope in the table above. The profile is a
traffic-class-to-VC restriction for mesh DOR-XY; it does not claim a cache
coherence protocol, directory state, exclusivity, ownership, writeback
races, wider per-class VC ranges, non-identity VC transitions, or shared-wire
topologies. `CERTIFIED_BOOKSIM_CMESH_DOR_XY_V1` is a separate family and is
covered by `docs/product/CMESH-REQUALIFICATION-2026-10.md`.

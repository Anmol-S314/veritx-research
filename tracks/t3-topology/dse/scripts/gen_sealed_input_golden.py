#!/usr/bin/env python3
"""Generate the SEALED PREPARED-INPUT golden digests (PHASE B.2 §10).

WHY THIS EXISTS
===============

PHASE B.1 changed how a design request is expressed (schema 4, typed topology
intent) without touching the BookSim fork or either sealed profile. The
required proof is not "the Python source files are unchanged" — it is:

    SAME SEALED SCIENCE  ->  SAME PREPARED BACKEND INPUT BYTES

So this records, for the sealed profiles, the exact content digests of every
byte the backend would receive:

    config bytes        the rendered BookSim config
    trace bytes         the rendered physical-traffic trace
    topology bytes      the rendered `.anynet` link file (AnyNet only)
    prepared_id         PreparedBookSimInput's own content identity, which
                        binds the canonical artifact hashes, the profile and
                        its semantics/lowerer versions

Run against the frozen baseline to (re)generate, and against HEAD to prove
non-regression. A mismatch is a change to the sealed science.

A mismatch is therefore never resolved by regenerating the fixture until the
test passes. It is resolved one of two ways: revert the change that moved the
bytes, or RE-FREEZE deliberately. A re-freeze requires a PROVENANCE entry
naming the commit that moved them, exactly what moved, and why the move is the
intended science. Regenerating without an entry destroys the only record of
what changed, which is the failure mode this fixture exists to prevent.

The fixture is a CANONICAL FIXTURE with a fixed seed, so both runs describe
the same science.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

DSE = Path(__file__).resolve().parent.parent
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

EXAMPLES = REPO / "tracks/t3-topology/examples"
SEED = 0

FIXTURES: dict[str, tuple[str, int | None]] = {
    "mesh_4x4": ("dense_1b_16tiles-v3.json", 16),
    "mesh_shipped": ("dense_1b_16tiles-v3.json", None),
}

# Every re-freeze records WHY, so the fixture carries its own history. This is
# the audit trail the rule above depends on: a regeneration with no new entry
# here is exactly the undocumented act that rule forbids.
#
# Deliberately no HEAD / "current revision" field: that is stale the moment
# anyone commits, and this repo does not hand-maintain a moving ref inside a
# file (see the snapshot policy in docs/OPEN-PROBLEMS.md). A CAUSE commit is
# immutable and meaningful; HEAD is neither.
PROVENANCE: list[dict[str, object]] = [
    {
        "event": "freeze",
        "date": "2026-09-27",
        "commit": "e6a1cff72e28f8669fceee522a9c4f15dd6bbbf",
        "baseline": "325df2d5b8bc1c007ce1822be4a5ffd4f11f1002",
        "reason": (
            "PHASE B.2 seal: bind execution and qualification to real "
            "authorities. Initial freeze of the rendered config, trace and "
            ".anynet topology bytes, plus prepared_id, for both sealed "
            "profiles."
        ),
    },
    {
        "event": "re-freeze",
        "date": "2026-10-05",
        "commit": "a6e78010022f1e26b807621945ebc977c056dd80",
        "moved": {
            "anynet/2x2_explicit.topology_bytes_sha256": (
                "4aedbac2497036f15102c3de5e49a04f012b0d35962c6379cb3012719a043fd0"
                " -> "
                "4f8c4327bebc4f3fcc59ed6aaf686a7095ee10f4ffdf2dc391bbd7ea125d3d99"
            ),
            "anynet/2x2_explicit.prepared_id": (
                "sha256:838d23664e43b2ae278096ce38559978d9e63c22f25d0cfaecf44dad272d1afd"
                " -> "
                "sha256:5b1fc1fe5ef0b73c9956f651caec95e9de827a149e39772911db10c4292226b6"
            ),
        },
        "reason": (
            "a6e78010 added the AnyNet route-cost token, so each link line in "
            "the rendered .anynet file went from '<dst> <latency>' to "
            "'<dst> <latency> <cost>'. The cost token pins hop-count routing "
            "so a link's own wire latency does not become its route weight. "
            "prepared_id moved only because it binds the topology bytes. "
            "Verified NOT to be silent science drift: re-rendering this same "
            "fixture in the pre-a6e78010 two-field format reproduces the "
            "original digest 4aedbac2... exactly, and the channels' latencies "
            "(all 1), the endpoint count (4) and the router count (4) are "
            "unchanged. That commit updated the projection tests but not "
            "this fixture, leaving the seal broken from 2026-09-30."
        ),
    },
]

def _digest(text: str | None) -> str | None:
    if text is None:
        return None
    return hashlib.sha256(text.encode()).hexdigest()

def _load(name: str):
    from veritx_dse.model.compile_model import CompileRequestV3
    filename, agents = FIXTURES[name]
    doc = json.loads((EXAMPLES / filename).read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    if agents is not None:
        doc["agents"] = [{"kind": "compute_tile", "count": agents,
                          "data_width": 256, "addr_width": 64,
                          "protocol": "AXI"}]
    doc["noc_config"] = dict(doc["noc_config"])
    doc["noc_config"]["topology_family"] = "mesh"
    doc["noc_config"]["radix"] = None
    doc["noc_config"]["concentration"] = None
    return CompileRequestV3.from_dict(doc)

def _custom_request():
    """An explicit 2x2 mesh graph: reaches CERTIFIED_BOOKSIM_ANYNET_V1."""
    from veritx_dse.model import topology_ir as tir
    from veritx_dse.model.compile_model import CompileRequestV3
    doc = json.loads(
        (EXAMPLES / "dense_1b_16tiles-v3.json").read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    k = 2
    links = []
    for y in range(k):
        for x in range(k):
            n = y * k + x
            if x + 1 < k:
                links.append([n, n + 1])
            if y + 1 < k:
                links.append([n, n + k])
    doc["explicit_topology"] = tir.from_dict({
        "name": "sealed-probe", "kind": "custom", "nodes": k * k,
        "links": links,
        "link_attrs": {"bandwidth_GBs": 50.0, "latency_ns": 500.0},
    }).to_dict()
    doc["agents"] = [{"kind": "compute_tile", "count": k * k,
                      "data_width": 256, "addr_width": 64,
                      "protocol": "AXI"}]
    doc["noc_config"] = dict(doc["noc_config"])
    doc["noc_config"]["topology_family"] = None
    doc["noc_config"]["radix"] = None
    doc["noc_config"]["concentration"] = None
    return CompileRequestV3.from_dict(doc)

def _record(request) -> dict:
    from veritx_dse.application.capability_truth import _parents_from_bundle
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.backend.booksim_projection import (
        prepare_booksim_input, select_booksim_profile,
    )
    compilation = FabricCompiler().compile(request)
    if compilation.bundle is None:                          # pragma: no cover
        return {"status": compilation.status,
                "error": str(compilation.error)[:200]}
    bundle = compilation.bundle
    parents = _parents_from_bundle(bundle, request)
    profile = select_booksim_profile(parents)
    prepared = prepare_booksim_input(parents, seed=SEED)
    pid = prepared.prepared_id
    pid = pid() if callable(pid) else pid
    return {
        "status": compilation.status,
        "profile_id": profile.profile_id,
        "profile_semantics_version": profile.semantics_version,
        "design_hash": request.design_hash(),
        "topology_hash": bundle.topology.topology_hash(),
        "config_sha256": _digest(prepared.config_text),
        "trace_sha256": _digest(prepared.trace_text),
        "topology_bytes_sha256": _digest(prepared.topology_text),
        "prepared_id": pid,
        "num_vcs": prepared.num_vcs,
        "endpoint_count": prepared.endpoint_count,
        "router_count": prepared.router_count,
        "expected_packets": prepared.expected_packets,
    }

def build() -> dict:
    out: dict[str, dict] = {"seed": SEED, "fixtures": {}}
    for name in sorted(FIXTURES):
        out["fixtures"][f"mesh/{name}"] = _record(_load(name))
    out["fixtures"]["anynet/2x2_explicit"] = _record(_custom_request())
    return out

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dest", nargs="?")
    args = ap.parse_args()
    doc = build()
    doc["provenance"] = PROVENANCE
    blob = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    if args.dest:
        Path(args.dest).write_text(blob)
        print(f"wrote {args.dest} ({len(blob)} bytes)")
    else:
        sys.stdout.write(blob)

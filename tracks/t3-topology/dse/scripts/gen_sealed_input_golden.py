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
non-regression. A mismatch is a change to the sealed science. The golden is
never regenerated to fix a mismatch.

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

#: name -> (example file, agents override or None)
FIXTURES: dict[str, tuple[str, int | None]] = {
    # A plain 4x4 mesh: seats exactly one endpoint per router, so it reaches
    # CERTIFIED_BOOKSIM_MESH_DOR_XY_V1.
    "mesh_4x4": ("dense_1b_16tiles-v3.json", 16),
    # The shipped 16-tile design (5x5 routers for 20 endpoints).
    "mesh_shipped": ("dense_1b_16tiles-v3.json", None),
}


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
    blob = json.dumps(build(), indent=2, sort_keys=True) + "\n"
    if args.dest:
        Path(args.dest).write_text(blob)
        print(f"wrote {args.dest} ({len(blob)} bytes)")
    else:
        sys.stdout.write(blob)

#!/usr/bin/env python3
"""Generate the FROZEN v3 identity golden (schema 3 / semantics 3).

WHY THIS EXISTS
===============

Schema 3 is a RELEASED semantic authority. Nothing may expand it in place, so
we need a durable record of what v3 MEANT at the moment it was frozen — not a
prose claim, but the actual bytes.

For every pinned v3 example and every representative v3 request shape this
emits:

  * `design_hash`      — the v3 identity
  * `canonical_sha256` — sha256 of canonical_dict() JSON (identity envelope)
  * `to_dict_sha256`   — sha256 of to_dict() JSON (persisted document)
  * `compiled`         — the v3 compiler's own verdict, so "v3 still compiles
                         mesh/custom the same way" is checkable, not asserted

Run it against the frozen commit to (re)generate, and against HEAD to prove
non-regression. A mismatch is a v3 semantic change and must FAIL.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

DSE = Path(__file__).resolve().parent.parent
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

from veritx_dse.model.compile_model import (  # noqa: E402
    CompileRequestV3,
)

EXAMPLES = REPO / "tracks/t3-topology/examples"


def _h(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _record(doc: dict) -> dict:
    """Load a v3 document and record its identity + compiler verdict."""
    req = CompileRequestV3.from_dict(doc)
    rec = {
        "design_hash": req.design_hash(),
        "canonical_sha256": _h(req.canonical_dict()),
        "to_dict_sha256": _h(req.to_dict()),
    }
    try:
        from veritx_dse.application.fabric_compiler import FabricCompiler
        c = FabricCompiler().compile(req)
        topo = getattr(getattr(c, "bundle", None), "topology", None)
        rec["compiled"] = {
            "status": c.status,
            "family": getattr(topo, "family", None) and topo.family.value,
            "router_count": getattr(topo, "router_count", None),
            "endpoint_count": getattr(topo, "endpoint_count", None),
            "topology_hash": (topo.topology_hash() if callable(
                getattr(topo, "topology_hash", None))
                else getattr(topo, "topology_hash", None)),
        }
    except Exception as e:                                    # noqa: BLE001
        rec["compiled"] = {"status": "ERROR", "error": f"{type(e).__name__}: {e}"}
    return rec


def _representative_docs() -> dict[str, dict]:
    """Construct v3 requests directly from the FROZEN v3 field set.

    These are hand-built so they exercise the v3 vocabulary itself (named
    family + radix + concentration, and explicit graph) rather than whatever
    the examples happen to contain.
    """
    base = json.loads((EXAMPLES / "dense_1b_16tiles-v3.json").read_text())
    for k in ("design_hash", "guardrail_hash", "topology_intent"):
        base.pop(k, None)
    base["agents"] = [{"kind": "compute_tile", "count": 16, "data_width": 256,
                       "addr_width": 64, "protocol": "AXI"}]
    docs: dict[str, dict] = {}

    for label, family, radix, conc in (
            ("named_mesh_radix4", "mesh", 4, None),
            ("named_mesh_auto", "mesh", None, None),
            ("named_cmesh_radix4_conc4", "concentrated_mesh", 4, 4),
            ("named_cmesh_radix2_conc4", "concentrated_mesh", 2, 4),
            ("named_torus_radix4", "torus", 4, None),
            ("named_family_absent", None, None, None),
    ):
        d = json.loads(json.dumps(base))
        d["noc_config"] = dict(d["noc_config"])
        d["noc_config"]["topology_family"] = family
        d["noc_config"]["radix"] = radix
        d["noc_config"]["concentration"] = conc
        docs[label] = d

    graph = {"name": "g16", "kind": "custom", "nodes": 16,
             "links": [[i, i + 1] for i in range(15)],
             "link_attrs": {"bandwidth_GBs": 50.0, "latency_ns": 500.0}}
    d = json.loads(json.dumps(base))
    d["noc_config"] = dict(d["noc_config"])
    d["noc_config"]["topology_family"] = None
    d["explicit_topology"] = graph
    docs["explicit_custom_graph"] = d
    return docs


def build() -> dict:
    out: dict[str, dict] = {"schema_version": 3, "entries": {}}
    for path in sorted(EXAMPLES.glob("*-v3.json")):
        doc = json.loads(path.read_text())
        doc.pop("design_hash", None)
        doc.pop("guardrail_hash", None)
        out["entries"][f"examples/{path.name}"] = _record(doc)
    for label, doc in _representative_docs().items():
        out["entries"][f"representative/{label}"] = _record(doc)
    return out


if __name__ == "__main__":
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    blob = json.dumps(build(), indent=2, sort_keys=True) + "\n"
    if dest is None:
        sys.stdout.write(blob)
    else:
        dest.write_text(blob)
        print(f"wrote {dest} ({len(blob)} bytes)")

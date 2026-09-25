"""Production workload corpus (C5).

A content-addressed manifest per workload, across the four trust levels:

  W0 micro-oracle       hand-verifiable (the V01-V14 experiments)
  W1 model-realistic    representative model geometries
  W2 serving-realistic  prefill/decode/mixed P2P and collective shapes
  W3 stress             all-to-all, large collectives, hotspot, fanout

Each manifest is derived from the canonical pipeline (compile -> workload
-> projection) and carries the content identities plus the conservation
proof, so two runs of the same entry produce the same manifest id.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from validation.harness import fabric as _fabric
from validation.harness.spec import ExperimentSpec

CORPUS_SCHEMA_VERSION = 1

#: representative entries. Payloads satisfy the per-kind divisibility laws;
#: link widths are supported values. These are parameterizations, not new
#: pipeline features.
ENTRIES: tuple[dict[str, Any], ...] = (
    # ── W1 model-realistic (TP allreduce, model-representative payload) ──
    {"id": "W1-llama3-8b-tp8", "level": "W1", "model": "Llama-3.1-8B",
     "fabric": {"compute_tiles": 8, "tp": 8, "link_width": 64},
     "workload": {"kind": "collective", "collective_kind": "ALLREDUCE",
                  "payload_bytes": 8192}},
    {"id": "W1-qwen3-32b-tp8", "level": "W1", "model": "Qwen3-32B",
     "fabric": {"compute_tiles": 8, "tp": 8, "link_width": 128},
     "workload": {"kind": "collective", "collective_kind": "ALLREDUCE",
                  "payload_bytes": 8192}},
    {"id": "W1-mixtral-8x7b-tp8", "level": "W1", "model": "Mixtral-8x7B",
     "fabric": {"compute_tiles": 8, "tp": 8, "link_width": 64},
     "workload": {"kind": "collective", "collective_kind": "ALLREDUCE",
                  "payload_bytes": 8192}},
    {"id": "W1-llama3-70b-tp8", "level": "W1", "model": "Llama-3.1-70B",
     "fabric": {"compute_tiles": 8, "tp": 8, "link_width": 128},
     "workload": {"kind": "collective", "collective_kind": "ALLREDUCE",
                  "payload_bytes": 8192}},
    # ── W2 serving-realistic ────────────────────────────────────────────
    {"id": "W2-prefill-heavy", "level": "W2", "model": "serving",
     "fabric": {"compute_tiles": 8, "tp": 8, "link_width": 128},
     "workload": {"kind": "p2p", "src_rank": 0, "dst_rank": 4,
                  "payload_bytes": 16384}},
    {"id": "W2-decode-heavy", "level": "W2", "model": "serving",
     "fabric": {"compute_tiles": 8, "tp": 8, "link_width": 64},
     "workload": {"kind": "p2p", "src_rank": 1, "dst_rank": 5,
                  "payload_bytes": 512}},
    {"id": "W2-short-interactive", "level": "W2", "model": "serving",
     "fabric": {"compute_tiles": 4, "tp": 4, "link_width": 64},
     "workload": {"kind": "p2p", "src_rank": 0, "dst_rank": 3,
                  "payload_bytes": 1024}},
    {"id": "W2-moe-dispatch", "level": "W2", "model": "MoE",
     "fabric": {"compute_tiles": 16, "tp": 16, "link_width": 128},
     "workload": {"kind": "collective", "collective_kind": "ALLTOALL",
                  "payload_bytes": 16384}},
    # ── W3 stress ───────────────────────────────────────────────────────
    {"id": "W3-alltoall-4x4", "level": "W3", "model": "stress",
     "fabric": {"compute_tiles": 16, "tp": 16, "link_width": 64},
     "workload": {"kind": "collective", "collective_kind": "ALLTOALL",
                  "payload_bytes": 16384}},
    {"id": "W3-allgather-large", "level": "W3", "model": "stress",
     "fabric": {"compute_tiles": 16, "tp": 16, "link_width": 64},
     "workload": {"kind": "collective", "collective_kind": "ALLGATHER",
                  "payload_bytes": 16384}},
    {"id": "W3-broadcast-fanout", "level": "W3", "model": "stress",
     "fabric": {"compute_tiles": 16, "tp": 16, "link_width": 64},
     "workload": {"kind": "collective", "collective_kind": "BROADCAST",
                  "payload_bytes": 8192, "source_rank": 7}},
    {"id": "W3-hotspot-p2p", "level": "W3", "model": "stress",
     "fabric": {"compute_tiles": 16, "tp": 16, "link_width": 64},
     "workload": {"kind": "p2p", "src_rank": 0, "dst_rank": 15,
                  "payload_bytes": 8192}},
)


def _spec_doc(entry: dict[str, Any], index: int) -> dict[str, Any]:
    # the harness spec id convention is V*; the descriptive corpus id is
    # carried separately in the manifest.
    return {
        "schema_version": 1,
        "id": f"V{index + 20:02d}",
        "title": f"{entry['level']} {entry['id']}",
        "fabric": {"topology_family": "mesh",
                   "concentration": 1, "num_vcs": 1,
                   **entry["fabric"]},
        "workload": entry["workload"],
        "checks": ["conservation"],
        "expected": {"notes": "content-addressed production corpus entry"},
    }


def _canonical(doc: dict[str, Any]) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()


def manifest_for(entry: dict[str, Any], index: int = 0) -> dict[str, Any]:
    """Build one corpus entry through the canonical pipeline and hash it."""
    from veritx_dse.backend.booksim_projection import (
        verify_trace_conservation,
    )
    spec = ExperimentSpec.from_dict(_spec_doc(entry, index))
    built = _fabric.build(spec)
    traffic = built.parents.physical_traffic
    conservation = verify_trace_conservation(traffic)
    body = {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "id": entry["id"],
        "level": entry["level"],
        "model": entry.get("model"),
        "fabric": entry["fabric"],
        "workload": entry["workload"],
        "profile_id": built.profile_id,
        "physical_traffic_id": traffic.physical_traffic_id(),
        "message_artifact_id": traffic.logical.message_artifact_id(),
        "prepared_id": built.prepared.prepared_id(),
        "expected_packets": built.packets,
        "expected_flits": built.flits,
        "conservation": conservation,
    }
    body["manifest_id"] = hashlib.sha256(_canonical(body)).hexdigest()
    return body


def build_corpus() -> list[dict[str, Any]]:
    return [manifest_for(entry, i) for i, entry in enumerate(ENTRIES)]


def write_corpus(directory: str | Path) -> list[Path]:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    written = []
    for manifest in build_corpus():
        path = root / f"{manifest['id']}.json"
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
        written.append(path)
    return written


__all__ = ["CORPUS_SCHEMA_VERSION", "ENTRIES", "build_corpus", "manifest_for",
           "write_corpus"]

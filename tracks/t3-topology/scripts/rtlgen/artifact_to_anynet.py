#!/usr/bin/env python3
"""Bridge a supported TopologyArtifact to the existing 2-VC RTL emitter.

Research/preview seam only. The graph connectivity is lowered, but the emitter
renumbers router ports and replaces source-family routing with its own
free/escape route tables. It is not family-faithful RTL.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


class ArtifactRtlRefusal(ValueError):
    """The artifact carries semantics not implemented by this emitter."""


def artifact_to_anynet(doc: dict[str, Any]) -> str:
    from veritx_dse.model.topology_artifact import TopologyArtifact

    artifact = TopologyArtifact.from_dict(doc)
    if artifact.shared_links:
        raise ArtifactRtlRefusal(
            "shared/multidrop links require a shared-link RTL backend")
    if artifact.island_columns:
        raise ArtifactRtlRefusal("QoS islands are not implemented by this emitter")
    if artifact.planes != ("d",):
        raise ArtifactRtlRefusal("only the single Plane-D slice is implemented")
    if artifact.physical_links:
        raise ArtifactRtlRefusal(
            "physical-link grouping is not represented by the point-to-point emitter")
    if any(r.seat_capacity != 1 or r.ejection_capacity != 1
           for r in artifact.routers):
        raise ArtifactRtlRefusal(
            "this emitter attaches exactly one terminal per router")
    if not artifact.channels:
        raise ArtifactRtlRefusal("topology has no point-to-point channels")

    directed: dict[tuple[int, int], tuple[int, int, int]] = {}
    for ch in artifact.channels:
        if ch.width_bits != 64:
            raise ArtifactRtlRefusal(
                f"channel {ch.channel_id} width is {ch.width_bits}; emitter uses 64-bit flits")
        if ch.latency_cycles != 1:
            raise ArtifactRtlRefusal(
                f"channel {ch.channel_id} latency is {ch.latency_cycles}; emitter models one-cycle links")
        if ch.route_weight != 1:
            raise ArtifactRtlRefusal(
                f"channel {ch.channel_id} route weight is {ch.route_weight}; weighted routing is unsupported")
        if ch.physical_link_id is not None:
            raise ArtifactRtlRefusal(
                f"channel {ch.channel_id} belongs to a physical link grouping")
        key = (ch.src_router, ch.dst_router)
        if key in directed:
            raise ArtifactRtlRefusal("parallel point-to-point channels are unsupported")
        directed[key] = (ch.src_port, ch.dst_port, ch.width_bits)

    adj: list[set[int]] = [set() for _ in artifact.routers]
    for (src, dst), (src_port, dst_port, width) in directed.items():
        reverse = directed.get((dst, src))
        if reverse is None:
            raise ArtifactRtlRefusal(
                f"channel {src}->{dst} has no reverse channel; emitter requires symmetric graphs")
        if reverse[2] != width:
            raise ArtifactRtlRefusal(f"reverse channels {src}<->{dst} have different widths")
        if (reverse[0], reverse[1]) != (dst_port, src_port):
            raise ArtifactRtlRefusal(
                f"reverse channels {src}<->{dst} disagree on reciprocal port identities")
        adj[src].add(dst)

    lines = []
    for router_id, neighbors in enumerate(adj):
        fields = ["router", str(router_id), "node", str(router_id)]
        for neighbor in sorted(neighbors):
            fields.extend(("router", str(neighbor), "1", "1"))
        lines.append(" ".join(fields))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("artifact", type=Path, help="serialized TopologyArtifact JSON")
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--buf", type=int, default=8)
    ap.add_argument("--block-k", type=int, default=8)
    args = ap.parse_args(argv)

    repo = Path(__file__).resolve().parents[4]
    dse = repo / "tracks" / "t3-topology" / "dse"
    if str(dse) not in sys.path:
        sys.path.insert(0, str(dse))
    try:
        doc = json.loads(args.artifact.read_text())
        anynet = artifact_to_anynet(doc)
    except (OSError, json.JSONDecodeError, ArtifactRtlRefusal, ValueError) as exc:
        print(f"REFUSED (artifact-to-RTL): {exc}", file=sys.stderr)
        return 2

    if args.outdir.exists() and any(args.outdir.iterdir()):
        print(f"REFUSED (artifact-to-RTL): output directory is not empty: {args.outdir}",
              file=sys.stderr)
        return 2
    args.outdir.mkdir(parents=True, exist_ok=True)
    anynet_path = args.outdir / "topology.anynet"
    anynet_path.write_text(anynet)
    emitter = Path(__file__).with_name("gen_rtl.py")
    command = [sys.executable, str(emitter), "--anynet", str(anynet_path),
               "--outdir", str(args.outdir / "rtl"), "--num-vc", "2",
               "--selected-vcs", "2", "--selected-family",
               str(doc.get("family", "unknown")), "--buf", str(args.buf),
               "--block-k", str(args.block_k)]
    result = subprocess.run(command, check=False)
    if result.returncode:
        return result.returncode
    print("Research RTL generated from graph connectivity; router port numbering and routing are normalized to the emitter's 2-VC free/escape scheme.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

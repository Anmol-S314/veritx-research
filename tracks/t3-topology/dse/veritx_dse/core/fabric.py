"""veritx_dse.core.fabric — one fabric authority (audit P0 #1).

A FabricArtifact is the content-addressed identity of the network a
simulator actually executes: topology backend + size, routing, VC/buffer/
packetization, and the hash of the rendered config that produced them.
Standalone BookSim builds it from the rendered config it just ran; the
serving slice parses the generated config.cfg the child executed. Both
sides share this parser — never two readers of the same grammar.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from .spec import canonical_json

_CFG_KV_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^;]+);", re.M)


def _int_or_none(d: dict[str, str], key: str) -> int | None:
    try:
        return int(d[key]) if d.get(key) not in (None, "") else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class FabricArtifact:
    source: str                      # "preset:<name>" | "booksim_config"
    topology: str | None             # BookSim backend name
    node_count: int | None
    size: dict[str, Any]             # k/n, or anynet ref + node count
    routing: str | None
    num_vcs: int | None
    vc_buf_size: int | None
    packet_size: int | None
    config_sha256: str | None        # rendered config text (execution side)
    anynet_sha256: str | None = None
    artifact_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source, "topology": self.topology,
            "node_count": self.node_count, "size": dict(self.size),
            "routing": self.routing, "num_vcs": self.num_vcs,
            "vc_buf_size": self.vc_buf_size, "packet_size": self.packet_size,
            "config_sha256": self.config_sha256,
            "anynet_sha256": self.anynet_sha256,
            "artifact_hash": self.artifact_hash,
        }


def fabric_hash(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "artifact_hash"}
    return hashlib.sha256(canonical_json(body).encode()).hexdigest()


def fabric_from_preset(topo: Any, node_count: int) -> FabricArtifact:
    base = {
        "source": f"preset:{topo.name}", "topology": topo.backend,
        "node_count": node_count, "size": dict(topo.params),
        "routing": topo.routing, "num_vcs": None, "vc_buf_size": None,
        "packet_size": None, "config_sha256": None, "anynet_sha256": None,
    }
    return FabricArtifact(**base, artifact_hash=fabric_hash(base))


def fabric_from_config_text(text: str, *, source: str = "booksim_config",
                            anynet_text: str | None = None) -> FabricArtifact:
    kv = {k: v.strip() for k, v in _CFG_KV_RE.findall(text)}
    if "topology" not in kv:
        raise ValueError("no 'topology =' line — not a BookSim config")
    size: dict[str, Any] = {k: kv[k] for k in ("k", "n") if k in kv}
    anynet_sha = None
    node_count: int | None = None
    if kv["topology"] == "anynet":
        if "network_file" in kv:
            size["network_file"] = kv["network_file"]
        if anynet_text is not None:
            ids = [int(p[1]) for ln in anynet_text.splitlines()
                   for p in [ln.split()] if len(p) >= 2 and p[0] == "router"
                   and p[1].lstrip("-").isdigit()]
            if ids:
                node_count = max(ids) + 1
            anynet_sha = "sha256:" + hashlib.sha256(
                anynet_text.encode()).hexdigest()
    else:
        try:
            k = int(kv.get("k", "")); n = int(kv.get("n", ""))
            node_count = k ** n
        except (TypeError, ValueError):
            node_count = None
    base = {
        "source": source, "topology": kv["topology"], "node_count": node_count,
        "size": size, "routing": kv.get("routing_function"),
        "num_vcs": _int_or_none(kv, "num_vcs"),
        "vc_buf_size": _int_or_none(kv, "vc_buf_size"),
        "packet_size": _int_or_none(kv, "packet_size"),
        "config_sha256": "sha256:" + hashlib.sha256(
            text.encode()).hexdigest(),
        "anynet_sha256": anynet_sha,
    }
    return FabricArtifact(**base, artifact_hash=fabric_hash(base))


_MATCH_FIELDS = ("topology", "node_count", "routing", "num_vcs",
                 "vc_buf_size", "packet_size")


def fabrics_match(intent: FabricArtifact,
                  executed: FabricArtifact) -> tuple[bool, str | None]:
    """Whether the executed fabric is the declared one.

    Unknown (None) on either side is a failed proof, not equality —
    absence never matches.
    """
    for f in _MATCH_FIELDS:
        a, b = getattr(intent, f), getattr(executed, f)
        if a is None or b is None:
            return False, f"{f} unrecorded on one side ({a!r} vs {b!r})"
        if a != b:
            return False, f"{f} differs ({a!r} vs {b!r})"
    return True, None


def check_serving_fabric(expected: dict[str, Any] | None,
                         executed: dict[str, Any] | None,
                         network_yml: dict[str, Any] | None
                         ) -> tuple[bool, str | None]:
    """Prove the serving child executed the resolved cluster fabric.

    Chain: expected == network.yml (child consumed the resolved model)
    and executed.node_count == expected.npu_count (config covers it).
    Anything else is FABRIC_INTENT_MISMATCH material.
    """
    if expected is None:
        return False, "no expected fabric in resolved spec"
    if executed is None or executed.get("unrecorded"):
        return False, "no executed fabric evidence"
    if network_yml is None:
        return False, "network.yml missing from run inputs"
    if network_yml.get("npus_count") != expected["dimensions"]:
        return False, (
            f"network.yml dims {network_yml.get('npus_count')} != "
            f"expected {expected['dimensions']}")
    if network_yml.get("topology") != expected["topology"]:
        return False, (
            f"network.yml topology {network_yml.get('topology')} != "
            f"expected {expected['topology']}")
    if executed.get("node_count") != expected["npu_count"]:
        return False, (
            f"executed nodes {executed.get('node_count')} != "
            f"expected {expected['npu_count']}")
    return True, None

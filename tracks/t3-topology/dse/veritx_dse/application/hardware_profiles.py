"""Canonical hardware-profile catalog.

A profile is DERIVED from tracked, measured sources — never authored in a
browser. Two authorities are combined:

  * the serving **cluster configs** (``npu_mem`` capacity/bandwidth,
    link bandwidth/latency) — tracked JSON;
  * the profiler **meta.yaml** (vendor/model, tool versions, profile
    date, model, precision, TP coverage) — tracked measurement.

Every field carries a disposition:

  DESCRIPTIVE  recorded, no authority consumes it today
  CONSUMED     an authority reads it (named in ``consumers``)

This is a *serving* hardware profile: the fabric compiler does not consume
memory capacity/bandwidth or compute rates, so those stay DESCRIPTIVE for
design and CONSUMED-by-serving. Compute EXECUTION at design time remains
NOT MODELED — the profiler tables are a serving timing source, not a
design-time compute authority.

The profile NEVER enters a design hash: binding is separate from design
identity.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from veritx_dse.core.artifact import content_hash

HW_PROFILE_SCHEMA_VERSION = 1

DESCRIPTIVE = "DESCRIPTIVE"
CONSUMED = "CONSUMED"

_GB = 1_000_000_000  # decimal GB, matching the config's stated units
_GBPS = 1_000_000_000


@dataclass(frozen=True)
class TimingSource:
    """The measured serving timing source bound to a hardware profile."""
    profiler_dir: str
    model: str
    variant: str
    tp_degrees: tuple[int, ...]
    gpu: str
    vllm_version: str | None
    cuda_version: str | None
    profiled_at: str | None
    consumed_by: str = "CANONICAL_SERVING"
    status: str = "MEASURED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "profiler_dir": self.profiler_dir,
            "model": self.model,
            "variant": self.variant,
            "tp_degrees": list(self.tp_degrees),
            "gpu": self.gpu,
            "vllm_version": self.vllm_version,
            "cuda_version": self.cuda_version,
            "profiled_at": self.profiled_at,
            "consumed_by": self.consumed_by,
            "status": self.status,
        }


@dataclass(frozen=True)
class HardwareProfile:
    hardware_id: str
    device_kind: str
    vendor_model: str
    memory_capacity_bytes: int | None
    memory_bandwidth_bytes_per_s: int | None
    host_memory_bytes: int | None
    host_bandwidth_bytes_per_s: int | None
    link_bandwidth_bytes_per_s: int | None
    link_latency_ns: int | None
    provenance: tuple[str, ...]
    timing_source: TimingSource | None
    dispositions: tuple[tuple[str, str], ...]
    consumers: tuple[str, ...]
    schema_version: int = HW_PROFILE_SCHEMA_VERSION

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/HardwareProfile",
            "schema_version": self.schema_version,
            "hardware_id": self.hardware_id,
            "device_kind": self.device_kind,
            "vendor_model": self.vendor_model,
            "memory_capacity_bytes": self.memory_capacity_bytes,
            "memory_bandwidth_bytes_per_s": self.memory_bandwidth_bytes_per_s,
            "host_memory_bytes": self.host_memory_bytes,
            "host_bandwidth_bytes_per_s": self.host_bandwidth_bytes_per_s,
            "link_bandwidth_bytes_per_s": self.link_bandwidth_bytes_per_s,
            "link_latency_ns": self.link_latency_ns,
            "provenance": list(self.provenance),
            "timing_source": (self.timing_source.to_dict()
                              if self.timing_source else None),
            "dispositions": [list(p) for p in self.dispositions],
            "consumers": list(self.consumers),
        }

    def profile_id(self) -> str:
        return content_hash("srota/HardwareProfile", self.schema_version,
                            self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.identity_dict())
        payload["profile_id"] = self.profile_id()
        payload["display_name"] = self.vendor_model
        return payload


def _repo_root() -> Path:
    from veritx_dse.core.paths import REPO
    return Path(REPO)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - malformed/absent meta is "unknown"
        return {}
    return doc if isinstance(doc, dict) else {}


def _timing_source(root: Path, hardware: str) -> TimingSource | None:
    base = root / "third_party" / "llmservingsim" / "profiler" / "perf" / hardware
    if not base.is_dir():
        return None
    for meta_path in sorted(base.rglob("meta.yaml")):
        meta = _read_yaml(meta_path)
        if not meta:
            continue
        tp = meta.get("tp_degrees") or []
        return TimingSource(
            profiler_dir=str(meta_path.parent.relative_to(root)),
            model=str(meta.get("model") or ""),
            variant=str(meta.get("variant") or ""),
            tp_degrees=tuple(int(t) for t in tp if isinstance(t, int)),
            gpu=str(meta.get("gpu") or ""),
            vllm_version=(str(meta["vllm_version"])
                          if meta.get("vllm_version") else None),
            cuda_version=(str(meta["cuda_version"])
                          if meta.get("cuda_version") else None),
            profiled_at=(str(meta["profiled_at"])
                         if meta.get("profiled_at") else None),
        )
    return None


def _num(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _scaled(value: Any, unit: int) -> int | None:
    n = _num(value)
    return None if n is None else n * unit


def _profiles() -> tuple[HardwareProfile, ...]:
    root = _repo_root()
    cluster_dir = (root / "third_party" / "llmservingsim" / "configs"
                   / "cluster")
    seen: dict[str, dict[str, Any]] = {}
    if cluster_dir.is_dir():
        for cfg in sorted(cluster_dir.glob("*.json")):
            try:
                doc = json.loads(cfg.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for node in doc.get("nodes", ()):
                for inst in node.get("instances", ()):
                    hardware = str(inst.get("hardware") or "")
                    if not hardware or hardware in seen:
                        continue
                    seen[hardware] = {
                        "npu_mem": inst.get("npu_mem") or {},
                        "cpu_mem": node.get("cpu_mem") or {},
                        "link_bw": doc.get("link_bw"),
                        "link_latency": doc.get("link_latency"),
                        "source": str(cfg.relative_to(root)),
                    }
    out: list[HardwareProfile] = []
    for hardware, facts in sorted(seen.items()):
        timing = _timing_source(root, hardware)
        npu = facts["npu_mem"]
        cpu = facts["cpu_mem"]
        mem_cap = _scaled(npu.get("mem_size"), _GB)
        mem_bw = _scaled(npu.get("mem_bw"), _GBPS)
        # Declared device kind: a serving hardware id of this family is a GPU.
        device_kind = ("GPU" if hardware.upper().startswith(("RTX", "H100",
                                                             "A100", "B200",
                                                             "MI", "L40"))
                       else "GENERIC")
        consumers = (["CANONICAL_SERVING"] if timing else [])
        dispositions = (
            ("memory_capacity_bytes", CONSUMED if timing else DESCRIPTIVE),
            ("memory_bandwidth_bytes_per_s", CONSUMED if timing else DESCRIPTIVE),
            ("host_memory_bytes", DESCRIPTIVE),
            ("host_bandwidth_bytes_per_s", DESCRIPTIVE),
            ("link_bandwidth_bytes_per_s", DESCRIPTIVE),
            ("link_latency_ns", DESCRIPTIVE),
        )
        provenance = [facts["source"]]
        if timing:
            provenance.append(timing.profiler_dir + "/meta.yaml")
        out.append(HardwareProfile(
            hardware_id=hardware,
            device_kind=device_kind,
            vendor_model=(timing.gpu if timing and timing.gpu else hardware),
            memory_capacity_bytes=mem_cap,
            memory_bandwidth_bytes_per_s=mem_bw,
            host_memory_bytes=_scaled(cpu.get("mem_size"), _GB),
            host_bandwidth_bytes_per_s=_scaled(cpu.get("mem_bw"), _GBPS),
            link_bandwidth_bytes_per_s=_scaled(facts.get("link_bw"), _GBPS),
            link_latency_ns=_num(facts.get("link_latency")),
            provenance=tuple(provenance),
            timing_source=timing,
            dispositions=dispositions,
            consumers=tuple(consumers),
        ))
    return tuple(out)


def hardware_profile_catalog() -> dict[str, Any]:
    profiles = _profiles()
    return {
        "contract_version": 1,
        "note": ("Profiles are derived from tracked measured sources. "
                 "DESCRIPTIVE fields have no consumer; CONSUMED fields name "
                 "their authority. Compute execution at design time is "
                 "NOT MODELED."),
        "profiles": [p.to_dict() for p in profiles],
    }


def profile_for(hardware_id: str) -> HardwareProfile | None:
    wanted = (hardware_id or "").upper()
    for profile in _profiles():
        if profile.hardware_id.upper() == wanted:
            return profile
    return None


__all__ = [
    "CONSUMED", "DESCRIPTIVE", "HW_PROFILE_SCHEMA_VERSION",
    "HardwareProfile", "TimingSource", "hardware_profile_catalog",
    "profile_for",
]

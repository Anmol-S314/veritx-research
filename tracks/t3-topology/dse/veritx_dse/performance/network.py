"""veritx_dse.performance.network — BookSim evidence → network timing (§36–§42).

Rationale: docs/decisions/modules/performance.md
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from veritx_dse.core.time import QTime, TimeError

WINDOW_KIND_BARRIER = "BARRIER_TRAFFIC_WINDOW"

# The stats Wave E consumes from BookSim evidence (§38 audit).
NETWORK_STATS_KEYS = ("completion_time", "delivered", "pkt_count",
                      "drain_verdict")


NETWORK_BINDING_SCHEMA_VERSION_V1 = 1
NETWORK_BINDING_SCHEMA_VERSION_V2 = 2

_BINDING_KEYS_V1 = frozenset({
    "operation_graph_id", "physical_traffic_id", "backend_config_hash",
    "backend_input_hash", "evidence_sha256", "stats_sha256",
    "network_clock_hz", "window_kind", "duration",
})
_BINDING_KEYS_V2 = frozenset({
    "schema_version", "workload_graph_id", "physical_traffic_id",
    "backend_config_hash", "backend_input_hash", "evidence_sha256",
    "stats_sha256", "network_clock_hz", "window_kind", "duration",
})


@dataclass(frozen=True)
class NetworkWindowBinding:
    """Provenance-complete network timing for one traffic window.

Rationale: docs/decisions/modules/performance.md
    """

    workload_parent_id: str
    physical_traffic_id: str
    backend_config_hash: str
    backend_input_hash: str
    evidence_sha256: str
    stats_sha256: str
    network_clock_hz: int | Fraction | None  # None => cycles-only
    window_kind: str = WINDOW_KIND_BARRIER
    duration: QTime | None = None
    schema_version: int = NETWORK_BINDING_SCHEMA_VERSION_V1

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.schema_version == NETWORK_BINDING_SCHEMA_VERSION_V2:
            d["schema_version"] = NETWORK_BINDING_SCHEMA_VERSION_V2
            d["workload_graph_id"] = self.workload_parent_id
        else:
            d["operation_graph_id"] = self.workload_parent_id
        d.update({
            "physical_traffic_id": self.physical_traffic_id,
            "backend_config_hash": self.backend_config_hash,
            "backend_input_hash": self.backend_input_hash,
            "evidence_sha256": self.evidence_sha256,
            "stats_sha256": self.stats_sha256,
            "network_clock_hz": (None if self.network_clock_hz is None else {
                "num": Fraction(self.network_clock_hz).numerator,
                "den": Fraction(self.network_clock_hz).denominator}),
            "window_kind": self.window_kind,
            "duration": (None if self.duration is None
                         else self.duration.to_dict()),
        })
        return d

    @staticmethod
    def from_dict(d: Any) -> "NetworkWindowBinding":
        if not isinstance(d, dict):
            raise TimeError("network binding must be a dict")
        version = d.get("schema_version", NETWORK_BINDING_SCHEMA_VERSION_V1)
        if version == NETWORK_BINDING_SCHEMA_VERSION_V1:
            allowed = _BINDING_KEYS_V1
            parent_key = "operation_graph_id"
        elif version == NETWORK_BINDING_SCHEMA_VERSION_V2:
            allowed = _BINDING_KEYS_V2
            parent_key = "workload_graph_id"
        else:
            raise TimeError(
                f"unknown network binding schema_version {version!r}")
        if set(d) != allowed:
            raise TimeError(
                f"network binding fields must be exactly {sorted(allowed)}, "
                f"got {sorted(d)}")
        hz = d["network_clock_hz"]
        if hz is not None:
            if not isinstance(hz, dict) or \
                    set(hz) != {"num", "den"}:
                raise TimeError("network_clock_hz must be null or {num,den}")
            hz = Fraction(hz["num"], hz["den"])
        dur = d["duration"]
        if dur is not None:
            dur = QTime.from_dict(dur)
        return NetworkWindowBinding(
            workload_parent_id=d[parent_key],
            schema_version=version,
            physical_traffic_id=d["physical_traffic_id"],
            backend_config_hash=d["backend_config_hash"],
            backend_input_hash=d["backend_input_hash"],
            evidence_sha256=d["evidence_sha256"],
            stats_sha256=d["stats_sha256"],
            network_clock_hz=hz,
            window_kind=d["window_kind"],
            duration=dur)


def stats_sha256(stats: dict[str, Any]) -> str:
    """Canonical digest of the backend statistics Wave E consumes.

    Canonical JSON (not ``repr``) so the digest is stable across Python
    versions — a persisted binding must re-verify years later.
    """
    from veritx_dse.core.spec import canonical_json
    return hashlib.sha256(canonical_json(stats).encode()).hexdigest()


def network_window_duration(cycles: int, network_clock_hz: int | Fraction
                            ) -> QTime:
    """completion_time cycles → exact seconds (§37).

    Requires an explicit clock. 0 cycles is a valid degenerate window.
    """
    return QTime.from_cycles(cycles, network_clock_hz)


def bind_network_window(*, evidence: Any, chain: dict[str, Any],
                        network_clock_hz: int | Fraction | None,
                        evidence_sha256: str,
                        expected_packets: int | None = None
                        ) -> tuple[NetworkWindowBinding, QTime | int]:
    """Bind one BARRIER window from certified BookSim evidence.

Rationale: docs/decisions/modules/performance.md
    """
    if not isinstance(evidence_sha256, str) or not evidence_sha256:
        raise TimeError(
            "network timing requires the sha256 of the authenticated "
            "evidence bytes (§42): refusing to bind timing that cannot "
            "name its evidence")
    stats = getattr(evidence, "stats", None) or \
        (evidence.get("stats") if isinstance(evidence, dict) else None)
    if not isinstance(stats, dict):
        raise TimeError("no BookSim stats on evidence (§42)")
    cycles = stats.get("completion_time")
    if not isinstance(cycles, int) or isinstance(cycles, bool):
        cycles = stats.get("completion_cycles")
    if not isinstance(cycles, int) or isinstance(cycles, bool) \
            or cycles < 0:
        raise TimeError(
            f"BookSim stats carry no integer completion_time "
            f"(completion_cycles accepted as the canonical alias, got "
            f"{cycles!r}); no network timing can be bound (§38/§42)")
    if expected_packets is not None and \
            isinstance(stats.get("delivered"), int) and \
            stats["delivered"] != expected_packets:
        raise TimeError(
            f"backend delivered {stats['delivered']} packets but Wave-D "
            f"traffic expected {expected_packets}: evidence does not "
            f"belong to this traffic (§42)")
    dur: QTime | None = None
    if network_clock_hz is not None:
        dur = network_window_duration(cycles, network_clock_hz)
    chain_version = chain.get("chain_schema_version",
                              NETWORK_BINDING_SCHEMA_VERSION_V1)
    if chain_version == NETWORK_BINDING_SCHEMA_VERSION_V1:
        binding_version = NETWORK_BINDING_SCHEMA_VERSION_V1
        parent_key = "operation_graph_id"
    elif chain_version == NETWORK_BINDING_SCHEMA_VERSION_V2:
        binding_version = NETWORK_BINDING_SCHEMA_VERSION_V2
        parent_key = "workload_graph_id"
    else:
        raise TimeError(
            f"cannot bind a network window to chain schema_version "
            f"{chain_version!r}")
    if parent_key not in chain:
        raise TimeError(
            f"chain generation {chain_version} must name its workload "
            f"authority as {parent_key!r}")
    binding = NetworkWindowBinding(
        workload_parent_id=str(chain[parent_key]),
        schema_version=binding_version,
        physical_traffic_id=str(chain["physical_traffic_id"]),
        backend_config_hash=str(chain["backend_config_hash"]),
        backend_input_hash=str(chain["backend_input_hash"]),
        evidence_sha256=evidence_sha256,
        stats_sha256=stats_sha256(stats),
        network_clock_hz=network_clock_hz,
        duration=dur)
    if network_clock_hz is None:
        return binding, cycles
    return binding, dur

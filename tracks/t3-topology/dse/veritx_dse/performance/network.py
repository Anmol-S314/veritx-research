"""veritx_dse.performance.network — BookSim evidence → network timing (§36–§42).

Wave D owns WHAT traffic; Wave E owns WHEN — but only through explicit
backend timing evidence. This module is the single seam:

- The Stage-A audit (§38) established that BookSim evidence exposes a
  GLOBAL ``completion_time`` (network cycles) plus packet/latency
  statistics, and does NOT expose per-message completion cycles.
- Therefore (§39) the whole traffic window is ONE BARRIER network
  event with duration = completion_time / network_clock_hz. Inventing
  per-operation causality from aggregate stats is forbidden and this
  module refuses to do it.
- One timing authority per network effect (§40): BookSim already
  simulates contention inside the window; no analytical NoC model is
  applied on top.
- The binding carries the full evidence provenance (§42):
  physical_traffic_id, backend config/input hashes, evidence sha256,
  stats sha256, network clock, window kind.

Without a bound network clock the window keeps its CYCLES and refuses
cross-domain wall-time claims (§37: never guess a frequency).
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


# The binding names the workload AUTHORITY it was bound to, and that
# authority changed generation in 2c.4. Rather than keep a v1 field name
# (operation_graph_id) holding a v2 value, the field is named for what it
# is and the binding declares which generation it belongs to. Absence of
# ``schema_version`` means v1, exactly as in the plan chain: the boundary
# is explicit, not inferred from which keys happen to be present.
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

    ``workload_parent_id`` names the workload authority this window was
    bound to: the historical OperationGraph in generation 1, the canonical
    WorkloadGraph in generation 2. Values are never compared across
    generations — a v1 binding proves a v1 parent, a v2 binding proves a
    v2 parent.

    ``duration`` is the exact wall-time window (completion_time /
    network_clock_hz) when a clock is bound, else ``None``: cycles-only
    evidence is retained for provenance but can never be converted to
    time without a declared frequency (§37 — never guess one).
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
        # v1 output is byte-identical to what it always was: no version
        # field, and the historical parent key. Only a v2 binding emits
        # the version and the canonical parent key.
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
        # An explicit version, never inferred from key presence: absence
        # means v1, and an unknown version refuses rather than being read
        # as whichever generation happens to match its keys.
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

    Returns ``(binding, duration)`` where duration is a QTime when a
    clock is bound, else the raw cycle count (cycles-only mode, §37:
    cross-domain wall-time claims refuse downstream).

    ``chain`` is the Wave-D plan chain block (physical_traffic_id,
    workload parent id, backend hashes) — passed through, never
    re-derived here. ``evidence_sha256`` is the digest of the exact
    authenticated evidence bytes (``EvidenceRef.sha256``), supplied by
    the caller that read the evidence; a binding that cannot name its
    evidence refuses.
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
    # Canonical-key acceptance (veritx-integrate §26): the canonical
    # BookSim parser records the backend's reported completion cycles
    # as ``completion_cycles``; historical stats used
    # ``completion_time``. One measured quantity — the backend's
    # reported completion cycles — two labels. The historical label
    # keeps precedence when both are present; a bool is never a count.
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

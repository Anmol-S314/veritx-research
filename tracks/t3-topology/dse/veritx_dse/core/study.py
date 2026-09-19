"""veritx_dse.core.study — StudyManifest + exact ExecutionFingerprint.

Worker item 1 of the study-integrity program: replace resume-by-name and
certified-with-None with types that make unknown dimensions
unrepresentable.

Two types, both frozen dataclasses with content hashes re-verified on
load (the route_artifact pattern):

* ``ExecutionFingerprint`` — the exact identity of one realized
  execution. Every material dimension is REQUIRED (no None, ever): a
  missing dimension raises instead of certifying. This is the strict
  counterpart to ``comparison.fingerprint_from_run``, which must keep
  accepting legacy runs and therefore marks unknowns uncertified.
* ``StudyManifest`` — one study: an immutable intent (kind, workload,
  candidate fingerprints, controlled vs experimental dimensions, seed and
  backend policy) referencing executions by fingerprint hash. Studies
  reference evidence; they never copy simulator numbers.

Relationship to the comparison gate: ``StudyManifest.comparison_intent``
emits a ``ComparisonIntent``-compatible dict, so a study flows straight
into ``evaluate_comparability`` with zero re-typing.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .spec import canonical_json

__all__ = [
    "StudyError",
    "ExecutionFingerprint",
    "execution_fingerprint",
    "fingerprints_equal",
    "verify_study_anchor",
    "StudyManifest",
    "study_manifest",
    "new_study_id",
    "STUDY_KINDS",
    "REQUIRED_EXECUTION_DIMENSIONS",
]

STUDY_KINDS = ("DESIGN_COMPARISON", "CROSS_FIDELITY_CALIBRATION")

# Execution classes with a wired comparison projection. v1 wires "booksim"
# only: serving identity already flows through the workload/serve
# fingerprint path (comparison.fingerprint_from_run), and a half-wired
# serving projection would certify shapes it cannot fill. Anything else
# refuses — narrower-but-sound beats broad-but-guessed.
EXECUTION_CLASSES = ("booksim",)

# Every dimension that changes what an execution MEANS. Anything absent
# here is presentation, not science. Order is diagnostic only.
REQUIRED_EXECUTION_DIMENSIONS = (
    "execution_class",
    "workload_artifact_hash",
    "node_count",
    "fabric_topology",
    "fabric_routing",
    "vc_count",
    "buffer_flits",
    "packet_bytes",
    "flit_bytes",
    "simulator_binary_sha",
    "simulator_config_sha",
    "mapping",
    "seed",
    "seed_policy",
    "source_commit",
    "source_dirty",
    "container_digest",
    "python_lock_sha",
)


class StudyError(ValueError):
    """Unbuildable study identity or unfingerprintable execution."""


def _sha256_hex(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


def new_study_id() -> str:
    """Sortable unique study identity (same uuid7 scheme as run ids)."""
    from .runs import new_run_id
    return new_run_id()


def _require_str(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise StudyError(
            f"execution dimension {name!r} must be a non-empty string, "
            f"got {value!r} — unknown dimensions refuse, never default")
    return value


def _require_int(name: str, value: Any, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) \
            or value < minimum:
        raise StudyError(
            f"execution dimension {name!r} must be an int >= {minimum}, "
            f"got {value!r}")
    return value


def _require_mapping(value: Any) -> tuple[dict[str, Any], ...]:
    """Rank/instance placement identity, order-sensitive (brief item 17).

    ``rank0 = A, rank1 = B`` performs differently from the swap, so the
    ordered list — not a set — is the identity. Each entry needs an
    integer rank and a non-empty artifact/device identity.
    """
    if not isinstance(value, (list, tuple)) or not value:
        raise StudyError(
            "execution dimension 'mapping' must be a non-empty ordered "
            f"list of rank entries, got {value!r}")
    out = []
    for i, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise StudyError(
                f"mapping[{i}] must be a dict with rank + artifact/device "
                f"identity, got {entry!r}")
        rank = entry.get("rank")
        if not isinstance(rank, int) or isinstance(rank, bool) or rank < 0:
            raise StudyError(f"mapping[{i}].rank must be an int >= 0")
        ident = entry.get("artifact") or entry.get("device")
        if not isinstance(ident, str) or not ident:
            raise StudyError(
                f"mapping[{i}] needs a non-empty artifact/device identity")
        out.append({"rank": rank, "artifact": ident}
                   if entry.get("artifact") is not None
                   else {"rank": rank, "device": ident})
    ranks = [e["rank"] for e in out]
    if sorted(ranks) != list(range(len(ranks))):
        raise StudyError(
            f"mapping ranks must be exactly 0..{len(ranks) - 1}, got "
            f"{sorted(ranks)} — gaps/duplicates hide placement semantics")
    return tuple(out)


@dataclass(frozen=True)
class ExecutionFingerprint:
    """Exact identity of one realized execution. No None, ever."""
    execution_class: str
    workload_artifact_hash: str
    node_count: int
    fabric_topology: str
    fabric_routing: str
    vc_count: int
    buffer_flits: int
    packet_bytes: int
    flit_bytes: int
    simulator_binary_sha: str
    simulator_config_sha: str
    mapping: tuple[dict[str, Any], ...]
    seed: int
    seed_policy: str
    source_commit: str
    source_dirty: bool
    container_digest: str
    python_lock_sha: str
    fingerprint_hash: str = ""

    def _identity_dict(self) -> dict[str, Any]:
        return {
            "execution_class": self.execution_class,
            "workload_artifact_hash": self.workload_artifact_hash,
            "node_count": self.node_count,
            "fabric_topology": self.fabric_topology,
            "fabric_routing": self.fabric_routing,
            "vc_count": self.vc_count,
            "buffer_flits": self.buffer_flits,
            "packet_bytes": self.packet_bytes,
            "flit_bytes": self.flit_bytes,
            "simulator_binary_sha": self.simulator_binary_sha,
            "simulator_config_sha": self.simulator_config_sha,
            "mapping": [dict(e) for e in self.mapping],
            "seed": self.seed,
            "seed_policy": self.seed_policy,
            "source_commit": self.source_commit,
            "source_dirty": self.source_dirty,
            "container_digest": self.container_digest,
            "python_lock_sha": self.python_lock_sha,
        }

    def to_comparison_dict(self) -> dict[str, Any]:
        """Project onto the comparison gate's fingerprint shape.

        A PROJECTION, documented field by field — not a second identity.
        Dimensions the booksim class determines by construction are filled
        (simulator/network_mode/fidelity); serving-shaped dimensions with
        no booksim meaning emit None, which the gate skips exactly as it
        skips absent legacy fields. Anything the class cannot determine
        would be a guess, so new classes refuse in execution_fingerprint
        instead of projecting wishes.
        """
        return {
            "workload_hash": self.workload_artifact_hash,
            "model_identity": None,
            "node_count": self.node_count,
            "participant_count": self.node_count,
            "packetization": f"{self.packet_bytes}B",
            "topology": self.fabric_topology,
            "routing": self.fabric_routing,
            "vc_count": self.vc_count,
            "simulator": "booksim",
            "network_engine": None,
            "network_mode": "REAL_SIMULATION",
            "fidelity": "NETWORK_SIMULATION",
            "seed_policy": self.seed_policy,
            "tp": None, "dp": None, "ep": None, "pp": None,
            "instance_mapping": None,
            "metric_schema": None,
            "certified": self.certified,
            "run_id": self.fingerprint_hash[:16],
        }

    @property
    def certified(self) -> bool:
        """Dirty trees refuse certification (brief item 21).

        Research/debug runs on dirty trees still fingerprint exactly —
        the hash covers commit+dirty — but carry no certified claim.
        """
        return not self.source_dirty

    def to_dict(self) -> dict[str, Any]:
        d = self._identity_dict()
        d["fingerprint_hash"] = self.fingerprint_hash
        d["certified"] = self.certified
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ExecutionFingerprint":
        """Reload + re-verify: tampered dimensions fail closed."""
        try:
            fp = execution_fingerprint(
                execution_class=d["execution_class"],
                workload_artifact_hash=d["workload_artifact_hash"],
                node_count=d["node_count"],
                fabric_topology=d["fabric_topology"],
                fabric_routing=d["fabric_routing"],
                vc_count=d["vc_count"],
                buffer_flits=d["buffer_flits"],
                packet_bytes=d["packet_bytes"],
                flit_bytes=d["flit_bytes"],
                simulator_binary_sha=d["simulator_binary_sha"],
                simulator_config_sha=d["simulator_config_sha"],
                mapping=d["mapping"],
                seed=d["seed"],
                seed_policy=d["seed_policy"],
                source_commit=d["source_commit"],
                source_dirty=d["source_dirty"],
                container_digest=d["container_digest"],
                python_lock_sha=d["python_lock_sha"],
            )
        except (KeyError, TypeError) as e:
            raise StudyError(f"malformed ExecutionFingerprint: {e}") from e
        if fp.fingerprint_hash != d.get("fingerprint_hash"):
            raise StudyError(
                "fingerprint_hash mismatch — an execution dimension was "
                "tampered with or corrupted")
        return fp


def fingerprints_equal(a: ExecutionFingerprint,
                       b: ExecutionFingerprint) -> bool:
    """Exact execution identity — for cache reuse only, never comparability.

    Comparing mesh vs torus MUST differ in topology; a fingerprint
    mismatch there is expected, and ComparisonIntent decides whether the
    difference is a declared axis or a refusal.
    """
    return a.fingerprint_hash == b.fingerprint_hash


def verify_study_anchor(recorded_hash: str | None,
                        study_dict: dict[str, Any]) -> StudyManifest:
    """Prove a run manifest's recorded study hash anchors this study.

    Reloads + re-verifies the study (inner hash included), then compares
    against the externally recorded hash. A payload+hash swap fails here
    unless the attacker also rewrites every anchor above it.
    """
    m = StudyManifest.from_dict(study_dict)
    if m.manifest_hash != recorded_hash:
        raise StudyError(
            "recorded study hash does not match study — substitution "
            "or tamper above the study level")
    return m


def execution_fingerprint(*, execution_class: str = "booksim",
                          workload_artifact_hash: str,
                          node_count: int,
                          fabric_topology: str, fabric_routing: str,
                          vc_count: int, buffer_flits: int,
                          packet_bytes: int, flit_bytes: int,
                          simulator_binary_sha: str,
                          simulator_config_sha: str,
                          mapping: list[dict[str, Any]] | tuple,
                          seed: int, seed_policy: str,
                          source_commit: str, source_dirty: bool,
                          container_digest: str,
                          python_lock_sha: str) -> ExecutionFingerprint:
    """Build + hash an exact execution fingerprint.

    Any missing/None/ill-typed material dimension raises StudyError —
    the whole point: unknown dimensions are unrepresentable here, so a
    certified claim can never rest on a silent None. Bare-metal runs
    pass ``container_digest="uncontainerized:<platform>"`` explicitly.
    """
    if not isinstance(source_dirty, bool):
        raise StudyError(
            f"source_dirty must be bool, got {source_dirty!r}")
    if execution_class not in EXECUTION_CLASSES:
        raise StudyError(
            f"execution class {execution_class!r} has no wired comparison "
            f"projection — supported: {EXECUTION_CLASSES} (narrower-but-"
            "sound beats broad-but-guessed)")
    fp = ExecutionFingerprint(
        execution_class=execution_class,
        workload_artifact_hash=_require_str(
            "workload_artifact_hash", workload_artifact_hash),
        node_count=_require_int("node_count", node_count, minimum=1),
        fabric_topology=_require_str("fabric_topology", fabric_topology),
        fabric_routing=_require_str("fabric_routing", fabric_routing),
        vc_count=_require_int("vc_count", vc_count, minimum=1),
        buffer_flits=_require_int("buffer_flits", buffer_flits, minimum=1),
        packet_bytes=_require_int("packet_bytes", packet_bytes, minimum=1),
        flit_bytes=_require_int("flit_bytes", flit_bytes, minimum=1),
        simulator_binary_sha=_require_str(
            "simulator_binary_sha", simulator_binary_sha),
        simulator_config_sha=_require_str(
            "simulator_config_sha", simulator_config_sha),
        mapping=_require_mapping(mapping),
        seed=_require_int("seed", seed, minimum=0),
        seed_policy=_require_str("seed_policy", seed_policy),
        source_commit=_require_str("source_commit", source_commit),
        source_dirty=source_dirty,
        container_digest=_require_str("container_digest",
                                      container_digest),
        python_lock_sha=_require_str("python_lock_sha", python_lock_sha),
    )
    object.__setattr__(fp, "fingerprint_hash",
                       _sha256_hex(canonical_json(fp._identity_dict())))
    return fp


@dataclass(frozen=True)
class StudyManifest:
    """One immutable study: intent + candidate execution references.

    Candidates are referenced by fingerprint hash (evidence stays in the
    runs they came from — the study never copies simulator numbers).
    """
    study_id: str
    study_kind: str
    workload_artifact_hash: str
    candidate_hashes: tuple[str, ...]
    controlled_dimensions: dict[str, str]
    experimental_variables: frozenset[str]
    seed_policy: str
    backend_policy: str
    manifest_hash: str = ""

    def _identity_dict(self) -> dict[str, Any]:
        return {
            "study_id": self.study_id,
            "study_kind": self.study_kind,
            "workload_artifact_hash": self.workload_artifact_hash,
            # Sorted: candidate ORDER is presentation, not science.
            "candidate_hashes": sorted(self.candidate_hashes),
            "controlled_dimensions": dict(sorted(
                self.controlled_dimensions.items())),
            "experimental_variables": sorted(self.experimental_variables),
            "seed_policy": self.seed_policy,
            "backend_policy": self.backend_policy,
        }

    @property
    def candidate_count(self) -> int:
        return len(self.candidate_hashes)

    def comparison_intent(self) -> dict[str, Any]:
        """Intent dict consumable by comparison.resolve_intent as-is."""
        return {
            "kind": self.study_kind,
            "objectives": ["latency"],
            "experimental_variables": sorted(self.experimental_variables),
            "controlled_dimensions": dict(self.controlled_dimensions),
        }

    def to_dict(self) -> dict[str, Any]:
        d = self._identity_dict()
        d["experimental_variables"] = list(d["experimental_variables"])
        d["manifest_hash"] = self.manifest_hash
        d["candidate_count"] = self.candidate_count
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "StudyManifest":
        try:
            m = study_manifest(
                study_id=d["study_id"], study_kind=d["study_kind"],
                workload_artifact_hash=d["workload_artifact_hash"],
                candidate_hashes=d["candidate_hashes"],
                controlled_dimensions=d.get("controlled_dimensions", {}),
                experimental_variables=d.get("experimental_variables", ()),
                seed_policy=d["seed_policy"],
                backend_policy=d["backend_policy"],
            )
        except (KeyError, TypeError) as e:
            raise StudyError(f"malformed StudyManifest: {e}") from e
        if m.manifest_hash != d.get("manifest_hash"):
            raise StudyError(
                "manifest_hash mismatch — study intent was tampered with "
                "or corrupted")
        return m


def study_manifest(*, study_id: str, study_kind: str,
                   workload_artifact_hash: str,
                   candidate_hashes: list[str] | tuple[str, ...],
                   controlled_dimensions: dict[str, str] | None = None,
                   experimental_variables=(),
                   seed_policy: str, backend_policy: str) -> StudyManifest:
    """Build + hash a study manifest. Empty/duplicate candidates refuse."""
    if not isinstance(study_id, str) or not study_id:
        raise StudyError("study_id must be a non-empty string")
    if study_kind not in STUDY_KINDS:
        raise StudyError(
            f"unknown study kind {study_kind!r} — must be one of "
            f"{STUDY_KINDS}")
    hashes = tuple(candidate_hashes)
    if not hashes:
        raise StudyError("a study with zero candidates states nothing")
    if len(set(hashes)) != len(hashes):
        raise StudyError("duplicate candidate fingerprint hashes")
    for h in hashes:
        _require_str("candidate_hash", h)
    controlled = dict(controlled_dimensions or {})
    for k, v in controlled.items():
        _require_str(f"controlled_dimensions[{k!r}]", v)
    variables = frozenset(experimental_variables)
    for v in variables:
        _require_str("experimental_variable", v)
    m = StudyManifest(
        study_id=study_id, study_kind=study_kind,
        workload_artifact_hash=_require_str(
            "workload_artifact_hash", workload_artifact_hash),
        candidate_hashes=hashes,
        controlled_dimensions=controlled,
        experimental_variables=variables,
        seed_policy=_require_str("seed_policy", seed_policy),
        backend_policy=_require_str("backend_policy", backend_policy),
    )
    object.__setattr__(m, "manifest_hash",
                       _sha256_hex(canonical_json(m._identity_dict())))
    return m

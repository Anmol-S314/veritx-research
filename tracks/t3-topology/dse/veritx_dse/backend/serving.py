"""veritx_dse.backend.serving — serving BookSim consumer seam (B3.7c).

The serving path historically synthesized its own BookSim topology and
config from ``network.yml`` and hardcoded ``--booksim2-flit-bytes=64``
(BYTES). Neither is a fabric authority, and 64 bits silently becoming
64 bytes is exactly the class of bug B3.7 exists to prevent.

This module prepares the certified serving backend directory from a
validated ResolvedFabricBundle:

    config.cfg          exact BookSim config (canonical projection)
    topology.anynet     exact topology render
    flit_bytes.txt      exact bits -> bytes conversion (refuses 64->64)
    physical_dims.json  logical ASTRA dims (execution input, not fabric)

The vendored serving module consumes that directory through the
``VERITX_CERTIFIED_BACKEND_DIR`` seam (serving/veritx_certified.py). When
the seam is absent, the old direct serving path remains
``LEGACY_NON_CERTIFIED``. There is deliberately NO upstream ResolvedFabric
in the public serving control path yet, so serving execution stays
BLOCKED for full certification and route realization is declared
UNREPRESENTABLE (no embedded executed-route evidence).

Unit conversion rules:
  * flit width -> flit bytes must be exact (`flit_width_bits % 8 == 0`);
  * `packet_size` is never emitted: embedded traffic length is
    ``ceil(message_bytes / flit_bytes)`` from ``Booksim2NetworkApi::sim_send``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .booksim import (
    BOOKSIM_CONFIG_KEY_ORDER, BOOKSIM_LOWERER_VERSION, ROUTE_DUMP_FILE,
    SERVING_BOOKSIM2_PROFILE, SERVING_BOOKSIM2_SEMANTICS_VERSION,
    TOPOLOGY_FILE, exact_flit_bytes, lower_booksim_projection,
    materialize_backend, render_topology_anynet, verify_materialized,
)
from .booksim_profile import BOOKSIM_SERVING_PROFILE as SERVING_PROFILE_SPEC
from .bundle import ResolvedFabricBundle
from .contracts import (
    BackendConfigArtifact, BackendInputManifest, BackendTarget,
    ParameterOwner, RenderedInput, sha256_bytes,
)

SERVING_CONFIG_FILE = "config.cfg"
SERVING_FLIT_BYTES_FILE = "flit_bytes.txt"
SERVING_PHYSICAL_DIMS_FILE = "physical_dims.json"

SERVING_EXECUTION_MODE = "REAL_SIMULATION_EMBEDDED"
SERVING_SEED = 1


class ServingBackendError(ValueError):
    """The certified serving backend cannot be prepared/validated."""


# ── closed ownership table (serving target) ─────────────────────────────
# Derived from the same B3.7g closed-world audit as standalone; the only
# ownership differences are the profile-selected traffic/sample values.

SERVING_BOOKSIM2_OWNERSHIP: dict[str, ParameterOwner] = \
    SERVING_PROFILE_SPEC.ownership()

_SERVING_KEY_ORDER: tuple[str, ...] = BOOKSIM_CONFIG_KEY_ORDER

_PROJECTION_ONLY_KEYS = frozenset({"routing_class",
                                   "channel_latency_cycles"})

if set(_SERVING_KEY_ORDER) != set(SERVING_BOOKSIM2_OWNERSHIP):  # pragma: no cover
    raise ServingBackendError(
        "serving ownership table does not match the rendered key set")


# ── lowering / rendering ────────────────────────────────────────────────

def lower_serving_booksim(
        bundle: ResolvedFabricBundle, *,
        profile: str = SERVING_BOOKSIM2_PROFILE) -> BackendConfigArtifact:
    if profile != SERVING_BOOKSIM2_PROFILE:
        raise ServingBackendError(
            f"unknown serving BookSim profile {profile!r}")
    return lower_booksim_projection(
        bundle, target=BackendTarget.SERVING_BOOKSIM2, profile=profile,
        semantics_version=SERVING_BOOKSIM2_SEMANTICS_VERSION,
        lowerer_version=BOOKSIM_LOWERER_VERSION)


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    raise ServingBackendError(f"cannot render value {value!r}")


def validate_physical_dims(physical_dims: Any, *,
                           endpoint_count: int) -> tuple[int, ...]:
    """Logical ASTRA dims: positive ints whose product is the endpoint
    universe. Missing/invalid data must fail closed."""
    if not isinstance(physical_dims, (list, tuple)) or not physical_dims:
        raise ServingBackendError(
            "physical_dims must be a non-empty list of positive ints")
    dims = []
    for value in physical_dims:
        if type(value) is not int or value < 1:
            raise ServingBackendError(
                f"physical_dims entries must be positive ints, got "
                f"{value!r}")
        dims.append(value)
    product = 1
    for d in dims:
        product *= d
    if product != endpoint_count:
        raise ServingBackendError(
            f"physical_dims {dims} multiply to {product}, but the "
            f"attachment has {endpoint_count} endpoints")
    return tuple(dims)


def render_serving_config(config: BackendConfigArtifact) -> bytes:
    """Render the exact embedded BookSim config (no packet_size)."""
    if config.backend_target is not BackendTarget.SERVING_BOOKSIM2:
        raise ServingBackendError(
            f"config target {config.backend_target.value} is not "
            f"{BackendTarget.SERVING_BOOKSIM2.value}")
    values: dict[str, Any] = {
        key: value for key, value in config.normalized_parameters
        if key not in _PROJECTION_ONLY_KEYS}
    values["network_file"] = TOPOLOGY_FILE
    values["seed"] = SERVING_SEED
    # The embedded AnyNet build also honors the dump seam; emitting it keeps
    # the closed-world key set identical and gives future route evidence.
    values["routing_dump_file"] = ROUTE_DUMP_FILE
    unowned = set(values) - set(SERVING_BOOKSIM2_OWNERSHIP)
    if unowned:
        raise ServingBackendError(
            f"serving parameters without an owner: {sorted(unowned)}")
    missing = set(SERVING_BOOKSIM2_OWNERSHIP) - set(values)
    if missing:
        raise ServingBackendError(
            f"serving ownership keys not rendered: {sorted(missing)}")
    lines = [f"{key} = {_format_value(values[key])};"
             for key in _SERVING_KEY_ORDER]
    return ("\n".join(lines) + "\n").encode()


@dataclass(frozen=True)
class ServingRendered:
    files: tuple[tuple[str, bytes], ...]

    def file(self, logical_name: str) -> bytes:
        for name, data in self.files:
            if name == logical_name:
                return data
        raise ServingBackendError(f"no rendered file {logical_name!r}")


@dataclass(frozen=True)
class PreparedServingBackend:
    bundle: ResolvedFabricBundle
    config: BackendConfigArtifact
    flit_bytes: int
    physical_dims: tuple[int, ...]
    rendered: ServingRendered
    manifest: BackendInputManifest
    directory: str


def prepare_serving_booksim(
        bundle: ResolvedFabricBundle, *, out_dir: Path,
        physical_dims: Any,
        profile: str = SERVING_BOOKSIM2_PROFILE) -> PreparedServingBackend:
    """Lower + render + bind + materialize the certified serving backend.

    The directory is run-owned: the caller passes a run dir, and the files
    are hash-verified by the serving consumer through the seam.
    """
    config = lower_serving_booksim(bundle, profile=profile)
    flit_bytes = exact_flit_bytes(bundle.packet_format)
    dims = validate_physical_dims(
        physical_dims, endpoint_count=bundle.attachment.endpoint_count)
    cfg = render_serving_config(config)
    files = (
        (SERVING_CONFIG_FILE, cfg),
        (TOPOLOGY_FILE, render_topology_anynet(bundle)),
        (SERVING_FLIT_BYTES_FILE, f"{flit_bytes}\n".encode()),
        (SERVING_PHYSICAL_DIMS_FILE,
         (json.dumps({"dims": list(dims)}, sort_keys=True) + "\n").encode()),
    )
    rendered = ServingRendered(files=tuple(sorted(files)))
    roles = {SERVING_CONFIG_FILE: "booksim_config", TOPOLOGY_FILE: "topology",
             SERVING_FLIT_BYTES_FILE: "flit_conversion",
             SERVING_PHYSICAL_DIMS_FILE: "physical_dims"}
    manifest = BackendInputManifest(
        backend_config_hash=config.backend_config_hash(),
        workload_hash=None,
        execution_mode=SERVING_EXECUTION_MODE,
        seed=SERVING_SEED,
        seed_policy="pinned_profile",
        rendered_inputs=tuple(
            RenderedInput(role=roles[name], logical_name=name,
                          sha256=sha256_bytes(data), size=len(data))
            for name, data in rendered.files),
        invocation_args=(("config-file", SERVING_CONFIG_FILE),
                         ("flit-bytes", str(flit_bytes)),
                         ("physical-dims",
                          ",".join(str(d) for d in dims)),
                         ("replay-only", "false")),
    )
    directory = Path(out_dir)
    materialize_backend(rendered, manifest, directory)
    return PreparedServingBackend(
        bundle=bundle, config=config, flit_bytes=flit_bytes,
        physical_dims=dims, rendered=rendered, manifest=manifest,
        directory=str(directory))


def verify_serving_prepared(prepared: PreparedServingBackend) -> None:
    """Re-hash the materialized serving inputs (consumer preflight)."""
    verify_materialized(prepared.manifest, Path(prepared.directory))


def serving_backend_evidence(prepared: PreparedServingBackend) -> dict:
    """Exact-input provenance for a prepared serving backend (B3.7e).

    Mirrors the standalone evidence vocabulary: both identity hashes, the
    logical rendered inputs with content hashes, and every command-line
    value that alters embedded network behavior (flit bytes, logical dims,
    replay mode).
    """
    return {
        "backend_config_hash": prepared.config.backend_config_hash(),
        "backend_input_hash": prepared.manifest.backend_input_hash(),
        "resolved_fabric_hash": prepared.config.resolved_fabric_hash,
        "fabric_hash": prepared.config.fabric_hash,
        "execution_mode": prepared.manifest.execution_mode,
        "flit_bytes": prepared.flit_bytes,
        "physical_dims": list(prepared.physical_dims),
        "invocation_args": dict(prepared.manifest.invocation_args),
        "rendered_inputs": [r.identity_dict()
                            for r in prepared.manifest.rendered_inputs],
        "semantic_loss": list(prepared.config.semantic_loss_summary()),
    }


# ── mechanical consumption validation (transition path) ────────────────

_CFG_KV_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^;]+);\s*$",
                        re.M)


def validate_serving_consumption(
        prepared: PreparedServingBackend, *,
        cfg_text: str, flit_bytes: int,
        physical_dims: Any, replay_only: bool) -> None:
    """Refuse a serving execution that diverges from the certified inputs.

    This is the mechanical equivalence check for transition paths: an
    independently generated config may be supplied, but every fabric
    parameter, the flit-byte conversion, the logical dims and the replay
    mode must agree with the prepared certified projection.
    """
    if replay_only:
        raise ServingBackendError(
            "replay_only serving runs are not network execution and cannot "
            "consume a certified backend")
    expected_flit = exact_flit_bytes(prepared.bundle.packet_format)
    if flit_bytes != expected_flit:
        raise ServingBackendError(
            f"serving flit_bytes={flit_bytes} does not match the exact "
            f"PacketFormatArtifact conversion "
            f"({prepared.bundle.packet_format.flit_width_bits} bits -> "
            f"{expected_flit} bytes); 64 bits must never become 64 bytes")
    dims = validate_physical_dims(
        physical_dims,
        endpoint_count=prepared.bundle.attachment.endpoint_count)
    if dims != prepared.physical_dims:
        raise ServingBackendError(
            f"serving physical_dims {dims} do not match the prepared "
            f"certified dims {prepared.physical_dims}")

    kv = {m.group(1): m.group(2).strip() for m in _CFG_KV_RE.finditer(cfg_text)}
    if "packet_size" in kv:
        raise ServingBackendError(
            "generated serving config declares packet_size, which does not "
            "control embedded sim_send traffic; a certified config must not "
            "carry a false packetization authority")
    expected = dict(prepared.config.normalized_parameters)
    expected.pop("routing_class", None)
    expected.pop("channel_latency_cycles", None)
    for key, value in expected.items():
        if key not in kv:
            raise ServingBackendError(
                f"generated serving config is missing certified parameter "
                f"{key!r}")
        if kv[key] != _format_value(value):
            raise ServingBackendError(
                f"generated serving config {key}={kv[key]!r} does not match "
                f"the certified projection {_format_value(value)!r}")


__all__ = [
    "PreparedServingBackend",
    "SERVING_BOOKSIM2_OWNERSHIP",
    "SERVING_BOOKSIM2_PROFILE",
    "SERVING_CONFIG_FILE",
    "SERVING_FLIT_BYTES_FILE",
    "SERVING_PHYSICAL_DIMS_FILE",
    "ServingBackendError",
    "ServingRendered",
    "lower_serving_booksim",
    "prepare_serving_booksim",
    "render_serving_config",
    "serving_backend_evidence",
    "validate_physical_dims",
    "validate_serving_consumption",
    "verify_serving_prepared",
]

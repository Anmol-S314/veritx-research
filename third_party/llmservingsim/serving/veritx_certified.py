"""VeritX certified serving backend consumer seam (Wave B3.7c).

When ``VERITX_CERTIFIED_BACKEND_DIR`` is set, the serving module MUST
consume the exact backend bytes prepared by the VeriTX certified lowerer
instead of synthesizing a BookSim config from ``network.yml`` and
hardcoding ``--booksim2-flit-bytes=64`` (BYTES). This module only loads
and validates the directory contract; it never interprets fabric
semantics and never falls back to inference.

Directory contract (written by ``veritx_dse.backend.serving``):

    config.cfg          exact BookSim config (fabric projection)
    topology.anynet     exact topology render (referenced by config.cfg)
    flit_bytes.txt      one integer: exact bits -> bytes conversion
    physical_dims.json  {"dims": [positive ints]} logical ASTRA dims

Any missing or malformed file raises ``CertifiedBackendError`` — the
certified path fails closed. When the environment variable is absent the
legacy serving path is unchanged and remains non-certified.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CERTIFIED_BACKEND_ENV = "VERITX_CERTIFIED_BACKEND_DIR"
CONFIG_NAME = "config.cfg"
FLIT_BYTES_NAME = "flit_bytes.txt"
PHYSICAL_DIMS_NAME = "physical_dims.json"


class CertifiedBackendError(RuntimeError):
    """The certified backend directory violates its contract."""


def certified_backend_dir(environ: dict | None = None) -> str | None:
    value = (os.environ if environ is None else environ).get(
        CERTIFIED_BACKEND_ENV)
    return value or None


def load_certified_backend(directory: str | os.PathLike) -> dict:
    """Strictly load the certified backend directory contract."""
    root = Path(directory)
    if not root.is_dir():
        raise CertifiedBackendError(
            f"{CERTIFIED_BACKEND_ENV}={root}: not a directory")

    config = root / CONFIG_NAME
    if not config.is_file():
        raise CertifiedBackendError(
            f"{CERTIFIED_BACKEND_ENV}: missing {CONFIG_NAME} in {root}")

    flit_path = root / FLIT_BYTES_NAME
    if not flit_path.is_file():
        raise CertifiedBackendError(
            f"{CERTIFIED_BACKEND_ENV}: missing {FLIT_BYTES_NAME} in {root}")
    flit_text = flit_path.read_text().strip()
    if not flit_text.isdigit():
        raise CertifiedBackendError(
            f"{CERTIFIED_BACKEND_ENV}: {FLIT_BYTES_NAME} must contain one "
            f"integer, got {flit_text!r}")
    flit_bytes = int(flit_text)
    if flit_bytes < 1:
        raise CertifiedBackendError(
            f"{CERTIFIED_BACKEND_ENV}: flit_bytes must be >= 1, got "
            f"{flit_bytes}")

    dims_path = root / PHYSICAL_DIMS_NAME
    if not dims_path.is_file():
        raise CertifiedBackendError(
            f"{CERTIFIED_BACKEND_ENV}: missing {PHYSICAL_DIMS_NAME} in "
            f"{root}")
    try:
        payload = json.loads(dims_path.read_text())
    except (OSError, ValueError) as exc:
        raise CertifiedBackendError(
            f"{CERTIFIED_BACKEND_ENV}: invalid {PHYSICAL_DIMS_NAME}: "
            f"{exc}") from exc
    if not isinstance(payload, dict) or "dims" not in payload:
        raise CertifiedBackendError(
            f"{CERTIFIED_BACKEND_ENV}: {PHYSICAL_DIMS_NAME} must be an "
            f"object with a 'dims' list")
    raw_dims = payload["dims"]
    if not isinstance(raw_dims, list) or not raw_dims:
        raise CertifiedBackendError(
            f"{CERTIFIED_BACKEND_ENV}: 'dims' must be a non-empty list")
    for value in raw_dims:
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise CertifiedBackendError(
                f"{CERTIFIED_BACKEND_ENV}: dims entries must be positive "
                f"ints, got {value!r}")

    return {
        "dir": str(root),
        "config_path": str(config),
        "flit_bytes": flit_bytes,
        "physical_dims": tuple(int(v) for v in raw_dims),
    }


def resolve_certified_backend(environ: dict | None = None) -> dict | None:
    """Load the certified backend when the seam env var is present."""
    directory = certified_backend_dir(environ)
    if directory is None:
        return None
    return load_certified_backend(directory)


__all__ = [
    "CERTIFIED_BACKEND_ENV",
    "CONFIG_NAME",
    "FLIT_BYTES_NAME",
    "PHYSICAL_DIMS_NAME",
    "CertifiedBackendError",
    "certified_backend_dir",
    "load_certified_backend",
    "resolve_certified_backend",
]

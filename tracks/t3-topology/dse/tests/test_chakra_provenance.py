"""tests/test_chakra_provenance.py — which Chakra am I running?

Gate V2.1. The repository's canonical Chakra source is VENDORED inside
ASTRA-Sim:

    third_party/astra-sim/extern/graph_frontend/chakra/

``utils/install_chakra.sh`` pip-installs that local directory, and the
root Dockerfile copies it onto PYTHONPATH. That makes it possible for a
developer machine to keep executing a STALE installed copy after the
vendored source changes — a correct patch then looks broken, or worse, an
old implementation looks qualified.

Version numbers cannot detect this: upstream-equivalent and locally
patched copies both call themselves 0.0.4. The check is therefore
SOURCE-CONTENT identity.

Dependency classification this gate enforces:

    ordinary DSE Python libraries        -> requirements.lock
    qualified modified simulation tools  -> third_party/* + METADATA.json

Chakra belongs to the second category THROUGH ASTRA-Sim. It must not be
added to requirements.lock as an ordinary PyPI dependency, and there must
not be a second vendored copy, an external patch file, or a modified
site-packages tree.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

DSE = Path(__file__).resolve().parents[1]
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

CHAKRA_REL = ("third_party/astra-sim/extern/graph_frontend/chakra/"
              "src/converter/llm_converter.py")
VENDORED = REPO / CHAKRA_REL


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_vendored_chakra_converter_exists():
    assert VENDORED.is_file(), (
        f"the vendored Chakra converter is missing: {VENDORED}")


def test_imported_converter_matches_the_vendored_source():
    """The runtime must execute the repository's converter bytes.

    Fails with a repair instruction rather than a diff: the usual cause is
    a stale ``pip install`` of the vendored directory.
    """
    spec = importlib.util.find_spec("chakra.src.converter.llm_converter")
    assert spec is not None and spec.origin, "chakra is not importable"
    runtime = Path(spec.origin)
    assert _sha256(runtime) == _sha256(VENDORED), (
        "imported Chakra converter does not match the vendored ASTRA "
        f"converter.\n  runtime : {runtime}\n  vendored: {VENDORED}\n"
        "Reinstall the repository copy, e.g.\n"
        "  python3 -m pip install --user --force-reinstall --no-deps "
        "--break-system-packages \\\n"
        f"      {REPO}/third_party/astra-sim/extern/graph_frontend/chakra\n"
        "or use the qualified container.")


def test_version_alone_is_not_enough():
    """Why the fingerprint exists: both copies are 0.0.4."""
    import importlib.metadata as md
    assert md.version("chakra") == "0.0.4"
    assert "0.0.4" in (VENDORED.parents[2] / "pyproject.toml").read_text()


def test_local_veritx_modifications_are_marked():
    """Vendored deltas carry a VeriTX marker (repo convention)."""
    assert "VeriTX" in VENDORED.read_text()


def test_no_second_chakra_copy_or_patch_mechanism():
    """One source of truth: no third_party/chakra, no patches/ dir."""
    assert not (REPO / "third_party" / "chakra").exists(), (
        "a second Chakra vendoring must not exist")
    assert not (DSE / "patches").exists(), (
        "Chakra is patched in the vendored source, not by patch files")


def test_chakra_is_not_an_ordinary_python_dependency():
    """It is a qualified backend dependency, not a PyPI requirement."""
    for name in ("requirements.lock", "pyproject.toml"):
        p = DSE / name
        if p.exists() and "chakra" in p.read_text().lower():
            text = p.read_text().lower()
            assert "astra-sim/extern" in text or "vendor" in text, (
                f"{name} lists chakra without marking it as vendored")


def test_docker_uses_the_same_source_tree():
    """The container's PYTHONPATH copy must not be a different Chakra."""
    dockerfile = REPO / "Dockerfile"
    if not dockerfile.exists():
        return
    text = dockerfile.read_text()
    if "chakra" in text.lower():
        assert "extern/graph_frontend/chakra" in text, (
            "Dockerfile references Chakra but not the vendored ASTRA path")

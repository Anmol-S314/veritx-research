"""Provenance and determinism of the serving Chakra fixtures (R1.1/R1.2).

The integration tests in ``test_full_pipeline.py`` used to depend on a
developer-local LLMServingSim run directory that never existed on a clean
clone. The fixtures are now generated deterministically from canonical text
traces (``veritx_dse.tools.gen_serving_chakra_fixtures``) using the tracked
Chakra converter. This test proves the committed bytes are exactly what the
generator produces, so the fixtures are not opaque blobs.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from veritx_dse.tools.gen_serving_chakra_fixtures import (
    CASES,
    FIXTURE_ROOT,
    generate,
)

MANIFEST = FIXTURE_ROOT / "MANIFEST.json"


def _converter_available() -> bool:
    from veritx_dse.tools.gen_serving_chakra_fixtures import CHAKRA_ROOT

    return (CHAKRA_ROOT / "src" / "converter" / "llm_converter.py").exists()


pytestmark = pytest.mark.skipif(
    not _converter_available(), reason="tracked Chakra converter not present"
)


def test_committed_fixtures_match_a_fresh_generation():
    """Every committed fixture byte-equals a fresh deterministic generation."""
    assert MANIFEST.exists(), "fixture manifest missing"
    with tempfile.TemporaryDirectory() as td:
        generated = generate(Path(td))
        diffs = []
        for path in sorted(FIXTURE_ROOT.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(FIXTURE_ROOT)
            fresh = Path(td) / rel
            if not fresh.exists() or path.read_bytes() != fresh.read_bytes():
                diffs.append(str(rel))
        assert not diffs, f"committed fixtures differ from regeneration: {diffs}"
        committed = json.loads(MANIFEST.read_text())
        assert generated["manifest_id"] == committed["manifest_id"]


def test_manifest_digests_match_the_committed_bytes():
    manifest = json.loads(MANIFEST.read_text())
    assert manifest["generator_version"]
    assert manifest["files"], "manifest lists no fixture files"
    for rel, entry in manifest["files"].items():
        data = (FIXTURE_ROOT / rel).read_bytes()
        assert len(data) == entry["size"], rel
        import hashlib

        assert hashlib.sha256(data).hexdigest() == entry["sha256"], rel


def test_every_canonical_case_has_a_recorded_trace_and_rank_files():
    manifest = json.loads(MANIFEST.read_text())
    recorded = set(manifest["canonical_inputs"])
    assert recorded == set(CASES)
    for name, case in CASES.items():
        assert (FIXTURE_ROOT / "traces" / f"{name}.txt").exists()
        ranks = sorted((FIXTURE_ROOT / name).glob("llm.*.et"))
        assert len(ranks) == case["num_npus"], name


def test_generator_source_is_hashed_into_the_manifest():
    manifest = json.loads(MANIFEST.read_text())
    hashed = manifest["generator_source_sha256"]
    assert (
        "veritx_dse/tools/gen_serving_chakra_fixtures.py" in hashed
    ), "generator source not hashed"
    assert (
        "third_party/astra-sim/extern/graph_frontend/chakra/src/converter/"
        "llm_converter.py" in hashed
    )

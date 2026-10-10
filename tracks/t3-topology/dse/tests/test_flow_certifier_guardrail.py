"""flow_certifier verifies the guardrail hash from the REAL emitter template.

``veritx_dse/tools/flow_certifier.py`` used to hash
``<seam_dir>/router_template.sv`` (a file under ``dse/.../scripts/rtlgen``
that does not exist), so every guardrail-hash check raised ``FileNotFoundError``
inside a broad handler and silently degraded to a non-fatal WARNING. The
template the emitter actually hashes lives with the emitter under
``<track>/rtl/mot_htree``.

These pins make the reconciliation durable: the hash is recomputed from that
real template against a live ``meta.json`` the emitter writes, and a missing
template FAILS CLOSED instead of warning.

Rationale: docs/decisions/modules/tools.md
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_DSE = _TESTS_DIR.parent
_TRACK_ROOT = _TESTS_DIR.parents[1]                    # .../tracks/t3-topology
_RTLGEN_DIR = _TRACK_ROOT / "scripts" / "rtlgen"
_GEN_RTL = _RTLGEN_DIR / "gen_rtl.py"
_EMITTER_DIR = _TRACK_ROOT / "rtl" / "mot_htree"
_EMITTER = _EMITTER_DIR / "gen_rtl_htree.py"
_FLOW_CERTIFIER = _DSE / "veritx_dse" / "tools" / "flow_certifier.py"

# flow_certifier resolves ``veritx_dse`` through whatever editable install is
# on the path; put THIS checkout's dse root first so the module under test is
# the local one.
sys.path.insert(0, str(_DSE))

# Row-major 2x2 mesh: the certified-slice topology the emitter accepts.
_TINY4_ANYNET = """\
router 0 node 0 router 1 router 2
router 1 node 1 router 0 router 3
router 2 node 2 router 0 router 3
router 3 node 3 router 1 router 2
"""
_TINY4 = {0: {1, 2}, 1: {0, 3}, 2: {0, 3}, 3: {1, 2}}


def _load_flow_certifier():
    spec = importlib.util.spec_from_file_location("flow_certifier",
                                                  _FLOW_CERTIFIER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["flow_certifier"] = module
    spec.loader.exec_module(module)
    return module


def _emit_meta(tmp_path: Path, *extra_args: str, direct: bool = False) -> dict:
    """Run a real RTL emitter on a temp anynet and return its meta.json."""
    anynet = tmp_path / "tiny4.anynet"
    anynet.write_text(_TINY4_ANYNET)
    outdir = tmp_path / "rtl"
    emitter = _EMITTER if direct else _GEN_RTL
    env = os.environ.copy()
    tools = str(_DSE / "veritx_dse" / "tools")
    env["PYTHONPATH"] = os.pathsep.join(
        (str(_DSE), tools, str(_EMITTER_DIR)))
    proc = subprocess.run(
        [sys.executable, str(emitter), "--anynet", str(anynet),
         "--outdir", str(outdir), *extra_args],
        capture_output=True, text=True, cwd=str(tmp_path), env=env)
    assert proc.returncode == 0, proc.stderr
    return json.loads((outdir / "meta.json").read_text())


def test_guardrail_hash_is_recomputed_from_the_real_emitter_template(tmp_path):
    certifier = _load_flow_certifier()

    # The path the certifier now uses is the emitter's own copy of the
    # template — the same file gen_rtl_htree.py hashes when it writes
    # meta.json["guardrail_hash"].
    assert certifier._EMITTER_DIR == _EMITTER_DIR
    assert (certifier._EMITTER_DIR / "router_template.sv").is_file()

    meta = _emit_meta(tmp_path)
    cert = {"verdict": "PASS"}

    matched = certifier.verify_guardrail_hash(cert, meta, _TINY4, 4)

    assert matched is True
    assert cert["verdict"] == "PASS"
    verification = cert["guardrail_hash_verification"]
    assert verification["match"] is True
    assert verification["recomputed_hash"] == meta["guardrail_hash"]
    assert meta["arch"] == "legacy-vc"
    assert meta["router_template"] == "router_template.sv"


def test_plane_v2_emission_selects_its_recorded_template(tmp_path):
    certifier = _load_flow_certifier()
    meta = _emit_meta(tmp_path, "--arch", "plane-v2", direct=True)
    assert meta["arch"] == "plane-v2"
    assert meta["router_template"] == "router_template_v2.sv"

    cert = {"verdict": "PASS"}
    assert certifier.verify_guardrail_hash(cert, meta, _TINY4, 4)
    assert cert["guardrail_hash_verification"]["match"] is True


def test_htree_emission_selects_its_recorded_template(tmp_path):
    certifier = _load_flow_certifier()
    meta = _emit_meta(tmp_path, "--htree", direct=True)
    assert meta["arch"] == "legacy-vc"
    assert meta["router_template"] == "router_htree.sv"

    cert = {"verdict": "PASS"}
    assert certifier.verify_guardrail_hash(cert, meta, _TINY4, 4)
    assert cert["guardrail_hash_verification"]["match"] is True


def test_missing_or_unknown_template_metadata_fails_closed(tmp_path):
    certifier = _load_flow_certifier()
    meta = _emit_meta(tmp_path)
    for bad_meta in ({key: value for key, value in meta.items()
                      if key != "router_template"},
                     {**meta, "router_template": "../router_template.sv"}):
        cert = {"verdict": "PASS"}
        assert certifier.verify_guardrail_hash(
            cert, bad_meta, _TINY4, 4) is False
        assert cert["verdict"] == "FAIL"
        assert cert["guardrail_hash_verification"]["match"] is None
        assert "router_template" in cert["guardrail_hash_verification"]["error"]


def test_template_metadata_mismatch_fails_hash_verification(tmp_path):
    certifier = _load_flow_certifier()
    meta = {**_emit_meta(tmp_path),
            "arch": "plane-v2",
            "router_template": "router_template_v2.sv"}
    cert = {"verdict": "PASS"}

    assert certifier.verify_guardrail_hash(cert, meta, _TINY4, 4) is False
    assert cert["verdict"] == "FAIL"
    assert cert["guardrail_hash_verification"]["match"] is False


def test_a_missing_template_fails_closed_instead_of_warning(tmp_path):
    certifier = _load_flow_certifier()
    meta = _emit_meta(tmp_path)

    # A real temp layout with no router template: the silent-warning path
    # must not return. A missing template forces the certificate to FAIL.
    empty_emitter = tmp_path / "emitter_without_template"
    empty_emitter.mkdir()
    cert = {"verdict": "PASS"}

    matched = certifier.verify_guardrail_hash(cert, meta, _TINY4, 4,
                                              emitter_dir=empty_emitter)

    assert matched is False
    assert cert["verdict"] == "FAIL"
    verification = cert["guardrail_hash_verification"]
    assert verification["match"] is None
    assert "router_template.sv" in verification["error"]
    assert "NOT verified" in verification["note"]

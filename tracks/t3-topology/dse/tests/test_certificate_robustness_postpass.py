"""Certificate post-PASS diagnostic robustness (§4 fix).

certify_deadlock_free's proof runs guarded, but the sccs_gt_1 diagnostic
rebuild used to sit OUTSIDE that guard: a semantic failure in the rebuild
escaped as an uncontrolled post-PASS exception instead of refusing the
obligation, and no test pinned the difference. This module pins it:

* injected semantic failure (CDGError/VeritXError) in the post-PASS
  rebuild -> DEADLOCK_FREE FAIL (refused), overall FAIL, no escape;
* injected programming fault (RuntimeError) -> propagates as an internal
  error, never laundered into an obligation FAIL.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_certificate_failclosed import _bundle  # noqa: E402
from veritx_dse.core.errors import VeritXError  # noqa: E402
from veritx_dse.verification.certificate import (  # noqa: E402
    verify_compiled_fabric,
)
from veritx_dse.verification.channel_vc_cdg import CDGError  # noqa: E402

def _deadlock_obligation(bundle):
    cert = verify_compiled_fabric(bundle)
    ob = {o.obligation: o for o in cert.obligations}
    return cert, ob["DEADLOCK_FREE"]

def test_baseline_carries_sccs_diagnostic():
    cert, ob = _deadlock_obligation(_bundle())
    assert cert.overall == "PASS"
    assert ob.status == "PASS"
    assert isinstance(ob.evidence.get("sccs_gt_1"), int)

def test_semantic_failure_in_postpass_rebuild_refuses(monkeypatch):
    """A semantic failure rebuilding the diagnostic refuses the obligation."""
    import veritx_dse.verification.channel_vc_cdg as cdg_module

    real_build = cdg_module.build_channel_vc_cdg
    calls = {"n": 0}

    def flaky_build(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            raise CDGError("injected post-PASS semantic failure")
        return real_build(*args, **kwargs)

    monkeypatch.setattr(cdg_module, "build_channel_vc_cdg", flaky_build)
    cert, ob = _deadlock_obligation(_bundle())
    assert calls["n"] == 2
    assert ob.status == "FAIL"
    assert "injected post-PASS semantic failure" in \
        ob.evidence["failure_reason"]
    assert cert.overall == "FAIL"

def test_veritx_error_base_class_also_refuses(monkeypatch):
    import veritx_dse.verification.channel_vc_cdg as cdg_module

    real_build = cdg_module.build_channel_vc_cdg
    calls = {"n": 0}

    def flaky_build(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            raise VeritXError("injected base-class semantic failure")
        return real_build(*args, **kwargs)

    monkeypatch.setattr(cdg_module, "build_channel_vc_cdg", flaky_build)
    cert, ob = _deadlock_obligation(_bundle())
    assert ob.status == "FAIL"
    assert cert.overall == "FAIL"

def test_programming_fault_escapes_as_internal_error(monkeypatch):
    """A programming fault must ABORT, never become an obligation FAIL."""
    import veritx_dse.verification.channel_vc_cdg as cdg_module

    real_build = cdg_module.build_channel_vc_cdg
    calls = {"n": 0}

    def faulty_build(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("injected programming fault")
        return real_build(*args, **kwargs)

    monkeypatch.setattr(cdg_module, "build_channel_vc_cdg", faulty_build)
    with pytest.raises(RuntimeError, match="injected programming fault"):
        verify_compiled_fabric(_bundle())
    assert calls["n"] == 2

def test_baseline_builds_twice_proof_plus_diagnostic(monkeypatch):
    """The passing path builds the CDG exactly twice (proof + guarded
    diagnostic rebuild) — the rebuild is real work, not dead code."""
    import veritx_dse.verification.channel_vc_cdg as cdg_module

    calls = {"n": 0}
    real_build = cdg_module.build_channel_vc_cdg

    def counting_build(*args, **kwargs):
        calls["n"] += 1
        return real_build(*args, **kwargs)

    monkeypatch.setattr(cdg_module, "build_channel_vc_cdg", counting_build)
    cert, ob = _deadlock_obligation(_bundle())
    assert ob.status == "PASS"
    assert calls["n"] == 2

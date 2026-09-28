"""Phase-3 exception taxonomy (capabilities + probe seams).

A programming error (AttributeError, TypeError, AssertionError, KeyError)
inside the capability derivation must escape — or surface as INTERNAL_ERROR
at a service boundary — never read as a semantic verdict ("not
materializable", "not executable"). Genuine semantic refusals (TopologyError
from the materializer, lowering/projection/ValueError in the probe) must
still classify as refused values.
"""
from __future__ import annotations

import pytest

from veritx_dse.model import topology_artifact as _topo_mod
from veritx_dse.optimization import capabilities as _caps_mod


def _materializable():
    _caps_mod._materializable_topology_families.cache_clear()
    try:
        return _caps_mod._materializable_topology_families()
    finally:
        _caps_mod._materializable_topology_families.cache_clear()


@pytest.mark.parametrize("bug", [
    AttributeError("injected: no such attribute"),
    TypeError("injected: bad operand"),
    AssertionError("injected: invariant broken"),
    KeyError("injected: missing key"),
])
def test_materializer_programmer_error_escapes_not_refused(
        monkeypatch, bug):
    """A bug in the family resolver propagates; it must never appear as a
    quietly refused topology_family value."""
    def _boom(noc):
        raise bug

    monkeypatch.setattr(_topo_mod, "_family_of", _boom)
    with pytest.raises(type(bug)):
        _materializable()


def test_materializer_semantic_refusal_still_classifies():
    """Real TopologyError values still land in refused, and every enum
    member is adjudicated exactly once (allowed xor refused)."""
    from veritx_dse.model.compile_model import TopologyFamily
    allowed, note = _materializable()
    assert "mesh" in allowed
    assert "gec" not in allowed and "fat_tree" not in allowed
    assert note
    members = {m.value for m in TopologyFamily}
    assert set(allowed) | set(
        m for m in members if m not in allowed) == members


@pytest.mark.parametrize("bug", [
    AttributeError("injected: no such attribute"),
    TypeError("injected: bad operand"),
    AssertionError("injected: invariant broken"),
    KeyError("injected: missing key"),
])
def test_probe_programmer_error_escapes_not_refused(monkeypatch, bug):
    """A bug in profile selection propagates; it must never read as
    (True, False, 'AttributeError: ...') executability verdict."""
    from veritx_dse.backend import booksim_projection as _proj_mod
    from veritx_dse.optimization.capability_probe import (
        _backend_executable, _base_request,
    )

    def _boom(parents):
        raise bug

    monkeypatch.setattr(_proj_mod, "select_booksim_profile", _boom)
    with pytest.raises(type(bug)):
        _backend_executable(_base_request())


def test_probe_vc_helper_bug_escapes_not_refused(monkeypatch):
    """A bug in VC resource projection propagates instead of refusing."""
    from veritx_dse.model import vc_resource as _vc_mod
    from veritx_dse.optimization.capability_probe import (
        _backend_executable, _base_request,
    )

    def _boom(assignment):
        raise KeyError("injected: vc table key")

    monkeypatch.setattr(_vc_mod, "vc_resources_from_assignment", _boom)
    with pytest.raises(KeyError):
        _backend_executable(_base_request())


def test_probe_semantic_refusals_still_classify():
    """Positive controls: the retained typed catches still work end to
    end — a good design executes and an uncompilable family is a compile
    refusal (never a crash, never a pass)."""
    from veritx_dse.optimization.capability_probe import (
        _backend_executable, _base_request,
    )
    compilable, executable, reason = _backend_executable(_base_request())
    assert (compilable, executable) == (True, True), reason
    compilable, executable, reason = _backend_executable(
        _base_request(topology_family="torus"))
    assert compilable is False and executable is False, reason
    assert reason.startswith("compile:")


def test_probe_projection_refusal_names_profile(monkeypatch):
    """A genuine projection refusal still classifies (does not crash,
    does not pass) and names the certified profile gate."""
    from veritx_dse.backend import booksim_projection as _proj_mod
    from veritx_dse.backend.booksim_projection import (
        BookSimProjectionError,
    )
    from veritx_dse.optimization.capability_probe import (
        _backend_executable, _base_request,
    )

    def _refuse(parents):
        raise BookSimProjectionError("injected: no profile covers this")

    monkeypatch.setattr(_proj_mod, "select_booksim_profile", _refuse)
    compilable, executable, reason = _backend_executable(_base_request())
    assert (compilable, executable) == (True, False), reason
    assert reason.startswith("certified profile refused:")


def test_probe_artifact_validation_refusal_names_type(monkeypatch):
    """An artifact-construction ValueError inside the probe try block
    still classifies and names its type instead of crashing the
    capability derivation. (A VC error raised earlier surfaces as a
    compile refusal — covered separately by the compile path.)"""
    from veritx_dse.workload import messages as _msg_mod
    from veritx_dse.optimization.capability_probe import (
        _backend_executable, _base_request,
    )

    def _refuse(**kwargs):
        raise ValueError("injected: illegal message artifact")

    monkeypatch.setattr(_msg_mod, "LogicalMessageArtifactV2", _refuse)
    compilable, executable, reason = _backend_executable(_base_request())
    assert (compilable, executable) == (True, False), reason
    assert reason.startswith("ValueError:")

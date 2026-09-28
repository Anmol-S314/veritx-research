"""Cache orchestration tests: explicit hits, transplant refusal, no id-keys."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.backend.evidence import BackendEvidenceError  # noqa: E402
from veritx_dse.backend.evidence_cache import (  # noqa: E402
    CacheMiss,
    EvidenceCache,
    KEY_FIELDS,
)


def _parents(**over):
    base = {k: f"{k}-v1" for k in KEY_FIELDS}
    base.update({
        "binary_size": 1234,
        "seed": 7,
        "network_clock_hz": 1_000_000_000,
    })
    base.update(over)
    return base


def _cache_with_stub(evidence_id="ev-1"):
    stub_ev = SimpleNamespace(evidence_id=evidence_id)
    cache = EvidenceCache(_read=lambda ref, **kw: stub_ev)
    return cache, stub_ev


def test_key_deterministic_and_order_independent():
    p1, p2 = _parents(), _parents()
    assert EvidenceCache.derive_key(p1) == EvidenceCache.derive_key(p2)
    assert len(EvidenceCache.derive_key(p1)) == 64


def test_key_refuses_partial_parents():
    p = _parents()
    del p["binary_sha256"]
    with pytest.raises(BackendEvidenceError):
        EvidenceCache.derive_key(p)


def test_unknown_key_is_typed_miss():
    cache, _ = _cache_with_stub()
    with pytest.raises(CacheMiss):
        cache.lookup("0" * 64, _parents())


def test_put_then_hit_returns_same_evidence_with_reused_id():
    from veritx_dse.backend.evidence import EvidenceRef

    cache, stub = _cache_with_stub("ev-9")
    ref = EvidenceRef(path="/tmp/x/backend-evidence.json",
                      sha256="a" * 64)
    key = cache.put(ref, _parents())
    ev, hit = cache.lookup(key, _parents())
    assert ev is stub and hit.reused_evidence_id == "ev-9" and hit.hits == 1


def test_producer_transplant_refused():
    from veritx_dse.backend.evidence import EvidenceRef

    cache, _ = _cache_with_stub()
    ref = EvidenceRef(path="/tmp/x/backend-evidence.json",
                      sha256="b" * 64)
    key = cache.put(ref, _parents())
    with pytest.raises(BackendEvidenceError, match="transplant refused"):
        cache.lookup(key, _parents(producer_revision="other"))


def test_config_transplant_refused():
    from veritx_dse.backend.evidence import EvidenceRef

    cache, _ = _cache_with_stub()
    ref = EvidenceRef(path="/tmp/x/backend-evidence.json",
                      sha256="c" * 64)
    key = cache.put(ref, _parents())
    with pytest.raises(BackendEvidenceError, match="transplant refused"):
        cache.lookup(key, _parents(config_sha256="changed"))


def test_clock_change_refused():
    from veritx_dse.backend.evidence import EvidenceRef

    cache, _ = _cache_with_stub()
    ref = EvidenceRef(path="/tmp/x/backend-evidence.json",
                      sha256="d" * 64)
    key = cache.put(ref, _parents())
    with pytest.raises(BackendEvidenceError, match="transplant refused"):
        cache.lookup(key, _parents(network_clock_hz=2_000_000_000))


def test_evidence_id_drift_refused():
    from veritx_dse.backend.evidence import EvidenceRef

    calls = {"n": 0}

    def flap(ref, **kw):
        calls["n"] += 1
        return SimpleNamespace(
            evidence_id="ev-a" if calls["n"] == 1 else "ev-b")

    cache = EvidenceCache(_read=flap)
    ref = EvidenceRef(path="/tmp/x/backend-evidence.json",
                      sha256="e" * 64)
    key = cache.put(ref, _parents())
    with pytest.raises(BackendEvidenceError, match="recomputation differs"):
        cache.lookup(key, _parents())


def test_no_study_id_key():
    assert "study_id" not in KEY_FIELDS and "trial_id" not in KEY_FIELDS

"""Measured model profile: durations + weights from real shipped data.

The profile is derived from the vendored llmservingsim architecture configs
and profiler CSVs. These tests pin the load-bearing properties: real
measured values, weight parity with the serving authority, and ABSENCE
reported as absence (never a placeholder).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.performance.model_profile import (  # noqa: E402
    ModelProfileError, ProfileShape, derive_profile,
)

QWEN = "Qwen/Qwen3-30B-A3B-Instruct-2507"
LLAMA = "meta-llama/Llama-3.1-8B"

def _prof(model, tp, ep=1, **shape):
    return derive_profile(model, tp=tp, ep=ep, shape=ProfileShape(**shape))

def test_qwen_tp1_profile_is_complete_with_measured_values():
    p = _prof(QWEN, 1, 4, tokens=1, n_decode=1, kv_decode=16)
    assert p.complete
    attn = next(l for l in p.layers if l.kind == "attention")
    moe = next(l for l in p.layers if l.kind == "moe")
    assert moe.duration_ns == 50230
    comps = dict(attn.duration_components)
    assert comps["attention"] == 7691
    assert attn.duration_ns == sum(comps.values())
    assert attn.duration_ns == 28880

def test_qwen_tp2_moe_is_unavailable_not_guessed():
    p = _prof(QWEN, 2, 4, tokens=1, n_decode=1, kv_decode=16)
    assert not p.complete
    attn = next(l for l in p.layers if l.kind == "attention")
    moe = next(l for l in p.layers if l.kind == "moe")
    assert attn.duration_ns is not None
    assert moe.duration_ns is None
    assert moe.missing and "moe" in moe.missing[0].lower()

def test_absent_optional_op_is_zero_not_missing():
    p = _prof(LLAMA, 2, tokens=1, n_decode=1, kv_decode=16)
    assert p.complete
    attn = next(l for l in p.layers if l.kind == "attention")
    comps = dict(attn.duration_components)
    assert comps["qk_norm"] == 0

def test_weight_bytes_match_the_serving_authority():
    from veritx_dse.performance.model_profile import _calculate_sizes
    calc = _calculate_sizes()
    p = _prof(QWEN, 2, 4)
    attn = next(l for l in p.layers if l.kind == "attention")
    moe = next(l for l in p.layers if l.kind == "moe")
    qkv = int(calc(QWEN, "qkv_proj", 1, parallel=2, fp=2)[1])
    o = int(calc(QWEN, "o_proj", 1, parallel=2, fp=2)[1])
    m = int(calc(QWEN, "moe", 1, parallel=4, fp=2)[1])
    assert attn.weight_bytes == qkv + o
    assert moe.weight_bytes == m

def test_compute_intent_refuses_an_unavailable_duration():
    p = _prof(QWEN, 2, 4)
    with pytest.raises(ModelProfileError):
        p.to_compute_intent(participants=8)

def test_compute_intent_emits_real_stages_when_complete():
    p = _prof(LLAMA, 2, tokens=1, n_decode=1, kv_decode=16)
    intent = p.to_compute_intent(participants=8)
    stages = intent["stages"]
    assert len(stages) == len(p.layers)
    assert all(s["duration_ns"] > 0 for s in stages)
    assert all(s["weight_bytes"] > 0 for s in stages)
    assert {s["owner"] for s in stages} <= set(range(8))

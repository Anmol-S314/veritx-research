"""Canonical hardware profiles are DERIVED from tracked measured sources.

No browser-authored profile; every field states whether an authority
consumes it; the profile never enters a design hash. Guards §4/§6/§9.
"""
from __future__ import annotations

import sys
from pathlib import Path

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.application.hardware_profiles import (  # noqa: E402
    CONSUMED, DESCRIPTIVE, hardware_profile_catalog, profile_for,
)


def test_rtxpro6000_profile_comes_from_tracked_measured_sources():
    p = profile_for("RTXPRO6000")
    assert p is not None
    assert p.device_kind == "GPU"
    assert p.memory_capacity_bytes == 96_000_000_000
    assert p.memory_bandwidth_bytes_per_s == 1_597_000_000_000
    assert p.timing_source is not None
    assert p.timing_source.status == "MEASURED"
    assert p.timing_source.model == "Qwen/Qwen3-30B-A3B-Instruct-2507"
    assert p.timing_source.tp_degrees == (1, 2)
    assert p.timing_source.consumed_by == "CANONICAL_SERVING"
    assert all(prov for prov in p.provenance)
    assert any("profiler/perf/RTXPRO6000" in prov for prov in p.provenance)


def test_dispositions_separate_descriptive_from_consumed():
    p = profile_for("RTXPRO6000")
    d = dict(p.dispositions)
    assert d["memory_capacity_bytes"] == CONSUMED
    assert d["memory_bandwidth_bytes_per_s"] == CONSUMED
    assert d["host_memory_bytes"] == DESCRIPTIVE
    assert d["link_latency_ns"] == DESCRIPTIVE
    assert "CANONICAL_SERVING" in p.consumers


def test_profile_identity_is_deterministic_and_prefixed():
    a = profile_for("RTXPRO6000")
    b = profile_for("RTXPRO6000")
    assert a.profile_id() == b.profile_id()
    assert a.profile_id().startswith("sha256:")


def test_catalog_is_transparent_and_unknown_has_no_profile():
    cat = hardware_profile_catalog()
    assert cat["contract_version"] == 1
    assert "NOT MODELED" in cat["note"]
    assert {p["hardware_id"] for p in cat["profiles"]} >= {"RTXPRO6000"}
    assert profile_for("DOES_NOT_EXIST") is None

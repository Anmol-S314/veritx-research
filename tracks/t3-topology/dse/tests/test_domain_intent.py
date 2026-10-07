"""Canonical clock / reset / power / crossing intent (docs/INTENT-V5-CONTRACT.md §6).

Every law in contract §6 gets its own refusal test. The properties under test
are the honest ones: exact integer clock identity, a supported async-assert /
sync-deassert release, a typed refusal for unsupported ASYNC deassertion, every
crossing compatibility law, and an async FIFO micro-oracle whose occupancy
never over-fills or underflows.

Nothing here claims metastability or signoff.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.model.domain_intent import (  # noqa: E402
    AssertionMode,
    AsyncFIFOConfig,
    AsyncFIFOModel,
    ClockDomain,
    ClockSource,
    ClockSourceKind,
    Crossing,
    CrossingMechanism,
    CrossingVerdict,
    DeassertionMode,
    DomainIntentError,
    FidelityLevel,
    PointerEncoding,
    Polarity,
    PowerDomain,
    PowerPolicy,
    ResetChannel,
    SignalKind,
    assess_crossing,
    check_clock_domains,
    validate_clock_domains,
    validate_reset_channels,
)


# ---------------------------------------------------------------- clock ----

def _src(**over):
    base = {"id": "pll0", "kind": "PLL", "frequency_hz": 1_000_000_000}
    base.update(over)
    return ClockSource.from_dict(base)


def _domain(**over):
    base = {"id": "core", "source_id": "pll0", "frequency_hz": 1_000_000_000,
            "divider_num": 1, "divider_den": 1}
    base.update(over)
    return ClockDomain.from_dict(base)


def test_clock_source_roundtrip():
    s = _src()
    assert ClockSource.from_dict(s.to_dict()) == s


def test_clock_domain_roundtrip():
    d = _domain(divider_num=2)
    # authored freq must equal the exact derivation (1e9 / 2)
    d = _domain(divider_num=2, frequency_hz=500_000_000)
    assert ClockDomain.from_dict(d.to_dict()) == d
    assert d.divider_num == 2


def test_clock_source_unknown_key_refuses():
    with pytest.raises(DomainIntentError) as e:
        ClockSource.from_dict({"id": "x", "kind": "PLL",
                               "frequency_hz": 1, "jitter_ps": 3})
    assert "jitter_ps" in str(e.value)


def test_clock_domain_unknown_key_refuses():
    with pytest.raises(DomainIntentError) as e:
        ClockDomain.from_dict({"id": "core", "source_id": "pll0",
                               "frequency_hz": 1, "phase_deg": 0.0})
    assert "phase_deg" in str(e.value)


def test_missing_required_field_refuses():
    with pytest.raises(DomainIntentError):
        ClockSource.from_dict({"id": "pll0", "kind": "PLL"})


def test_exact_integer_above_2_53_is_preserved():
    big = 9007199254740993          # 2**53 + 1, not representable as a float
    assert _src(frequency_hz=big).frequency_hz == big
    assert ClockSource.from_dict(_src(frequency_hz=big).to_dict()) \
        .frequency_hz == big


def test_integral_scientific_string_is_exact():
    assert _src(frequency_hz="1e9").frequency_hz == 10 ** 9


@pytest.mark.parametrize("bad", ["1.5", "0.1", "nan", "inf", ""])
def test_inexact_string_refuses(bad):
    with pytest.raises(DomainIntentError):
        _src(frequency_hz=bad)


@pytest.mark.parametrize("bad", [1.5, 0.1, 1e9])
def test_binary_float_refuses_outright(bad):
    """A clock identity may never round: binary floats are refused, period."""
    with pytest.raises(DomainIntentError) as e:
        _src(frequency_hz=bad)
    assert "float" in str(e.value) or "exact" in str(e.value)


@pytest.mark.parametrize("bad", [0, -1, True, False])
def test_non_positive_or_bool_hz_refuses(bad):
    with pytest.raises(DomainIntentError):
        _src(frequency_hz=bad)


def test_period_is_exact_integer_or_absent():
    assert _src().period_ps == 1000              # 1 GHz -> 1000 ps
    # 3 Hz does not divide 10**12: report nothing rather than a rounded period
    with pytest.raises(DomainIntentError) as e:
        _src(id="odd", frequency_hz=3).period_ps
    assert "round" in str(e.value)


def test_divider_non_integer_derivation_refuses_never_rounds():
    d = _domain(divider_num=3, frequency_hz=333_333_333)
    with pytest.raises(DomainIntentError) as e:
        validate_clock_domains([_src()], [d])
    assert "evenly" in str(e.value)
    assert "round" in str(e.value)


def test_divider_law_rejects_inauthored_frequency():
    # exact derivation is 1e9 / 2 = 5e8, but the domain claims 6e8
    d = _domain(divider_num=2, frequency_hz=600_000_000)
    with pytest.raises(DomainIntentError) as e:
        validate_clock_domains([_src()], [d])
    assert "500000000" in str(e.value)


def test_unknown_source_id_refuses():
    with pytest.raises(DomainIntentError) as e:
        validate_clock_domains([_src()], [_domain(source_id="pll1")])
    assert "pll1" in str(e.value)


def test_duplicate_domain_ids_refuse():
    with pytest.raises(DomainIntentError) as e:
        validate_clock_domains([_src()], [_domain(), _domain()])
    assert "duplicate" in str(e.value)


def test_exact_divider_multiplication_is_valid():
    # source * den / num with an exact integer result is legal
    d = _domain(divider_num=1, divider_den=3, frequency_hz=3_000_000_000)
    validate_clock_domains([_src()], [d])


def test_divider_values_must_be_positive():
    with pytest.raises(DomainIntentError):
        _domain(divider_num=0)
    with pytest.raises(DomainIntentError):
        _domain(divider_den=-1)


def test_empty_clock_intent_is_valid_neutral():
    """v4 shipped with no clock domains at all; empty must stay valid."""
    assert check_clock_domains([], []) is True
    validate_clock_domains([], [])


def test_check_clock_domains_never_repairs():
    assert check_clock_domains([_src()],
                               [_domain(source_id="nope")]) is False


# --------------------------------------------------------------- reset -----

def _reset(**over):
    base = {"id": "rst_a", "source_id": "por", "target_clock_domain": "core",
            "assertion": "ASYNC", "deassertion": "SYNC",
            "synchronizer_stages": 2}
    base.update(over)
    return ResetChannel.from_dict(base)


def test_reset_roundtrip_async_assert_sync_deassert():
    r = _reset()
    assert r.assertion is AssertionMode.ASYNC
    assert r.deassertion is DeassertionMode.SYNC
    assert r.async_assert_sync_deassert is True
    assert ResetChannel.from_dict(r.to_dict()) == r


def test_reset_roundtrip_with_none_stages_survives():
    r = _reset(assertion="SYNC", synchronizer_stages=None)
    assert r.synchronizer_stages is None
    assert ResetChannel.from_dict(r.to_dict()).synchronizer_stages is None


def test_async_deassertion_is_a_typed_refusal_at_from_dict():
    with pytest.raises(DomainIntentError) as e:
        _reset(deassertion="ASYNC")
    msg = str(e.value)
    assert "not supported" in msg
    assert "SYNC" in msg


def test_deassertion_enum_has_no_async_member():
    """ASYNC deassertion must not exist as a value — it is unsupported."""
    assert [m.value for m in DeassertionMode] == ["SYNC"]
    assert not hasattr(DeassertionMode, "ASYNC")


def test_async_assertion_without_release_synchronizer_refuses():
    with pytest.raises(DomainIntentError) as e:
        _reset(synchronizer_stages=None)
    assert "synchronizer_stages >= 2" in str(e.value)


@pytest.mark.parametrize("stages", [0, 1])
def test_async_assertion_with_too_few_stages_refuses(stages):
    with pytest.raises(DomainIntentError) as e:
        _reset(synchronizer_stages=stages)
    # either the minimum-2 law or the async-assert law must fire
    assert "synchronizer_stages" in str(e.value)


def test_sync_assertion_needs_no_release_synchronizer():
    r = _reset(assertion="SYNC", synchronizer_stages=None)
    assert r.async_assert_sync_deassert is False
    assert r.synchronizer_stages is None


def test_reset_polarity_defaults_and_roundtrips():
    r = _reset()
    assert r.polarity is Polarity.ACTIVE_HIGH
    assert ResetChannel.from_dict(r.to_dict()).polarity is Polarity.ACTIVE_HIGH


def test_reset_unknown_key_refuses():
    with pytest.raises(DomainIntentError) as e:
        _reset(deassert_latency=4)
    assert "deassert_latency" in str(e.value)


def test_reset_self_dependency_refuses():
    with pytest.raises(DomainIntentError):
        _reset(depends_on=["rst_a"])


def test_reset_channel_must_declare_id():
    with pytest.raises(DomainIntentError):
        ResetChannel.from_dict({"source_id": "por",
                                "target_clock_domain": "core",
                                "assertion": "SYNC",
                                "deassertion": "SYNC"})


def test_reset_dependency_cycle_refuses_release_order():
    a = _reset(id="a", depends_on=["b"])
    b = _reset(id="b", depends_on=["a"])
    with pytest.raises(DomainIntentError) as e:
        validate_reset_channels([a, b])
    assert "cycle" in str(e.value)


def test_reset_unknown_dependency_refuses():
    with pytest.raises(DomainIntentError) as e:
        validate_reset_channels([_reset(depends_on=["ghost"])])
    assert "ghost" in str(e.value)


def test_reset_target_domain_existence_is_checkable():
    d = _domain()
    validate_reset_channels([_reset()], [d], check_domain_existence=True)
    with pytest.raises(DomainIntentError) as e:
        validate_reset_channels([_reset()], [], check_domain_existence=True)
    assert "core" in str(e.value)


def test_reset_duplicate_ids_refuse():
    with pytest.raises(DomainIntentError):
        validate_reset_channels([_reset(), _reset()])


def test_empty_reset_intent_is_valid_neutral():
    validate_reset_channels([])


# --------------------------------------------------------------- power -----

def test_power_domain_roundtrip():
    p = PowerDomain.from_dict(
        {"id": "pd_always", "policy": "ALWAYS_ON", "name": "always-on",
         "declared_states": ["ON"]})
    assert PowerDomain.from_dict(p.to_dict()) == p
    assert p.always_on is True


def test_power_domain_collapsible_and_empty_states_roundtrip():
    p = PowerDomain(id="pd1", policy=PowerPolicy.COLLAPSIBLE)
    assert p.declared_states == ()
    assert p.name == ""
    assert p.always_on is False
    assert PowerDomain.from_dict(p.to_dict()) == p


def test_power_domain_unknown_policy_refuses():
    with pytest.raises(DomainIntentError) as e:
        PowerDomain.from_dict({"id": "pd1", "policy": "UPF_SIGNOFF"})
    assert "UPF_SIGNOFF" in str(e.value)


def test_power_domain_duplicate_states_refuse():
    with pytest.raises(DomainIntentError):
        PowerDomain(id="pd1", policy=PowerPolicy.COLLAPSIBLE,
                    declared_states=("SLEEP", "SLEEP"))


def test_power_domain_is_not_upf():
    """Architectural label only — no isolation/retention claim is generated."""
    p = PowerDomain(id="pd1", policy=PowerPolicy.ALWAYS_ON)
    assert not any(k in p.to_dict() for k in
                   ("isolation", "retention", "level_shifter"))


def test_power_domain_unknown_key_refuses():
    with pytest.raises(DomainIntentError):
        PowerDomain.from_dict({"id": "pd1", "policy": "ALWAYS_ON",
                               "upf_file": "x.upf"})


# ------------------------------------------------------------ crossing -----

def _fifo(depth=8):
    return AsyncFIFOConfig.from_dict(
        {"depth": depth, "write_width": 128, "read_width": 32,
         "pointer_encoding": "GRAY", "synchronizer_stages": 2})


def _cross(**over):
    base = {"id": "x1", "src_clock": "a", "dst_clock": "b",
            "signal_kind": "SINGLE_BIT", "mechanism": "SYNC_2FF",
            "synchronizer_stages": 2}
    base.update(over)
    return Crossing.from_dict(base)


def test_async_fifo_config_roundtrip():
    f = _fifo()
    assert AsyncFIFOConfig.from_dict(f.to_dict()) == f


def test_async_fifo_config_unknown_key_refuses():
    with pytest.raises(DomainIntentError) as e:
        AsyncFIFOConfig.from_dict(
            {"depth": 8, "write_width": 8, "read_width": 8,
             "pointer_encoding": "GRAY", "synchronizer_stages": 2,
             "almost_full": 6})
    assert "almost_full" in str(e.value)


@pytest.mark.parametrize("depth", [0, 1])
def test_async_fifo_depth_must_be_at_least_two(depth):
    with pytest.raises(DomainIntentError):
        AsyncFIFOConfig(depth=depth, write_width=8, read_width=8,
                        pointer_encoding=PointerEncoding.GRAY,
                        synchronizer_stages=2)


def test_gray_pointer_requires_power_of_two_depth():
    with pytest.raises(DomainIntentError) as e:
        AsyncFIFOConfig(depth=3, write_width=8, read_width=8,
                        pointer_encoding=PointerEncoding.GRAY,
                        synchronizer_stages=2)
    assert "power of two" in str(e.value)


def test_binary_pointer_allows_non_power_of_two_depth():
    f = AsyncFIFOConfig(depth=3, write_width=8, read_width=8,
                        pointer_encoding=PointerEncoding.BINARY,
                        synchronizer_stages=2)
    assert f.depth == 3


def test_fifo_widths_must_be_positive():
    with pytest.raises(DomainIntentError):
        AsyncFIFOConfig(depth=4, write_width=0, read_width=8,
                        pointer_encoding=PointerEncoding.BINARY,
                        synchronizer_stages=2)
    with pytest.raises(DomainIntentError):
        AsyncFIFOConfig(depth=4, write_width=8, read_width=0,
                        pointer_encoding=PointerEncoding.BINARY,
                        synchronizer_stages=2)


def test_fifo_synchronizer_stages_at_least_two():
    with pytest.raises(DomainIntentError):
        AsyncFIFOConfig(depth=4, write_width=8, read_width=8,
                        pointer_encoding=PointerEncoding.BINARY,
                        synchronizer_stages=1)


def test_crossing_roundtrip_two_ff():
    c = _cross()
    assert Crossing.from_dict(c.to_dict()) == c
    assert c.requires_clock_crossing is True


def test_crossing_roundtrip_with_async_fifo():
    c = _cross(signal_kind="BUS", mechanism="ASYNC_FIFO",
               synchronizer_stages=None, async_fifo=_fifo().to_dict())
    assert Crossing.from_dict(c.to_dict()) == c
    assert c.async_fifo.depth == 8


def test_crossing_roundtrip_unresolved():
    c = _cross(mechanism="UNRESOLVED", synchronizer_stages=None,
               reason="no clock relationship known")
    assert Crossing.from_dict(c.to_dict()) == c


def test_crossing_unknown_key_refuses():
    with pytest.raises(DomainIntentError) as e:
        _cross(latency_cycles=3)
    assert "latency_cycles" in str(e.value)


def test_same_domain_is_not_a_crossing():
    with pytest.raises(DomainIntentError) as e:
        _cross(dst_clock="a")
    assert "not a clock-domain crossing" in str(e.value)


def test_empty_clock_names_refuse():
    with pytest.raises(DomainIntentError):
        _cross(src_clock="")


def test_async_fifo_mechanism_requires_a_configuration():
    with pytest.raises(DomainIntentError) as e:
        _cross(signal_kind="BUS", mechanism="ASYNC_FIFO",
               synchronizer_stages=None, async_fifo=None)
    assert "no async_fifo configuration" in str(e.value)


def test_fifo_configuration_without_async_fifo_mechanism_refuses():
    with pytest.raises(DomainIntentError) as e:
        _cross(mechanism="SYNC_2FF", synchronizer_stages=2,
               async_fifo=_fifo().to_dict())
    assert "two authorities" in str(e.value)


def test_async_fifo_crossing_must_not_restate_stages_at_crossing_level():
    with pytest.raises(DomainIntentError) as e:
        _cross(signal_kind="BUS", mechanism="ASYNC_FIFO",
               synchronizer_stages=2, async_fifo=_fifo().to_dict())
    assert "synchronizer_stages" in str(e.value)


@pytest.mark.parametrize("kind", ["SINGLE_BIT", "PULSE"])
def test_level_sensitive_signal_cannot_use_async_fifo(kind):
    with pytest.raises(DomainIntentError) as e:
        _cross(signal_kind=kind, mechanism="ASYNC_FIFO",
               synchronizer_stages=None, async_fifo=_fifo().to_dict())
    assert "ASYNC_FIFO" in str(e.value)


@pytest.mark.parametrize("kind,stages", [("MULTI_BIT", 2), ("BUS", 3)])
def test_multibit_signal_cannot_use_single_flop_synchronizer(kind, stages):
    with pytest.raises(DomainIntentError) as e:
        _cross(signal_kind=kind, synchronizer_stages=stages)
    msg = str(e.value)
    assert "multi-bit" in msg
    assert "ASYNC_FIFO" in msg


def test_sync_2ff_requires_exactly_two_stages():
    with pytest.raises(DomainIntentError):
        _cross(synchronizer_stages=None)
    with pytest.raises(DomainIntentError) as e:
        _cross(synchronizer_stages=3)
    assert "exactly 2" in str(e.value)


def test_sync_3ff_requires_exactly_three_stages():
    c = _cross(mechanism="SYNC_3FF", synchronizer_stages=3)
    assert c.mechanism is CrossingMechanism.SYNC_3FF
    with pytest.raises(DomainIntentError) as e:
        _cross(mechanism="SYNC_3FF", synchronizer_stages=2)
    assert "exactly 3" in str(e.value)


def test_handshake_stage_choices():
    assert _cross(mechanism="HANDSHAKE", synchronizer_stages=None).mechanism \
        is CrossingMechanism.HANDSHAKE
    assert _cross(mechanism="HANDSHAKE", synchronizer_stages=3).synchronizer_stages == 3
    with pytest.raises(DomainIntentError) as e:
        _cross(mechanism="HANDSHAKE", synchronizer_stages=5)
    assert "HANDSHAKE accepts" in str(e.value)


def test_unresolved_requires_a_named_reason():
    with pytest.raises(DomainIntentError) as e:
        _cross(mechanism="UNRESOLVED", synchronizer_stages=None, reason="")
    assert "UNRESOLVED" in str(e.value)


def test_unresolved_must_not_carry_mechanism_parameters():
    with pytest.raises(DomainIntentError):
        _cross(mechanism="UNRESOLVED", synchronizer_stages=2, reason="why?")


def test_unknown_mechanism_refuses():
    with pytest.raises(DomainIntentError) as e:
        _cross(mechanism="SYNC_4FF")
    assert "SYNC_4FF" in str(e.value)


def test_assess_unresolved_is_never_promoted_to_valid():
    """The honest answer stays UNRESOLVED — no auto-selected 2FF."""
    c = _cross(mechanism="UNRESOLVED", synchronizer_stages=None,
               reason="clock ratio unknown")
    a = assess_crossing(c)
    assert a.intent_verdict is CrossingVerdict.UNRESOLVED_CROSSING
    assert a.reason == "clock ratio unknown"
    assert a.performance_fidelity is FidelityLevel.NOT_MODELED
    assert a.signoff_verified is False
    assert "SYNC_2FF" not in a.reason


def test_assess_performance_fidelity_is_per_mechanism():
    two_ff = assess_crossing(_cross())
    assert two_ff.intent_verdict is CrossingVerdict.INTENT_VALID
    assert two_ff.performance_fidelity is FidelityLevel.NOT_MODELED

    fifo = assess_crossing(_cross(
        signal_kind="BUS", mechanism="ASYNC_FIFO",
        synchronizer_stages=None, async_fifo=_fifo(depth=16).to_dict()))
    assert fifo.intent_verdict is CrossingVerdict.INTENT_VALID
    assert fifo.performance_fidelity is FidelityLevel.HETERO_TIMING_ABSTRACT


def test_signoff_is_always_false():
    """No mechanism in this module performs signoff, so it can never be True."""
    for c in (_cross(),
              _cross(signal_kind="BUS", mechanism="ASYNC_FIFO",
                     synchronizer_stages=None, async_fifo=_fifo().to_dict())):
        assert assess_crossing(c).signoff_verified is False


def test_assessment_mentions_no_metastability_claim():
    a = assess_crossing(_cross())
    assert "no metastability claim" in a.reason
    assert "NOT signoff" in a.reason
    assert set(a.as_dict()) == {"crossing_id", "intent_verdict", "reason",
                                "performance_fidelity", "signoff_verified"}


# ------------------------------------------------- async FIFO model (Q1) ---

def test_fifo_model_never_overfills():
    m = AsyncFIFOModel(AsyncFIFOConfig(
        depth=4, write_width=8, read_width=8,
        pointer_encoding=PointerEncoding.GRAY, synchronizer_stages=2))
    assert m.fill() == 4
    assert m.occupancy == 4
    assert m.full is True
    # fill() itself ran into the wall once; count from there.
    rejected_at_full = m.backpressured_writes
    # further writes are refused, never accepted past depth
    for _ in range(5):
        assert m.write_accepted() is False
    assert m.occupancy == 4 == m.depth
    assert m.backpressured_writes == rejected_at_full + 5


def test_fifo_model_never_underflows():
    m = AsyncFIFOModel(AsyncFIFOConfig(
        depth=4, write_width=8, read_width=8,
        pointer_encoding=PointerEncoding.GRAY, synchronizer_stages=2))
    assert m.empty is True
    assert m.occupancy == 0
    assert m.read_accepted() is False
    assert m.occupancy == 0
    assert m.accepted_reads == 0


def test_fifo_model_latency_delays_readability():
    m = AsyncFIFOModel(AsyncFIFOConfig(
        depth=4, write_width=8, read_width=8,
        pointer_encoding=PointerEncoding.GRAY, synchronizer_stages=2))
    assert m.write_accepted() is True
    assert m.occupancy == 1          # occupying a slot...
    assert m.in_synchronizer == 1
    assert m.readable == 0
    assert m.read_accepted() is False  # ...but not yet synchronised
    m.advance(1)
    assert m.read_accepted() is False
    m.advance(1)
    assert m.readable == 1
    assert m.read_accepted() is True
    assert m.occupancy == 0
    assert m.empty is True


def test_fifo_model_preserves_write_order():
    m = AsyncFIFOModel(AsyncFIFOConfig(
        depth=8, write_width=8, read_width=8,
        pointer_encoding=PointerEncoding.GRAY, synchronizer_stages=2))
    for _ in range(5):
        assert m.write_accepted() is True
    m.advance(2)
    # interleave reads and writes; completed order must stay FIFO
    assert m.read_accepted() is True
    assert m.write_accepted() is True
    assert m.read_accepted() is True
    m.advance(2)
    assert m.read_accepted() is True
    assert m.read_accepted() is True
    assert m.read_accepted() is True
    assert m.read_accepted() is True    # seq5, written after the first reads
    assert m.read_accepted() is False   # drained
    assert m.read_order == (0, 1, 2, 3, 4, 5)


def test_fifo_model_occupancy_watermark_never_exceeds_depth():
    m = AsyncFIFOModel(AsyncFIFOConfig(
        depth=8, write_width=8, read_width=8,
        pointer_encoding=PointerEncoding.GRAY, synchronizer_stages=3))
    watermark = 0
    for i in range(40):
        m.write_accepted()
        watermark = max(watermark, m.occupancy)
        assert 0 <= m.occupancy <= 8
        if i % 3 == 0:
            m.advance(2)
            m.read_accepted()
        assert m.occupancy >= 0
    assert watermark <= 8


def test_fifo_model_backpressure_is_refusal_not_drop():
    m = AsyncFIFOModel(AsyncFIFOConfig(
        depth=2, write_width=8, read_width=8,
        pointer_encoding=PointerEncoding.GRAY, synchronizer_stages=2))
    assert m.write_accepted() and m.write_accepted()
    assert m.write_accepted() is False     # backpressure
    assert m.accepted_writes == 2          # nothing silently vanished
    assert m.backpressured_writes == 1
    m.advance(2)
    assert m.drain() == 2
    assert m.occupancy == 0


def test_fifo_model_latency_is_a_single_authority():
    cfg = AsyncFIFOConfig(depth=4, write_width=8, read_width=8,
                          pointer_encoding=PointerEncoding.GRAY,
                          synchronizer_stages=2)
    assert AsyncFIFOModel(cfg).fidelity is FidelityLevel.HETERO_TIMING_ABSTRACT
    assert AsyncFIFOModel(cfg, synchronizer_latency_cycles=2).cycle == 0
    with pytest.raises(DomainIntentError) as e:
        AsyncFIFOModel(cfg, synchronizer_latency_cycles=5)
    assert "one authority" in str(e.value).lower()


def test_fifo_model_rejects_bad_config_type():
    with pytest.raises(DomainIntentError):
        AsyncFIFOModel("depth=4")


def test_fifo_model_reports_abstract_fidelity_not_signoff():
    """Occupancy cost is abstract heterogeneous timing, never signoff."""
    m = AsyncFIFOModel(AsyncFIFOConfig(
        depth=4, write_width=8, read_width=8,
        pointer_encoding=PointerEncoding.GRAY, synchronizer_stages=2))
    assert m.fidelity is FidelityLevel.HETERO_TIMING_ABSTRACT
    assert "NOT_MODELED" in FidelityLevel.NOT_MODELED.name


def test_fifo_model_advance_is_exact_int_only():
    m = AsyncFIFOModel(AsyncFIFOConfig(
        depth=4, write_width=8, read_width=8,
        pointer_encoding=PointerEncoding.BINARY, synchronizer_stages=2))
    with pytest.raises(DomainIntentError):
        m.advance(1.5)
    with pytest.raises(DomainIntentError):
        m.advance(-1)
    m.advance(0)
    assert m.cycle == 0

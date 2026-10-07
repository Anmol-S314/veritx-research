"""Sideband interfaces and connectivity (contract §7).

Architectural intent only: a sideband is a first-class edge, never a payload
the main NoC data plane carries. Every invalid declaration refuses with a
typed SidebandError; nothing is silently repaired, defaulted to a legal value,
or resolved into a clock-crossing mechanism.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.model.sideband import (  # noqa: E402
    Direction,
    SidebandConnection,
    SidebandEndpointRef,
    SidebandError,
    SidebandInterface,
    SidebandKind,
    validate_sidebands,
)

AGENTS = ("tile0", "tile1", "hbm0")


def _iface(**over):
    base = {
        "id": "irq_out",
        "kind": "interrupt",
        "direction": "output",
        "width_bits": 1,
        "clock_domain": "clk_a",
        "power_domain": "pd_logic",
        "protocol_binding": None,
    }
    base.update(over)
    return base


def _out(**over):
    return SidebandInterface.from_dict(_iface(**over))


def _in(**over):
    base = {"id": "irq_in", "direction": "input"}
    base.update(over)
    return SidebandInterface.from_dict(_iface(**base))


def _conn(**over):
    base = {
        "connection_id": "c0",
        "source": {"agent": "tile0", "sideband_id": "irq_out"},
        "destination": {"agent": "tile1", "sideband_id": "irq_in"},
    }
    base.update(over)
    return SidebandConnection.from_dict(base)


# --------------------------------------------------------------------------
# roundtrip
# --------------------------------------------------------------------------

def test_interface_roundtrip_full():
    iface = _out()
    assert SidebandInterface.from_dict(iface.to_dict()) == iface


def test_interface_roundtrip_minimal():
    iface = SidebandInterface.from_dict({
        "id": "q", "kind": "qos", "direction": "output", "width_bits": 4})
    again = SidebandInterface.from_dict(iface.to_dict())
    assert again == iface


def test_connection_roundtrip():
    conn = _conn()
    assert SidebandConnection.from_dict(conn.to_dict()) == conn


def test_endpoint_ref_roundtrip():
    ref = SidebandEndpointRef(agent="tile0", sideband_id="irq_out")
    assert SidebandEndpointRef.from_dict(ref.to_dict()) == ref


# --------------------------------------------------------------------------
# unknown keys refuse on every from_dict
# --------------------------------------------------------------------------

def test_interface_unknown_key_refuses():
    with pytest.raises(SidebandError) as e:
        SidebandInterface.from_dict(_iface(synchronizer_stages=2))
    assert "synchronizer_stages" in str(e.value)


def test_connection_unknown_key_refuses():
    with pytest.raises(SidebandError) as e:
        SidebandConnection.from_dict({
            "connection_id": "c0",
            "source": {"agent": "tile0", "sideband_id": "irq_out"},
            "destination": {"agent": "tile1", "sideband_id": "irq_in"},
            "vc": 3,
        })
    assert "vc" in str(e.value)


def test_endpoint_ref_unknown_key_refuses():
    with pytest.raises(SidebandError) as e:
        SidebandEndpointRef.from_dict({"agent": "a", "sideband_id": "b",
                                       "width": 8})
    assert "width" in str(e.value)


def test_missing_required_field_refuses():
    with pytest.raises(SidebandError) as e:
        SidebandInterface.from_dict({"id": "x", "kind": "interrupt",
                                     "direction": "input"})
    assert "width_bits" in str(e.value)


def test_non_object_refuses():
    with pytest.raises(SidebandError):
        SidebandInterface.from_dict(["not", "an", "object"])


# --------------------------------------------------------------------------
# vocabulary is exact
# --------------------------------------------------------------------------

def test_sideband_kind_has_the_eleven_contract_values():
    assert tuple(k.value for k in SidebandKind) == (
        "interrupt", "qos", "error", "poison", "snoop_control",
        "power_state", "reset", "clock_request", "credit_status",
        "trace", "custom")


def test_direction_has_exactly_two_values():
    assert tuple(d.value for d in Direction) == ("output", "input")


def test_unknown_kind_value_refuses_with_known_list():
    with pytest.raises(SidebandError) as e:
        SidebandInterface.from_dict(_iface(kind="nmi"))
    assert "interrupt" in str(e.value)


def test_unknown_direction_value_refuses():
    with pytest.raises(SidebandError):
        SidebandInterface.from_dict(_iface(direction="bidirectional"))


# --------------------------------------------------------------------------
# interface field laws
# --------------------------------------------------------------------------

def test_width_must_be_at_least_one():
    with pytest.raises(SidebandError) as e:
        _out(width_bits=0)
    assert "width_bits" in str(e.value)


@pytest.mark.parametrize("bad", [1.5, "8", True, None])
def test_width_must_be_an_exact_int(bad):
    with pytest.raises(SidebandError):
        _out(width_bits=bad)


def test_empty_id_refuses():
    with pytest.raises(SidebandError):
        _out(id="")


def test_empty_clock_domain_refuses_but_none_is_allowed():
    with pytest.raises(SidebandError):
        _out(clock_domain="")
    assert _out(clock_domain=None).clock_domain is None


def test_protocol_binding_is_not_inferred():
    """Absent binding stays None — never coerced to 'AXI' or ''."""
    iface = SidebandInterface.from_dict({
        "id": "t", "kind": "trace", "direction": "output", "width_bits": 1})
    assert iface.protocol_binding is None
    assert iface.to_dict()["protocol_binding"] is None


# --------------------------------------------------------------------------
# no fabricated values: None stays None through serialization
# --------------------------------------------------------------------------

def test_none_domains_survive_roundtrip_as_none():
    iface = _out(clock_domain=None, power_domain=None)
    d = iface.to_dict()
    assert d["clock_domain"] is None
    assert d["power_domain"] is None
    assert SidebandInterface.from_dict(d) == iface
    assert SidebandInterface.from_dict(d).clock_domain is None


# --------------------------------------------------------------------------
# connection laws
# --------------------------------------------------------------------------

def test_self_connection_refuses():
    with pytest.raises(SidebandError) as e:
        SidebandConnection.from_dict({
            "connection_id": "c0",
            "source": {"agent": "tile0", "sideband_id": "irq_out"},
            "destination": {"agent": "tile0", "sideband_id": "irq_out"},
        })
    assert "self-connection" in str(e.value)


def test_empty_connection_id_refuses():
    with pytest.raises(SidebandError):
        _conn(connection_id="")


def test_non_endpoint_ref_end_refuses():
    with pytest.raises(SidebandError) as e:
        SidebandConnection(connection_id="c0", source="tile0",
                           destination=_conn().destination)
    assert "source must be a SidebandEndpointRef" in str(e.value)

    with pytest.raises(SidebandError) as e2:
        SidebandConnection(connection_id="c0", source=_conn().source,
                           destination="tile1")
    assert "destination must be a SidebandEndpointRef" in str(e2.value)


# --------------------------------------------------------------------------
# validate_sidebands
# --------------------------------------------------------------------------

def test_valid_connection_passes():
    validate_sidebands([_out(), _in()], [_conn()], agent_universe=AGENTS)


def test_empty_connection_list_passes():
    validate_sidebands([_out(), _in()], [], agent_universe=AGENTS)


def test_unknown_sideband_id_refuses():
    conn = _conn()
    bad = SidebandConnection(
        connection_id=conn.connection_id,
        source=conn.source,
        destination=SidebandEndpointRef(agent="tile1",
                                        sideband_id="does_not_exist"),
    )
    with pytest.raises(SidebandError) as e:
        validate_sidebands([_out(), _in()], [bad], agent_universe=AGENTS)
    assert "does_not_exist" in str(e.value)
    assert "not a declared sideband interface" in str(e.value)


def test_agent_outside_universe_refuses():
    conn = _conn()
    bad = SidebandConnection(
        connection_id=conn.connection_id,
        source=SidebandEndpointRef(agent="ghost", sideband_id="irq_out"),
        destination=conn.destination,
    )
    with pytest.raises(SidebandError) as e:
        validate_sidebands([_out(), _in()], [bad], agent_universe=AGENTS)
    assert "ghost" in str(e.value)
    assert "not in the agent universe" in str(e.value)


def test_source_must_be_output():
    src = _out(direction="input", id="irq_out")
    with pytest.raises(SidebandError) as e:
        validate_sidebands([src, _in()], [_conn()],
                           agent_universe=AGENTS)
    assert "source port must be OUTPUT" in str(e.value)


def test_destination_must_be_input():
    dst = _in(direction="output", id="irq_in")
    with pytest.raises(SidebandError) as e:
        validate_sidebands([_out(), dst], [_conn()],
                           agent_universe=AGENTS)
    assert "destination port must be INPUT" in str(e.value)


def test_width_mismatch_refuses():
    src = _out(width_bits=1, id="irq_out")
    dst = _in(width_bits=8, id="irq_in")
    with pytest.raises(SidebandError) as e:
        validate_sidebands([src, dst], [_conn()],
                           agent_universe=AGENTS)
    assert "width mismatch" in str(e.value)


def test_kind_mismatch_refuses():
    src = _out(kind="error", id="irq_out")
    with pytest.raises(SidebandError) as e:
        validate_sidebands([src, _in()], [_conn()],
                           agent_universe=AGENTS)
    assert "kind mismatch" in str(e.value)


def test_duplicate_interface_id_refuses():
    with pytest.raises(SidebandError) as e:
        validate_sidebands([_out(), _out()], [_conn()],
                           agent_universe=AGENTS)
    assert "duplicate sideband interface id" in str(e.value)


def test_duplicate_connection_id_refuses():
    with pytest.raises(SidebandError) as e:
        validate_sidebands([_out(), _in()], [_conn(), _conn()],
                           agent_universe=AGENTS)
    assert "duplicate sideband connection id" in str(e.value)


def test_duplicate_agent_in_universe_refuses():
    with pytest.raises(SidebandError) as e:
        validate_sidebands([_out(), _in()], [_conn()],
                           agent_universe=("tile0", "tile0"))
    assert "duplicate agent" in str(e.value)


def test_non_sideband_interface_in_list_refuses():
    with pytest.raises(SidebandError) as e:
        validate_sidebands(["irq_out"], [_conn()], agent_universe=AGENTS)
    assert "SidebandInterface" in str(e.value)


def test_empty_agent_universe_refuses_any_connection():
    with pytest.raises(SidebandError):
        validate_sidebands([_out(), _in()], [_conn()], agent_universe=())


# --------------------------------------------------------------------------
# clock crossing is DERIVED and FLAGGED, never resolved here
# --------------------------------------------------------------------------

def test_crossing_flagged_true_when_domains_differ():
    src = _out(clock_domain="clk_a")
    dst = _in(clock_domain="clk_b")
    assert _conn().requires_clock_crossing([src, dst]) is True


def test_crossing_flagged_false_when_domains_match():
    assert _conn().requires_clock_crossing([_out(), _in()]) is False


def test_crossing_is_unknown_not_false_when_domain_undeclared():
    src = _out(clock_domain=None)
    dst = _in(clock_domain="clk_b")
    assert _conn().requires_clock_crossing([src, dst]) is None


def test_crossing_is_unknown_when_interface_undeclared():
    assert _conn().requires_clock_crossing([]) is None


def test_module_exposes_no_crossing_mechanism():
    """The sideband model must not gain a synchronizer/FIFO/2FF field: that
    authority belongs to domain_intent, and duplicating it would fork one
    fact into two."""
    import veritx_dse.model.sideband as mod
    import inspect
    names = [n for n in dir(mod)
             if any(t in n.lower() for t in
                    ("synchron", "fifo", "sync_2ff", "sync_3ff", "2ff"))]
    assert names == [], names
    fields = {f for f in SidebandInterface.__dataclass_fields__}
    assert not any("sync" in f or "fifo" in f for f in fields), fields


def test_connection_is_its_own_edge_not_a_data_plane_payload():
    """No VC / traffic-class / route field on a sideband edge."""
    fields = set(SidebandConnection.__dataclass_fields__)
    assert not ({"vc", "traffic_class", "route", "hop", "flit"} & fields)


def test_validate_returns_none():
    assert validate_sidebands([_out(), _in()], [_conn()],
                              agent_universe=AGENTS) is None

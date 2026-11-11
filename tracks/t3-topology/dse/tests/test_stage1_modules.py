"""STAGE 1 deep modules M1–M4: narrow functions, frozen in, Verdict out.

Module-isolation contract (§8.3): none of the four modules imports
``CompileRequestV4`` or ``topology_intent`` (static import-lint), and every
check is pure (same input struct twice -> identical Verdict).
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from veritx_dse.model.agent_intent_v4 import (
    AgentIntentV4, OrderingMode, PermissionWindow, ProtocolFamily,
    TrafficClassVC,
)
from veritx_dse.model.compile_model import (
    AddressRange, AgentKind, Dependency, DependencyGraph, DepKind,
)

_MODULES = [
    "veritx_dse.model.address_permission",
    "veritx_dse.model.ordering_vc",
    "veritx_dse.model.clock_power_cdc",
    "veritx_dse.model.protocol_adapter",
]

_FORBIDDEN = ("compile_request_v4", "topology_intent")


def test_modules_do_not_import_request_or_topology():
    for dotted in _MODULES:
        module = importlib.import_module(dotted)
        tree = ast.parse(Path(module.__file__).read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
            elif isinstance(node, ast.Import):
                imports.extend(a.name for a in node.names)
        for banned in _FORBIDDEN:
            assert not any(banned in name for name in imports), (
                f"{dotted} imports banned {banned}: {imports}")


def _range(name, base, size, group=0, **kwargs):
    return AddressRange(name=name, base=base, size=size,
                        target_agent_idx=group, **kwargs)


# --- M1: address_permission ---------------------------------------------

def _m1(ranges, windows=(), counts=(4,), traffic=()):
    from veritx_dse.model.address_permission import AddressPermissionInput
    return AddressPermissionInput(ranges=ranges, windows=windows,
                                  agent_counts=counts, traffic=traffic)


def test_m1_overlap_names_both_ranges():
    from veritx_dse.model.address_permission import check_address_permission
    verdict = check_address_permission(_m1((
        _range("A", 0x1000, 0x2000, target_instance_index=0,
               selection_policy="FIXED_INSTANCE"),
        _range("B", 0x2000, 0x1000, target_instance_index=0,
               selection_policy="FIXED_INSTANCE"))))
    assert verdict.ok is False
    assert verdict.status == "INVALID"
    assert "'A'" in verdict.reason and "'B'" in verdict.reason
    assert "overlap" in verdict.reason


def test_m1_multi_instance_without_selection_is_invalid():
    from veritx_dse.model.address_permission import check_address_permission
    verdict = check_address_permission(_m1((_range("A", 0x1000, 0x1000),)))
    assert verdict.ok is False and "FIXED_INSTANCE or STRIPED" in verdict.reason


def test_m1_unknown_and_duplicate_windows_are_invalid():
    from veritx_dse.model.address_permission import check_address_permission
    ok_range = (_range("A", 0x1000, 0x1000, target_instance_index=0,
                       selection_policy="FIXED_INSTANCE"),)
    unknown = check_address_permission(_m1(
        ok_range, windows=(PermissionWindow("NOPE"),)))
    assert unknown.ok is False and "unknown address range" in unknown.reason
    duplicate = check_address_permission(_m1(
        ok_range, windows=(PermissionWindow("A", True, False),
                           PermissionWindow("A", True, True))))
    assert duplicate.ok is False and "more than once" in duplicate.reason


def test_m1_write_to_readonly_window_is_invalid():
    from veritx_dse.model.address_permission import (
        TrafficRequirement, check_address_permission,
    )
    ranges = (_range("A", 0x1000, 0x1000, target_instance_index=0,
                     selection_policy="FIXED_INSTANCE"),)
    write = check_address_permission(_m1(
        ranges, windows=(PermissionWindow("A", readable=True, writable=False),),
        traffic=(TrafficRequirement("write", is_write=True, is_read=False),)))
    assert write.ok is False and "read-only" in write.reason
    # Same window, no write traffic: fine.
    read_only_traffic = check_address_permission(_m1(
        ranges, windows=(PermissionWindow("A", readable=True, writable=False),),
        traffic=(TrafficRequirement("read", is_write=False, is_read=True),)))
    assert read_only_traffic.ok is True
    # Open window, any traffic: fine. No windows, any traffic: fine.
    open_window = check_address_permission(_m1(
        ranges, windows=(PermissionWindow("A", True, True),),
        traffic=(TrafficRequirement("write", True, False),
                 TrafficRequirement("x", True, True))))
    assert open_window.ok is True
    no_windows = check_address_permission(_m1(
        ranges, traffic=(TrafficRequirement("write", True, False),)))
    assert no_windows.ok is True


def test_m1_pure_and_projection_sorted():
    from veritx_dse.model.address_permission import (
        build_decode_entries, check_address_permission,
    )
    inp = _m1((_range("B", 0x9000, 0x1000, target_instance_index=0,
                      selection_policy="FIXED_INSTANCE"),
               _range("A", 0x1000, 0x1000, target_instance_index=0,
                      selection_policy="FIXED_INSTANCE")))
    assert check_address_permission(inp) == check_address_permission(inp)
    rows = build_decode_entries(inp)
    assert [row.name for row in rows] == ["A", "B"]
    assert rows[0].base == 0x1000


# --- M2: ordering_vc -----------------------------------------------------

def _m2(desired, derived_count, derived_map, graph=None):
    from veritx_dse.model.ordering_vc import OrderingVCInput
    return OrderingVCInput(
        graph=graph or DependencyGraph(()),
        desired=desired,
        derived_vc_count=derived_count,
        derived_per_class_vc=tuple(sorted(derived_map.items())))


def test_m2_desired_at_or_above_derived_is_invalid():
    from veritx_dse.model.ordering_vc import check_ordering_vc
    verdict = check_ordering_vc(_m2(
        (TrafficClassVC("data", 3),), 1, {"data": 0}))
    assert verdict.ok is False and verdict.status == "INVALID"
    assert "only 1 VC" in verdict.reason


def test_m2_mismatch_is_invalid_never_override():
    from veritx_dse.model.ordering_vc import check_ordering_vc
    verdict = check_ordering_vc(_m2(
        (TrafficClassVC("data", 0),), 3, {"data": 2}))
    assert verdict.ok is False and "binds it to VC 2" in verdict.reason


def test_m2_unknown_class_is_invalid():
    from veritx_dse.model.ordering_vc import check_ordering_vc
    verdict = check_ordering_vc(_m2(
        (TrafficClassVC("nope", 0),), 1, {"data": 0}))
    assert verdict.ok is False and "not in the derived assignment" in verdict.reason


def test_m2_match_and_empty_are_ok():
    from veritx_dse.model.ordering_vc import check_ordering_vc
    assert check_ordering_vc(_m2(
        (TrafficClassVC("data", 2),), 3, {"data": 2})).ok is True
    assert check_ordering_vc(_m2((), 1, {})).ok is True


def test_m2_derived_count_above_max_is_invalid():
    from veritx_dse.model.ordering_vc import check_ordering_vc
    verdict = check_ordering_vc(_m2((), 17, {}))
    assert verdict.ok is False and "PLANE_C_MAX_VC" in verdict.reason


# --- M3: clock_power_cdc -------------------------------------------------

def _m3(endpoints, crossings=(), num_power=1, agents=()):
    from veritx_dse.model.clock_power_cdc import ClockPowerInput
    return ClockPowerInput(endpoints=endpoints, crossings=crossings,
                           num_power_domains=num_power, agents=agents)


def test_m3_intent_domain_must_match_agent():
    from veritx_dse.model.clock_power_cdc import (
        EndpointDomain, check_clock_power_cdc,
    )
    verdict = check_clock_power_cdc(_m3((
        EndpointDomain(0, "noc_clk", "pd0", "other_clk", None),)))
    assert verdict.ok is False and verdict.status == "INVALID"
    assert "must exist and equal" in verdict.reason


def test_m3_multi_domain_is_unsupported_with_named_points():
    from veritx_dse.model.clock_power_cdc import (
        EndpointDomain, check_clock_power_cdc, cdc_insertion_points,
    )
    inp = _m3((
        EndpointDomain(0, "a", None, None, None),
        EndpointDomain(1, "b", None, None, None),
        EndpointDomain(2, "a", None, None, None)))
    verdict = check_clock_power_cdc(inp)
    assert verdict.ok is False and verdict.status == "UNSUPPORTED"
    assert "CDC insertion points" in verdict.reason
    points = cdc_insertion_points(inp)
    assert points == verdict.findings
    assert any("group0(a)->group1(b)" in point for point in points)
    assert all(point.startswith("cdc:") for point in points)


def test_m3_same_domain_is_ok_and_power_shortage_warns():
    from veritx_dse.model.clock_power_cdc import (
        EndpointDomain, check_clock_power_cdc,
    )
    assert check_clock_power_cdc(_m3((
        EndpointDomain(0, "a", None, None, None),
        EndpointDomain(1, "a", None, None, None)))).ok is True
    warn = check_clock_power_cdc(_m3(
        (EndpointDomain(0, "a", "pd0", None, None),
         EndpointDomain(1, "a", "pd1", None, None)),
        num_power=1))
    assert warn.ok is True and warn.findings  # WARN, still compiles


# --- M4: protocol_adapter -------------------------------------------------

def _m4(intents):
    from veritx_dse.model.protocol_adapter import ProtocolInput
    return ProtocolInput(intents=intents, data_width=256, addr_width=64)


def test_m4_split_at_on_non_burst_family_is_invalid():
    from veritx_dse.model.protocol_adapter import check_protocol
    # CHI/TileLink size from DATA_W/SIZE, not split_at: split_at is
    # INVALID there (only axi5/custom implement a burst split).
    for family in (ProtocolFamily.CHI, ProtocolFamily.TILELINK):
        verdict = check_protocol(_m4((
            AgentIntentV4(0, protocol=family, split_at=64),)))
        assert verdict.ok is False and "only axi5" in verdict.reason
    # Custom with split_at is the declared burst param: legal.
    custom = check_protocol(_m4((
        AgentIntentV4(0, protocol=ProtocolFamily.CUSTOM, split_at=64),)))
    assert custom.ok is True
    # Bare custom without burst/ordering is INVALID (no hidden defaults).
    bare = check_protocol(_m4((
        AgentIntentV4(0, protocol=ProtocolFamily.CUSTOM),)))
    assert bare.ok is False and "burst" in bare.reason
    assert "ordering" in bare.reason
    # split_at with inherited (unknown) family cannot be honored either.
    verdict = check_protocol(_m4((AgentIntentV4(0, split_at=64),)))
    assert verdict.ok is False and "declare protocol 'axi5'" in verdict.reason


def test_m4_axi5_with_split_and_requirements():
    from veritx_dse.model.protocol_adapter import (
        adapter_requirements, check_protocol,
    )
    intent = AgentIntentV4(0, protocol=ProtocolFamily.AXI5, split_at=64,
                           max_outstanding=16, ordering=OrderingMode.STRONG)
    verdict = check_protocol(_m4((intent,)))
    assert verdict.ok is True and verdict.findings == ()
    rows = adapter_requirements(_m4((intent,)))
    assert "burst-split" in rows and "protocol-shim:axi5" in rows
    assert "outstanding-credit" in rows and "ordering:strong" in rows
    assert list(rows) == sorted(rows)


def test_m4_max_outstanding_without_ordering_warns():
    from veritx_dse.model.protocol_adapter import check_protocol
    verdict = check_protocol(_m4((AgentIntentV4(0, max_outstanding=16),)))
    assert verdict.ok is True and verdict.findings
    assert "no ordering promise is invented" in verdict.findings[0]


def test_m4_unknown_family_is_invalid():
    from veritx_dse.model.protocol_adapter import check_protocol
    intent = AgentIntentV4(0, protocol=ProtocolFamily.AXI5)
    # Bypass frozen __post_init__ to prove the module-level gate still
    # refuses a family outside the closed vocabulary (defense in depth
    # for programmatically built structs).
    object.__setattr__(intent, "protocol", "axi99")
    verdict = check_protocol(_m4((intent,)))
    assert verdict.ok is False and "unknown protocol family" in verdict.reason
    from veritx_dse.model.agent_intent_v4 import ProtocolFamily as PF
    with pytest.raises(ValueError, match="invalid protocol"):
        PF.parse("axi99")


def test_all_checks_are_pure():
    from veritx_dse.model.address_permission import check_address_permission
    from veritx_dse.model.clock_power_cdc import (
        EndpointDomain, check_clock_power_cdc,
    )
    from veritx_dse.model.ordering_vc import check_ordering_vc
    from veritx_dse.model.protocol_adapter import check_protocol
    m1 = _m1((_range("A", 0x1000, 0x1000, target_instance_index=0,
                     selection_policy="FIXED_INSTANCE"),))
    m2 = _m2((TrafficClassVC("data", 0),), 1, {"data": 0})
    # Build the M3 input with real agent refs for the purity probe.
    from veritx_dse.model.compile_model import Agent
    m3 = _m3((EndpointDomain(0, "a", None, None, None),),
             agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=1,
                           clock_domain="a"),))
    m4 = _m4((AgentIntentV4(0, protocol=ProtocolFamily.AXI5),))
    for check, inp in ((check_address_permission, m1),
                       (check_ordering_vc, m2),
                       (check_clock_power_cdc, m3),
                       (check_protocol, m4)):
        assert check(inp) == check(inp)

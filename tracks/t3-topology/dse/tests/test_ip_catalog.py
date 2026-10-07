"""IP primitive catalog (§27/§48): server-owned templates, no invented PPA.

The catalog is data the product renders, so the tests below are really
contract tests on what a client is allowed to be shown:

- every required primitive is PRESENT even when its semantics are unsupported,
  and it carries the capability id that gates it (§27);
- area/power are never numeric, because nothing here has a PDK artifact
  behind it (§27/§35/§89);
- agent kinds come from the closed five-member AgentKind set, and any
  substitution is recorded in provenance rather than silently made;
- unknown fields and unknown enum values refuse at the boundary.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.model.compile_model import AgentKind  # noqa: E402
from veritx_dse.model.ip_catalog import (  # noqa: E402
    IP_CATALOG,
    NOT_PROVIDED,
    InterfaceRole,
    IpCatalogError,
    IpCategory,
    IpTemplate,
    get_ip_template,
    list_ip_templates,
)

REQUIRED_IDS = (
    "npu-tensor-core",
    "vector-coprocessor",
    "streaming-dma-engine",
    "telemetry-atb-trace-hub",
    "csr-config-controller",
    "cdc-async-fifo-bridge",
    "pipeline-retiming-stage",
    "rcu-collective",
    "ucie-d2d-chiplet",
    "concentrated-router",
    "hbm3e-memory",
    "pcie-cxl-root",
)


def _template(**over):
    base = dict(
        id="unit-primitive",
        version="1.0",
        category=IpCategory.COMPUTE,
        agent_kind=AgentKind.COMPUTE_TILE,
        interface_role=InterfaceRole.INITIATOR,
        protocol="AXI",
        data_width_bits=256,
        address_width_bits=64,
        requires_clock_domain=True,
        requires_power_domain=False,
        port_count=1,
        capability_requirements=(),
        provenance="unit test template",
    )
    base.update(over)
    return IpTemplate(**base)


# ---------------------------------------------------------------- catalog ----

def test_every_required_primitive_is_present():
    ids = tuple(t.id for t in IP_CATALOG)
    for required in REQUIRED_IDS:
        assert required in ids, f"missing catalog entry {required!r}"


def test_get_ip_template_returns_it():
    for required in REQUIRED_IDS:
        assert get_ip_template(required).id == required


def test_unknown_template_id_refuses_with_known_list():
    with pytest.raises(IpCatalogError) as exc:
        get_ip_template("does-not-exist")
    assert "unknown IP catalog template" in str(exc.value)
    assert "npu-tensor-core" in str(exc.value)


def test_ids_have_no_whitespace():
    for t in IP_CATALOG:
        assert not any(ch.isspace() for ch in t.id)


def test_list_ip_templates_filters_by_category_and_value():
    compute = list_ip_templates(IpCategory.COMPUTE)
    assert compute == list_ip_templates("compute")
    assert all(t.category is IpCategory.COMPUTE for t in compute)
    assert {t.id for t in compute} >= {"npu-tensor-core", "rcu-collective"}
    assert len(list_ip_templates(None)) == len(IP_CATALOG)


def test_unknown_category_refuses():
    with pytest.raises(IpCatalogError) as exc:
        list_ip_templates("chiplets")
    assert "chiplets" in str(exc.value)


# ------------------------------------------------------------ agent kinds ----

def test_agent_kinds_come_from_the_closed_set_only():
    closed = {m.value for m in AgentKind}
    assert closed == {"compute_tile", "hbm_controller", "nic",
                      "peripheral", "ucie_port"}
    for t in IP_CATALOG:
        assert isinstance(t.agent_kind, AgentKind)


def test_substituted_kinds_explain_the_mapping_in_provenance():
    # These primitives have NO matching AgentKind, so a mapping must be
    # stated rather than implied.
    for tid in ("npu-tensor-core", "streaming-dma-engine",
                "concentrated-router", "pcie-cxl-root", "rcu-collective"):
        t = get_ip_template(tid)
        assert "AgentKind" in t.provenance, tid
        assert t.provenance.endswith("."), tid


def test_direct_match_does_not_pretend_to_be_a_substitution():
    hbm = get_ip_template("hbm3e-memory")
    assert hbm.agent_kind is AgentKind.HBM_CONTROLLER
    assert "direct match" in hbm.provenance
    ucie = get_ip_template("ucie-d2d-chiplet")
    assert ucie.agent_kind is AgentKind.UCIE_PORT


# ------------------------------------------------------- no invented PPA ----

def test_no_entry_carries_a_numeric_area_or_power():
    for t in IP_CATALOG:
        d = t.to_dict()
        assert d["area_mm2"] == NOT_PROVIDED, t.id
        assert d["power_w"] == NOT_PROVIDED, t.id
        assert isinstance(d["area_mm2"], str)
        assert isinstance(d["power_w"], str)


def test_absent_physical_fields_roundtrip_to_none():
    for t in IP_CATALOG:
        assert t.area_mm2 is None, t.id
        assert t.power_w is None, t.id
        assert IpTemplate.from_dict(t.to_dict()) == t


@pytest.mark.parametrize("field", ["area_mm2", "power_w"])
@pytest.mark.parametrize("value", [45, 6.5, 0, True])
def test_numeric_area_or_power_is_refused(field, value):
    with pytest.raises(IpCatalogError) as exc:
        _template(**{field: value})
    msg = str(exc.value)
    assert "must not carry a numeric value" in msg
    assert "PDK" in msg


def test_unrecognised_physical_string_refuses():
    with pytest.raises(IpCatalogError) as exc:
        _template(area_mm2="7.8 mm2")
    assert NOT_PROVIDED in str(exc.value)


def test_not_provided_string_is_accepted_and_normalized_to_none():
    # The wire spelling "NOT PROVIDED" is a valid authoring value and is
    # normalized to None in memory, so construction and documents agree.
    t = _template(area_mm2=NOT_PROVIDED, power_w=NOT_PROVIDED)
    assert t.area_mm2 is None
    assert t.power_w is None
    assert t.to_dict()["area_mm2"] == NOT_PROVIDED


# ---------------------------------------------------------- gating rows ----

def test_unsupported_semantics_are_listed_not_omitted():
    """Every gated primitive must name the capability that gates it."""
    gated = {
        "npu-tensor-core": ("workload.compute_architecture",),
        "vector-coprocessor": ("workload.compute_architecture",),
        "streaming-dma-engine": ("transaction.outstanding",
                                 "transaction.splitting"),
        "telemetry-atb-trace-hub": ("sideband.interface",),
        "csr-config-controller": ("fabric.multiplane",
                                  "sideband.connectivity"),
        "cdc-async-fifo-bridge": ("cdc.async_fifo", "cdc.crossing"),
        "pipeline-retiming-stage": ("generate.rtl",),
        "rcu-collective": ("router.rcu",),
        "ucie-d2d-chiplet": ("agent.interface", "cdc.crossing"),
        "concentrated-router": ("router.concentration",
                                "router.vc_allocation"),
        "hbm3e-memory": ("address.decode",),
        "pcie-cxl-root": ("address.decode", "sideband.interface"),
    }
    assert set(gated) == set(REQUIRED_IDS)
    for tid, reqs in gated.items():
        t = get_ip_template(tid)
        assert t.capability_requirements == tuple(sorted(reqs)), tid
        assert t.stampable_now is False, tid
        assert all(r for r in t.capability_requirements), tid


def test_stampable_now_is_true_only_with_no_requirements():
    assert _template().stampable_now is True
    assert _template(capability_requirements=("cdc.crossing",)).stampable_now \
        is False


def test_rcu_row_records_the_removed_v4_realization():
    rcu = get_ip_template("rcu-collective")
    assert "ROUTE-011" in rcu.provenance
    assert "FUTURE_CONTRACT" in rcu.provenance
    assert "REMOVED from v4" in rcu.provenance


def test_concentrated_router_ports_cite_the_canonical_default():
    r = get_ip_template("concentrated-router")
    assert r.port_count == 4
    assert "V3_CONCENTRATED_MESH_DEFAULT_CONCENTRATION" in r.provenance


# -------------------------------------------------------------- laws --------

def test_port_count_must_be_positive():
    with pytest.raises(IpCatalogError) as exc:
        _template(port_count=0)
    assert ">= 1" in str(exc.value)


@pytest.mark.parametrize("width", [0, 4, 2, True])
def test_widths_must_be_ints_at_least_8(width):
    with pytest.raises(IpCatalogError):
        _template(data_width_bits=width)


def test_non_bool_domain_flags_refuse():
    with pytest.raises(IpCatalogError) as exc:
        _template(requires_clock_domain=1)
    assert "must be a bool" in str(exc.value)


def test_empty_provenance_refuses():
    with pytest.raises(IpCatalogError):
        _template(provenance="")


def test_capability_requirements_are_canonical_sorted_unique():
    t = _template(capability_requirements=("z.cap", "a.cap"))
    assert t.capability_requirements == ("a.cap", "z.cap")
    with pytest.raises(IpCatalogError) as exc:
        _template(capability_requirements=("a.cap", "a.cap"))
    assert "duplicates" in str(exc.value)


def test_template_is_frozen():
    t = _template()
    with pytest.raises(Exception):
        t.id = "other"          # type: ignore[misc]


# ------------------------------------------------------ enum vocabulary -----

def test_interface_role_vocabulary_is_exactly_the_defined_set():
    assert tuple(m.name for m in InterfaceRole) == (
        "INITIATOR", "TARGET", "BIDIRECTIONAL", "STREAM_SOURCE",
        "STREAM_SINK",
    )


def test_category_vocabulary_is_exactly_the_defined_set():
    assert tuple(m.value for m in IpCategory) == (
        "compute", "memory", "network", "bridge", "support",
    )


def test_stream_roles_are_the_no_completion_tracking_roles():
    assert InterfaceRole.STREAM_SINK.value == "STREAM_SINK"
    assert InterfaceRole.STREAM_SOURCE.value == "STREAM_SOURCE"
    assert InterfaceRole.STREAM_SINK in {m for m in InterfaceRole}


def test_unknown_enum_values_refuse():
    with pytest.raises(IpCatalogError) as exc:
        _template(interface_role="MASTER")
    assert "MASTER" in str(exc.value)
    with pytest.raises(IpCatalogError):
        _template(category="interconnect")
    with pytest.raises(IpCatalogError):
        _template(agent_kind="npu")


# ------------------------------------------------------- roundtrip ----------

def test_every_catalog_entry_roundtrips():
    for t in IP_CATALOG:
        assert IpTemplate.from_dict(t.to_dict()) == t


def test_unknown_field_refuses_on_from_dict():
    d = _template().to_dict()
    d["vendor"] = "acme"
    with pytest.raises(IpCatalogError) as exc:
        IpTemplate.from_dict(d)
    assert "unknown fields" in str(exc.value)
    assert "vendor" in str(exc.value)


def test_missing_required_field_refuses():
    d = _template().to_dict()
    del d["provenance"]
    with pytest.raises(IpCatalogError) as exc:
        IpTemplate.from_dict(d)
    assert "provenance" in str(exc.value)


def test_non_object_refuses():
    with pytest.raises(IpCatalogError) as exc:
        IpTemplate.from_dict(["npu-tensor-core"])
    assert "must be an object" in str(exc.value)


def test_capability_requirements_must_be_a_list_in_dict():
    d = _template().to_dict()
    d["capability_requirements"] = "cdc.crossing"
    with pytest.raises(IpCatalogError) as exc:
        IpTemplate.from_dict(d)
    assert "must be a list" in str(exc.value)


def test_to_dict_carries_every_contract_field():
    expected = {
        "id", "version", "category", "agent_kind", "interface_role",
        "protocol", "data_width_bits", "address_width_bits",
        "requires_clock_domain", "requires_power_domain", "port_count",
        "capability_requirements", "provenance", "area_mm2", "power_w",
    }
    assert set(_template().to_dict()) == expected

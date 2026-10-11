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

from veritx_dse.core.errors import UnsupportedSemantics  # noqa: E402
from veritx_dse.model.compile_model import AgentKind  # noqa: E402
from veritx_dse.model.domain_intent import PowerDomain, PowerPolicy  # noqa: E402
from veritx_dse.model.ip_catalog import (  # noqa: E402
    IP_CATALOG,
    NOT_PROVIDED,
    InterfaceRole,
    IpCatalogError,
    IpCategory,
    IpTemplate,
    get_ip_template,
    list_ip_templates,
    stamp_ip_template,
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


def test_unsupported_stampable_row_has_no_consumer():
    with pytest.raises(UnsupportedSemantics, match="no canonical instance materializer"):
        stamp_ip_template(_template())


def test_stamping_a_gated_template_names_the_unmet_requirement():
    with pytest.raises(UnsupportedSemantics) as exc:
        stamp_ip_template("npu-tensor-core")
    msg = str(exc.value)
    assert "workload.compute_architecture" in msg
    assert "no matching materializer" in msg


def test_unimplemented_catalog_templates_remain_gated():
    for template in IP_CATALOG:
        if template.id == "hbm3e-memory":
            continue
        with pytest.raises(UnsupportedSemantics) as exc:
            stamp_ip_template(template)
        for requirement in template.capability_requirements:
            assert requirement in str(exc.value), template.id


def test_stamping_accepts_an_id_or_a_template_and_refuses_unknown_ids():
    with pytest.raises(IpCatalogError):
        stamp_ip_template("does-not-exist")
    with pytest.raises(IpCatalogError):
        stamp_ip_template(123)      # type: ignore[arg-type]
    for target in ("npu-tensor-core", get_ip_template("npu-tensor-core")):
        with pytest.raises(UnsupportedSemantics):
            stamp_ip_template(target)


def test_hbm3e_stamp_materializes_and_consumes_real_endpoint_read_write():
    import json
    from dataclasses import replace
    from pathlib import Path

    from veritx_dse.application.data_movement import execute_data_movement
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.application.tensor_demand import (
        RemoteDemandPolicy, project_remote_tensor_demand,
    )
    from veritx_dse.core.artifact import canonical_bytes
    from veritx_dse.model.access_policy import AddressSpace
    from veritx_dse.model.compile_request_v5 import CompileRequestV5
    from veritx_dse.model.physical_placement import PhysicalPlacement
    from veritx_dse.model.tensor_demand import (
        Tensor, TensorAccess, TensorDemandWorkload, TensorShard,
    )
    from veritx_dse.model.transaction_intent import TransactionKind
    from veritx_dse.workload.tensor_demand import lower_tensor_demand

    example = Path(__file__).resolve().parents[1] / "examples/tensor_demand_v5.json"
    doc = json.loads(example.read_text())
    original = CompileRequestV5.from_dict(doc["design"])
    expanded_topology = replace(original.base_v4.topology, concentration=2)
    original = replace(original, base_v4=replace(original.base_v4,
                                                  topology=expanded_topology))
    stamped = stamp_ip_template(
        "hbm3e-memory", original, instance_id="mem0",
        address_base=0xA000, address_size=16,
        clock_domain="network", power_domain="DEFAULT",
        initiator_group_index=0, access_permission="RW")
    assert isinstance(stamped, CompileRequestV5)
    assert stamped.design_hash() != original.design_hash()
    assert len(stamped.base_v4.agents) == len(original.base_v4.agents) + 1
    agent = stamped.base_v4.agents[-1]
    assert (agent.ip_template_id, agent.ip_template_version,
            agent.ip_instance_id) == ("hbm3e-memory", "1.0", "mem0")
    assert (agent.kind, agent.data_width, agent.addr_width, agent.protocol,
            agent.clock_domain, agent.power_domain) == (
                AgentKind.HBM_CONTROLLER, 256, 64, "AXI", "network", "DEFAULT")
    loaded = CompileRequestV5.from_dict(json.loads(json.dumps(stamped.to_dict())))
    assert canonical_bytes(loaded.to_dict()) == canonical_bytes(stamped.to_dict())
    assert loaded.design_hash() == stamped.design_hash()

    compilation = FabricCompiler().compile(loaded)
    assert compilation.status == "COMPILED", compilation.error
    root = compilation.compiled_system
    root.revalidate()
    group_index = len(loaded.base_v4.agents) - 1
    endpoint = next(e for e in root.fabric.attachment.endpoints
                    if e.agent.group_index == group_index)
    entry = next(e for e in root.fabric.address_decode.entries
                 if e.target_agent_group == group_index)
    assert (entry.base, entry.size, entry.target_endpoint_id) == (
        0xA000, 16, endpoint.endpoint_id)
    assert endpoint.agent.kind is AgentKind.HBM_CONTROLLER
    assert (endpoint.interface.data_width_bits,
            endpoint.interface.address_width_bits,
            endpoint.interface.protocol, endpoint.interface.clock_domain,
            endpoint.interface.power_domain) == (
                256, 64, "AXI", "network", "DEFAULT")
    assert root.fabric.address_decode.select_endpoint(0xA000) == endpoint.endpoint_id

    workload = TensorDemandWorkload(
        design_hash=loaded.design_hash(), system_hash=root.system_hash(),
        tensors=(Tensor("ip-window", 1, 16, 16, (TensorShard(
            "mem0-window", 0, 16, endpoint.endpoint_id,
            AddressSpace.GLOBAL, 0xA000, 16),)),),
        accesses=(
            TensorAccess("read", "ip-window", 0, TransactionKind.READ,
                         0, 16, 1, 16, (), "BYPASS"),
            TensorAccess("write", "ip-window", 0, TransactionKind.WRITE,
                         0, 16, 1, 16, ("read",), "BYPASS"),
        ))
    lowered = lower_tensor_demand(compilation, workload)
    assert lowered.audit["read_bytes"] == lowered.audit["write_bytes"] == 16
    assert [
        (r.kind, r.transaction_address, r.transaction_bytes,
         r.payload_address, r.payload_bytes, r.target)
        for r in lowered.requests
    ] == [
        ("READ", 0xA000, 16, 0xA000, 16, endpoint.endpoint_id),
        ("WRITE", 0xA000, 16, 0xA000, 16, endpoint.endpoint_id),
    ]
    policy = RemoteDemandPolicy.from_dict(doc["transport"])
    remote = project_remote_tensor_demand(compilation, workload, policy)
    placement = PhysicalPlacement.from_dict(doc["placement"])
    placement = replace(placement,
                        resource_graph_id=root.resource_graph.artifact_id())
    evidence = execute_data_movement(compilation, remote.workload,
                                     placement).to_dict()
    assert evidence["summary"]["payload_bytes"] == 32
    assert evidence["summary"]["children_completed"] == 2
    assert [
        (row["kind"], row["child"]["address_start"],
         row["child"]["address_end"], row["child"]["byte_length"],
         row["target"])
        for row in evidence["children"]
    ] == [
        ("READ", 0xA000, 0xA010, 16, endpoint.endpoint_id),
        ("WRITE", 0xA000, 0xA010, 16, endpoint.endpoint_id),
    ]
    assert evidence["scope"]["memory_contents_modeled"] is False
    assert evidence["scope"]["booksim_equivalent"] is False
    assert evidence["scope"]["signoff_verified"] is False


def test_hbm3e_stamp_accepts_declared_unassigned_v5_power_domain():
    import json
    from dataclasses import replace
    from pathlib import Path

    from veritx_dse.model.compile_request_v5 import CompileRequestV5

    example = Path(__file__).resolve().parents[1] / "examples/tensor_demand_v5.json"
    design = CompileRequestV5.from_dict(json.loads(example.read_text())["design"])
    declared = PowerDomain("MEMORY", PowerPolicy.ALWAYS_ON)
    design = replace(design, power_domains=(declared,))
    stamped = stamp_ip_template(
        "hbm3e-memory", design, instance_id="memory0",
        address_base=0xA000, address_size=16,
        clock_domain="network", power_domain="MEMORY",
        initiator_group_index=0, access_permission="RW")

    assert stamped.power_domains == (declared,)
    assert stamped.base_v4.agents[-1].power_domain == "MEMORY"


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

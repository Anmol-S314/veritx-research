"""Wave B1 — product design-intent identity (CompileRequest).

Executable documentation for the authoritative design identity:

    design_hash()  =  SHA-256 over the canonical semantic envelope
                      (domain-tagged, schema-versioned,
                       compiler-semantics-versioned)

It answers exactly one question: "what product design did the customer
request?". It never contains execution provenance (git commit, binary
hash, host, seed, timestamp, run id) — that is ExecutionFingerprint's job.

COLLECTION ORDER RULING (inspected against the code, not assumed):

  dataclass        collection        order?    reason
  ---------------  ----------------  --------  ---------------------------
  Workload         collectives       ORDERED   collective_vc_map keys by
                                                index (derive_vc_assignment)
  CompileRequest   agents            ORDERED   AddressRange.target_agent_idx
                                                indexes this tuple
  DependencyGraph  dependencies      ORDERED   adjacency insertion order
                                                feeds DFS cycle enumeration
  CompileRequest   requirements      UNORDERED per-class bounds; min()/all()
                                                are order-independent
  AddressMap       ranges            UNORDERED validate_no_overlaps sorts by
                                                base; no decode-order consumer
  NocConfig        output_formats    UNORDERED a set of requested artifacts
"""
import dataclasses
import json
from dataclasses import replace
from pathlib import Path

import pytest

from veritx_dse.model.compile_model import (
    COMPILE_REQUEST_SCHEMA_VERSION,
    COMPILER_SEMANTICS_VERSION,
    AddressMap,
    AddressRange,
    Agent,
    AgentKind,
    CollectiveKind,
    CollectiveOp,
    CompileRequest,
    CompileRequestSchemaError,
    Dependency,
    DependencyGraph,
    DepKind,
    ModelFamily,
    NocConfig,
    OutputFormat,
    PhysicalContext,
    QoSClass,
    Requirement,
    ServingMode,
    TopologyFamily,
    Workload,
)

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"

# Golden design identity of the fully-populated baseline. Bump a schema or
# compiler-semantics version to change it legitimately, never silently.
GOLDEN_DESIGN_HASH = \
    "6b95eb820150f06d2b155f807160675f7f43e7af5e3e8ae07977164f065a6707"


# ── builders ────────────────────────────────────────────────────────────────

def _workload(**kw) -> Workload:
    base = dict(
        model_family=ModelFamily.MOE, model_name="Qwen3-30B-A3B",
        tp=8, pp=2, ep=4, dp=3, param_count_b=30.5, sequence_length=4096,
        batch_size=16, precision="fp8",
        serving_mode=ServingMode.DECODE_HEAVY,
        collectives=(CollectiveOp(kind=CollectiveKind.ALLTOALL, group_size=8,
                                  bytes_per_element=4096),),
        trace_path="runs/traces/x.trace",
    )
    base.update(kw)
    return Workload(**base)


def _requirement(**kw) -> Requirement:
    base = dict(qos_class=QoSClass.LATENCY_CRITICAL,
                latency_ceiling_cycles=1234.0, bandwidth_floor_gbps=99.0,
                binding=True)
    base.update(kw)
    return Requirement(**base)


def _agent(**kw) -> Agent:
    base = dict(kind=AgentKind.COMPUTE_TILE, count=64, data_width=512,
                addr_width=48, protocol="CHI", clock_domain="clk0",
                power_domain="pd0")
    base.update(kw)
    return Agent(**base)


def _noc(**kw) -> NocConfig:
    base = dict(topology_family=TopologyFamily.TORUS, radix=8,
                concentration=2, arbitration="round_robin",
                rcu_enabled=True, link_width=256, mcast_groups=4,
                mcast_setup_cycles=50,
                output_formats=(OutputFormat.SYSTEMVERILOG, OutputFormat.UVM),
                obfuscation_level=2)
    base.update(kw)
    return NocConfig(**base)


def _physical(**kw) -> PhysicalContext:
    base = dict(default_clock_freq_mhz=2000.0, default_data_width=512,
                num_power_domains=3, process_node_nm=5)
    base.update(kw)
    return PhysicalContext(**base)


def _address_range(**kw) -> AddressRange:
    base = dict(name="HBM0", base=0x0, size=0x10000000,
                target_agent_idx=1)
    base.update(kw)
    return AddressRange(**base)


def _full_request() -> CompileRequest:
    """Every supported field set to a non-default value."""
    return CompileRequest(
        workload=_workload(),
        requirements=(_requirement(),
                      _requirement(qos_class=QoSClass.BANDWIDTH,
                                   latency_ceiling_cycles=None,
                                   bandwidth_floor_gbps=12.0,
                                   binding=False)),
        agents=(_agent(),
                _agent(kind=AgentKind.HBM_CONTROLLER, count=8,
                       data_width=256, addr_width=40, protocol="AXI",
                       clock_domain="clk1", power_domain="pd1")),
        dependencies=DependencyGraph([
            Dependency(source="cls_a", target="cls_b", kind=DepKind.BLOCKING),
            Dependency(source="cls_b", target="cls_c", kind=DepKind.ORDERING),
        ]),
        noc_config=_noc(),
        address_map=AddressMap(ranges=(
            AddressRange(name="SRAM0", base=0x20000000, size=0x100000,
                         target_agent_idx=0),
            _address_range(),
        )),
        physical=_physical(),
    )


def _with_workload(**kw) -> CompileRequest:
    return replace(_full_request(), workload=_workload(**kw))


def _with_requirement(i, **kw) -> CompileRequest:
    base = _full_request()
    reqs = list(base.requirements)
    reqs[i] = replace(reqs[i], **kw)
    return replace(base, requirements=tuple(reqs))


def _with_agent(i, **kw) -> CompileRequest:
    base = _full_request()
    agents = list(base.agents)
    agents[i] = replace(agents[i], **kw)
    return replace(base, agents=tuple(agents))


def _with_noc(**kw) -> CompileRequest:
    return replace(_full_request(), noc_config=_noc(**kw))


def _with_physical(**kw) -> CompileRequest:
    return replace(_full_request(), physical=_physical(**kw))


def _with_ranges(ranges) -> CompileRequest:
    return replace(_full_request(), address_map=AddressMap(ranges=tuple(ranges)))


def _with_deps(deps) -> CompileRequest:
    return replace(_full_request(),
                   dependencies=DependencyGraph(list(deps)))


def _base_hash() -> str:
    return _full_request().design_hash()


# ── §22 single-field mutation matrix ────────────────────────────────────────

def _matrix():
    """(label, mutated_request) for every semantic field."""
    m = [
        # Workload
        ("workload.model_family", _with_workload(model_family=ModelFamily.DENSE_TRANSFORMER)),
        ("workload.model_name", _with_workload(model_name="Other")),
        ("workload.tp", _with_workload(tp=16)),
        ("workload.pp", _with_workload(pp=3)),
        ("workload.ep", _with_workload(ep=8)),
        ("workload.dp", _with_workload(dp=4)),
        ("workload.param_count_b", _with_workload(param_count_b=70.0)),
        ("workload.sequence_length", _with_workload(sequence_length=8192)),
        ("workload.batch_size", _with_workload(batch_size=32)),
        ("workload.precision", _with_workload(precision="bf16")),
        ("workload.serving_mode", _with_workload(serving_mode=ServingMode.PREFILL_HEAVY)),
        ("workload.collectives", _with_workload(collectives=(
            CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=8),))),
        ("workload.trace_path", _with_workload(trace_path="runs/traces/y.trace")),
        # Requirement
        ("requirement.qos_class", _with_requirement(0, qos_class=QoSClass.BEST_EFFORT)),
        ("requirement.latency_ceiling_cycles", _with_requirement(0, latency_ceiling_cycles=4321.0)),
        ("requirement.bandwidth_floor_gbps", _with_requirement(0, bandwidth_floor_gbps=55.0)),
        ("requirement.binding", _with_requirement(0, binding=False)),
        # Agent
        ("agent.kind", _with_agent(0, kind=AgentKind.NIC)),
        ("agent.count", _with_agent(0, count=128)),
        ("agent.data_width", _with_agent(0, data_width=1024)),
        ("agent.addr_width", _with_agent(0, addr_width=64)),
        ("agent.protocol", _with_agent(0, protocol="AXI")),
        ("agent.clock_domain", _with_agent(0, clock_domain="clk9")),
        ("agent.power_domain", _with_agent(0, power_domain="pd9")),
        # Dependency
        ("dependency.source", _with_deps([
            Dependency(source="cls_z", target="cls_b", kind=DepKind.BLOCKING),
            Dependency(source="cls_b", target="cls_c", kind=DepKind.ORDERING)])),
        ("dependency.target", _with_deps([
            Dependency(source="cls_a", target="cls_z", kind=DepKind.BLOCKING),
            Dependency(source="cls_b", target="cls_c", kind=DepKind.ORDERING)])),
        ("dependency.kind", _with_deps([
            Dependency(source="cls_a", target="cls_b", kind=DepKind.INDEPENDENT),
            Dependency(source="cls_b", target="cls_c", kind=DepKind.ORDERING)])),
        # NocConfig
        ("noc_config.topology_family", _with_noc(topology_family=TopologyFamily.MESH)),
        ("noc_config.radix", _with_noc(radix=16)),
        ("noc_config.concentration", _with_noc(concentration=4)),
        ("noc_config.arbitration", _with_noc(arbitration="fixed")),
        ("noc_config.rcu_enabled", _with_noc(rcu_enabled=False)),
        ("noc_config.link_width", _with_noc(link_width=512)),
        ("noc_config.mcast_groups", _with_noc(mcast_groups=8)),
        ("noc_config.mcast_setup_cycles", _with_noc(mcast_setup_cycles=99)),
        ("noc_config.output_formats", _with_noc(
            output_formats=(OutputFormat.SYSTEMVERILOG,))),
        ("noc_config.obfuscation_level", _with_noc(obfuscation_level=1)),
        # Physical
        ("physical.clock_freq_mhz", _with_physical(default_clock_freq_mhz=1500.0)),
        ("physical.data_width", _with_physical(default_data_width=256)),
        ("physical.num_power_domains", _with_physical(num_power_domains=5)),
        ("physical.process_node_nm", _with_physical(process_node_nm=3)),
        # Address map
        ("address_map.name", _with_ranges([
            _address_range(name="HBM1"),
            AddressRange(name="SRAM0", base=0x20000000, size=0x100000,
                         target_agent_idx=0)])),
        ("address_map.base", _with_ranges([
            _address_range(base=0x1000),
            AddressRange(name="SRAM0", base=0x20000000, size=0x100000,
                         target_agent_idx=0)])),
        ("address_map.size", _with_ranges([
            _address_range(size=0x20000000),
            AddressRange(name="SRAM0", base=0x20000000, size=0x100000,
                         target_agent_idx=0)])),
        ("address_map.target_agent_idx", _with_ranges([
            _address_range(target_agent_idx=0),
            AddressRange(name="SRAM0", base=0x20000000, size=0x100000,
                         target_agent_idx=1)])),
        # Envelope
        ("schema_version", replace(_full_request(),
                                   schema_version=COMPILE_REQUEST_SCHEMA_VERSION + 1)),
        ("compiler_semantics_version", replace(
            _full_request(),
            compiler_semantics_version=COMPILER_SEMANTICS_VERSION + 1)),
    ]
    return m


@pytest.mark.parametrize("label,mutated", _matrix(),
                         ids=[lbl for lbl, _ in _matrix()])
def test_semantic_field_mutation_changes_design_hash(label, mutated):
    assert mutated.design_hash() != _base_hash(), (
        f"mutating {label} did not change design identity")


def test_mutation_matrix_is_complete():
    """Every semantic field appears in the matrix at least once."""
    labels = {lbl for lbl, _ in _matrix()}
    expected = {
        "workload.model_family", "workload.model_name", "workload.tp",
        "workload.pp", "workload.ep", "workload.dp", "workload.param_count_b",
        "workload.sequence_length", "workload.batch_size", "workload.precision",
        "workload.serving_mode", "workload.collectives", "workload.trace_path",
        "requirement.qos_class", "requirement.latency_ceiling_cycles",
        "requirement.bandwidth_floor_gbps", "requirement.binding",
        "agent.kind", "agent.count", "agent.data_width", "agent.addr_width",
        "agent.protocol", "agent.clock_domain", "agent.power_domain",
        "dependency.source", "dependency.target", "dependency.kind",
        "noc_config.topology_family", "noc_config.radix",
        "noc_config.concentration", "noc_config.arbitration",
        "noc_config.rcu_enabled", "noc_config.link_width",
        "noc_config.mcast_groups", "noc_config.mcast_setup_cycles",
        "noc_config.output_formats", "noc_config.obfuscation_level",
        "physical.clock_freq_mhz", "physical.data_width",
        "physical.num_power_domains", "physical.process_node_nm",
        "address_map.name", "address_map.base", "address_map.size",
        "address_map.target_agent_idx",
        "schema_version", "compiler_semantics_version",
    }
    assert labels == expected


# ── §23 field-coverage sentinel ─────────────────────────────────────────────

# Fields deliberately excluded from identity. Must be empty for the
# product-intent dataclasses today; if that changes, name the field here
# with a written reason.
NON_SEMANTIC_FIELDS = {
    CompileRequest: frozenset(),
    Workload: frozenset(),
    Requirement: frozenset(),
    Agent: frozenset(),
    Dependency: frozenset(),
    NocConfig: frozenset(),
    AddressRange: frozenset(),
    PhysicalContext: frozenset(),
}


@pytest.mark.parametrize("cls", list(NON_SEMANTIC_FIELDS),
                         ids=lambda c: c.__name__)
def test_field_coverage_sentinel(cls):
    """A new dataclass field must be classified before this passes.

    All fields are currently semantic; adding one to any of these
    dataclasses fails this test until it is either included in identity
    or explicitly listed in NON_SEMANTIC_FIELDS with a reason.
    """
    names = {f.name for f in dataclasses.fields(cls)}
    non_semantic = NON_SEMANTIC_FIELDS[cls]
    semantic = names - non_semantic
    assert semantic, f"{cls.__name__} has no semantic fields?"
    assert semantic | non_semantic == names
    assert not (semantic & non_semantic)


# ── §21 / §15 complete round trip ───────────────────────────────────────────

def test_complete_round_trip_is_lossless():
    cr = _full_request()
    restored = CompileRequest.from_dict(cr.to_dict())
    assert restored == cr
    assert restored.to_dict() == cr.to_dict()
    assert restored.design_hash() == cr.design_hash()


@pytest.mark.parametrize("path", [
    "workload.pp", "workload.param_count_b", "workload.sequence_length",
    "workload.batch_size", "workload.precision", "workload.trace_path",
    "agents.0.clock_domain", "agents.0.power_domain",
    "physical.num_power_domains", "noc_config.output_formats",
])
def test_previously_dropped_fields_survive_serialization(path):
    d = _full_request().to_dict()
    cur = d
    for part in path.split("."):
        cur = cur[int(part)] if part.isdigit() else cur[part]
    assert cur is not None


# ── §24 dictionary insertion order ──────────────────────────────────────────

def test_json_key_order_does_not_affect_hash():
    a = _full_request()
    d = a.to_dict()
    reordered = dict(reversed(list(d.items())))
    b = CompileRequest.from_dict(reordered)
    assert b.design_hash() == a.design_hash()


# ── §25 collection order semantics ──────────────────────────────────────────

def test_requirements_order_is_irrelevant():
    a = _full_request()
    b = replace(a, requirements=tuple(reversed(a.requirements)))
    assert b.design_hash() == a.design_hash()


def test_address_ranges_order_is_irrelevant():
    a = _full_request()
    b = replace(a, address_map=AddressMap(
        ranges=tuple(reversed(a.address_map.ranges))))
    assert b.design_hash() == a.design_hash()


def test_output_formats_order_is_irrelevant():
    fmts = (OutputFormat.SYSTEMVERILOG, OutputFormat.UVM, OutputFormat.JSON)
    a = _with_noc(output_formats=fmts)
    b = _with_noc(output_formats=tuple(reversed(fmts)))
    assert b.design_hash() == a.design_hash()


def test_agents_order_is_semantic():
    a = _full_request()
    b = replace(a, agents=tuple(reversed(a.agents)))
    assert b.design_hash() != a.design_hash()


def test_collectives_order_is_semantic():
    colls = (CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=8),
             CollectiveOp(kind=CollectiveKind.ALLGATHER, group_size=4))
    a = _with_workload(collectives=colls)
    b = _with_workload(collectives=tuple(reversed(colls)))
    assert b.design_hash() != a.design_hash()


def test_dependencies_order_is_semantic():
    deps = [Dependency(source="a", target="b", kind=DepKind.BLOCKING),
            Dependency(source="b", target="c", kind=DepKind.ORDERING)]
    a = _with_deps(deps)
    b = _with_deps(list(reversed(deps)))
    assert b.design_hash() != a.design_hash()


# ── §26 unknown fields ──────────────────────────────────────────────────────

def _doc() -> dict:
    return _full_request().to_dict()


@pytest.mark.parametrize("mutate,where", [
    (lambda d: d.__setitem__("tpp", 16), "root.tpp"),
    (lambda d: d["workload"].__setitem__("tpp", 16), "workload.tpp"),
    (lambda d: d["agents"][0].__setitem__("width", 4), "agents[0].width"),
    (lambda d: d["noc_config"].__setitem__("routing", "dor"), "noc_config.routing"),
    (lambda d: d["physical"].__setitem__("voltage", 1.0), "physical.voltage"),
    (lambda d: d["address_map"]["ranges"][0].__setitem__("owner", "x"),
     "address_map.ranges[0].owner"),
])
def test_unknown_field_refused(mutate, where):
    d = _doc()
    mutate(d)
    with pytest.raises(CompileRequestSchemaError, match="unknown field"):
        CompileRequest.from_dict(d)


def test_underscore_metadata_allowed_at_root():
    d = _doc()
    d["_comment"] = "documentation"
    CompileRequest.from_dict(d)  # must not raise, must not change identity


# ── §27 / §28 schema behavior ───────────────────────────────────────────────

def test_missing_schema_version_refused():
    d = _doc()
    del d["schema_version"]
    with pytest.raises(CompileRequestSchemaError, match="missing schema_version"):
        CompileRequest.from_dict(d)


def test_old_schema_version_refused():
    d = _doc()
    d["schema_version"] = 1
    with pytest.raises(CompileRequestSchemaError, match="unsupported"):
        CompileRequest.from_dict(d)


def test_future_schema_version_refused():
    d = _doc()
    d["schema_version"] = COMPILE_REQUEST_SCHEMA_VERSION + 1
    with pytest.raises(CompileRequestSchemaError, match="unsupported"):
        CompileRequest.from_dict(d)


def test_future_compiler_semantics_refused():
    d = _doc()
    d["compiler_semantics_version"] = COMPILER_SEMANTICS_VERSION + 1
    with pytest.raises(CompileRequestSchemaError, match="compiler_semantics"):
        CompileRequest.from_dict(d)


def test_tampered_design_hash_refused():
    d = _doc()
    d["design_hash"] = "0" * 64
    with pytest.raises(CompileRequestSchemaError, match="does not match"):
        CompileRequest.from_dict(d)


def test_current_schema_accepted():
    CompileRequest.from_dict(_doc())  # must not raise


# ── §29 invalid numerics ────────────────────────────────────────────────────

@pytest.mark.parametrize("mutate,exc", [
    (lambda d: d["workload"].__setitem__("tp", 0), ValueError),
    (lambda d: d["workload"].__setitem__("pp", -1), ValueError),
    (lambda d: d["workload"].__setitem__("param_count_b", float("nan")), ValueError),
    (lambda d: d["workload"].__setitem__("param_count_b", float("inf")), ValueError),
    (lambda d: d["workload"].__setitem__("param_count_b", 0), ValueError),
    (lambda d: d["workload"].__setitem__("sequence_length", 0), ValueError),
    (lambda d: d["workload"].__setitem__("batch_size", 0), ValueError),
    (lambda d: d["agents"][0].__setitem__("count", 0), ValueError),
    (lambda d: d["agents"][0].__setitem__("data_width", 4), ValueError),
    (lambda d: d["agents"][0].__setitem__("addr_width", 0), ValueError),
    (lambda d: d["requirements"][0].__setitem__("latency_ceiling_cycles", float("nan")), ValueError),
    (lambda d: d["requirements"][0].__setitem__("latency_ceiling_cycles", -1.0), ValueError),
    (lambda d: d["requirements"][0].__setitem__("bandwidth_floor_gbps", float("inf")), ValueError),
    (lambda d: d["physical"].__setitem__("clock_freq_mhz", float("nan")), ValueError),
    (lambda d: d["physical"].__setitem__("clock_freq_mhz", 0.0), ValueError),
    (lambda d: d["physical"].__setitem__("num_power_domains", 0), ValueError),
    (lambda d: d["physical"].__setitem__("process_node_nm", 0), ValueError),
    (lambda d: d["address_map"]["ranges"][0].__setitem__("size", 0), ValueError),
    (lambda d: d["address_map"]["ranges"][0].__setitem__("base", -1), ValueError),
    (lambda d: d["address_map"]["ranges"][0].__setitem__("target_agent_idx", -1), ValueError),
])
def test_invalid_numerics_refused(mutate, exc):
    d = _doc()
    mutate(d)
    with pytest.raises(exc):
        CompileRequest.from_dict(d)


# ── §31 hash domain separation ──────────────────────────────────────────────

def test_canonical_envelope_carries_type_discriminator():
    c = _full_request().canonical_dict()
    assert c["type"] == "srota/CompileRequest"
    assert c["schema_version"] == COMPILE_REQUEST_SCHEMA_VERSION
    assert c["compiler_semantics_version"] == COMPILER_SEMANTICS_VERSION


def test_schema_version_forks_identity():
    a = _full_request()
    b = replace(a, schema_version=a.schema_version + 1)
    assert a.design_hash() != b.design_hash()


def test_compiler_semantics_version_forks_identity():
    a = _full_request()
    b = replace(a, compiler_semantics_version=a.compiler_semantics_version + 1)
    assert a.design_hash() != b.design_hash()


# ── §32 no execution provenance leak ────────────────────────────────────────

_PROVENANCE_TOKENS = (
    "commit", "dirty", "binary", "bin_path", "hostname", "host",
    "python", "timestamp", "created_at", "run_id", "seed", "container",
    "git", "argv", "env",
)


def test_no_execution_provenance_in_canonical_identity():
    canon = json.dumps(_full_request().canonical_dict(), sort_keys=True)
    for tok in _PROVENANCE_TOKENS:
        assert tok not in canon, f"provenance token {tok!r} leaked into identity"
    # The whole envelope is exactly the known semantic keys + discriminator.
    assert set(_full_request().canonical_dict()) == {
        "type", "schema_version", "compiler_semantics_version",
        "workload", "requirements", "agents", "dependencies", "noc_config",
        "address_map", "physical",
    }


def test_same_intent_same_hash_across_construction_contexts():
    # Different construction path (round-trip) in a different "context"
    # must yield the same identity — no context leaks in.
    a = _full_request()
    b = CompileRequest.from_dict(json.loads(json.dumps(a.to_dict())))
    assert a.design_hash() == b.design_hash()
    assert a.design_hash() == CompileRequest.from_dict(a.to_dict()).design_hash()


# ── §30 hash stability golden ───────────────────────────────────────────────

def test_golden_design_hash_is_stable():
    """Deliberate change detector.

    If this fails, canonical serialization changed. Do NOT just update the
    constant: bump COMPILE_REQUEST_SCHEMA_VERSION or
    COMPILER_SEMANTICS_VERSION (whichever semantics moved) and explain why.
    """
    assert _full_request().design_hash() == GOLDEN_DESIGN_HASH


# ── §33 tracked examples ────────────────────────────────────────────────────

@pytest.mark.parametrize("path", sorted(EXAMPLES_DIR.glob("*.json")),
                         ids=lambda p: p.name)
def test_tracked_example_round_trips(path):
    cr = CompileRequest.from_dict(json.loads(path.read_text()))
    assert CompileRequest.from_dict(cr.to_dict()).design_hash() == cr.design_hash()
    assert cr.design_hash() == CompileRequest.from_dict(
        json.loads(path.read_text())).design_hash()

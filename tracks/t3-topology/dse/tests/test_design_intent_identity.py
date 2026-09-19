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
  DependencyGraph  dependencies      UNORDERED (semantics v2; graph
                                                processing is deterministic)
  CompileRequest   requirements      UNORDERED per-class bounds; min()/all()
                                                are order-independent
  AddressMap       ranges            UNORDERED validate_no_overlaps sorts by
                                                base; no decode-order consumer
  NocConfig        output_formats    UNORDERED a set of requested artifacts

RESOLVED (Wave B3.0-pre): the B1 temporary ruling made dependency edge
order identity-bearing because adjacency insertion order fed the DFS in
DependencyGraph.find_cycles. find_cycles now sorts traversal order, so
semantics v2 makes dependency edge order non-semantic. Legacy semantics
v1 documents remain loadable and are hashed in declared order.
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
#
# B3.0-pre: COMPILER_SEMANTICS_VERSION 1 -> 2 made dependency edge order
# non-semantic. The hash body's semantics-version component (c1 -> c2) and
# the canonical sorting of dependencies both move this value; that is the
# intended consequence of the semantics change, not drift.
GOLDEN_DESIGN_HASH = \
    "941e403861f5f71fd6c8235ef5ac0efd3ac1cc226aada28cdf67110eac7ac779"

# ── explicit positive field classification ──────────────────────────────────
# A new dataclass field fails test_field_coverage_sentinel until it is
# listed here (identity-bearing) or in NON_SEMANTIC_FIELDS (with a reason).
IDENTITY_FIELDS = {
    CompileRequest: frozenset({
        "workload", "requirements", "agents", "dependencies", "noc_config",
        "address_map", "physical", "schema_version",
        "compiler_semantics_version",
    }),
    Workload: frozenset({
        "model_family", "model_name", "tp", "pp", "ep", "dp",
        "param_count_b", "sequence_length", "batch_size", "precision",
        "serving_mode", "collectives", "trace_path",
    }),
    CollectiveOp: frozenset({"kind", "group_size", "bytes_per_element"}),
    Requirement: frozenset({
        "qos_class", "latency_ceiling_cycles", "bandwidth_floor_gbps",
        "binding",
    }),
    Agent: frozenset({
        "kind", "count", "data_width", "addr_width", "protocol",
        "clock_domain", "power_domain",
    }),
    Dependency: frozenset({"source", "target", "kind"}),
    DependencyGraph: frozenset({"dependencies"}),
    NocConfig: frozenset({
        "topology_family", "radix", "concentration", "arbitration",
        "rcu_enabled", "link_width", "mcast_groups", "mcast_setup_cycles",
        "output_formats", "obfuscation_level",
    }),
    AddressMap: frozenset({"ranges"}),
    AddressRange: frozenset({"name", "base", "size", "target_agent_idx"}),
    PhysicalContext: frozenset({
        "default_clock_freq_mhz", "default_data_width", "num_power_domains",
        "process_node_nm",
    }),
}

# Fields deliberately excluded from identity. Empty today; a future
# non-semantic field must be named here with a reason.
NON_SEMANTIC_FIELDS = {cls: frozenset() for cls in IDENTITY_FIELDS}

# Version fields are identity-bearing constants: construction refuses any
# unsupported version (only the supported set is representable), so they
# cannot be freely mutated and do not appear in the mutation matrix.
IMMUTABLE_CONSTANT_FIELDS = frozenset({
    (CompileRequest, "schema_version"),
    (CompileRequest, "compiler_semantics_version"),
})

_LEAF_FIELDS = frozenset(
    (cls, f) for cls, fs in IDENTITY_FIELDS.items() for f in fs
) - IMMUTABLE_CONSTANT_FIELDS


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


def _noc_config(**kw) -> NocConfig:
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


def _deps(**kw) -> DependencyGraph:
    base = dict(dependencies=(
        Dependency(source="cls_a", target="cls_b", kind=DepKind.BLOCKING),
        Dependency(source="cls_b", target="cls_c", kind=DepKind.ORDERING),
    ))
    base.update(kw)
    return DependencyGraph(**base)


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
        dependencies=_deps(),
        noc_config=_noc_config(),
        address_map=AddressMap(ranges=(
            AddressRange(name="SRAM0", base=0x20000000, size=0x100000,
                         target_agent_idx=0),
            _address_range(),
        )),
        physical=_physical(),
    )


B = _full_request()


def _wl(**kw) -> CompileRequest:
    return replace(B, workload=_workload(**kw))


def _req(i, **kw) -> CompileRequest:
    reqs = list(B.requirements)
    reqs[i] = replace(reqs[i], **kw)
    return replace(B, requirements=tuple(reqs))


def _coll(**kw) -> CompileRequest:
    colls = list(B.workload.collectives)
    colls[0] = replace(colls[0], **kw)
    return replace(B, workload=replace(B.workload, collectives=tuple(colls)))


def _ag(i, **kw) -> CompileRequest:
    agents = list(B.agents)
    agents[i] = replace(agents[i], **kw)
    return replace(B, agents=tuple(agents))


def _dep(i, **kw) -> CompileRequest:
    deps = list(B.dependencies.dependencies)
    deps[i] = replace(deps[i], **kw)
    return replace(B, dependencies=DependencyGraph(tuple(deps)))


def _noc(**kw) -> CompileRequest:
    return replace(B, noc_config=_noc_config(**kw))


def _phys(**kw) -> CompileRequest:
    return replace(B, physical=_physical(**kw))


def _rng(i, **kw) -> CompileRequest:
    rs = list(B.address_map.ranges)
    rs[i] = replace(rs[i], **kw)
    return replace(B, address_map=AddressMap(ranges=tuple(rs)))


# (ClassName, field) -> zero-arg callable producing a request differing
# only in that field. Covers every identity-bearing leaf field; the
# coverage test asserts this mechanically.
MUTATORS = {
    # CompileRequest object fields
    (CompileRequest, "workload"): lambda: _wl(model_name="Other"),
    (CompileRequest, "requirements"):
        lambda: replace(B, requirements=(B.requirements[0],)),
    (CompileRequest, "agents"): lambda: replace(B, agents=(B.agents[0],)),
    (CompileRequest, "dependencies"):
        lambda: replace(B, dependencies=DependencyGraph(
            (B.dependencies.dependencies[0],))),
    (CompileRequest, "noc_config"): lambda: _noc(radix=16),
    (CompileRequest, "address_map"):
        lambda: replace(B, address_map=AddressMap(
            ranges=(B.address_map.ranges[0],))),
    (CompileRequest, "physical"): lambda: _phys(default_data_width=256),
    # Workload
    (Workload, "model_family"): lambda: _wl(model_family=ModelFamily.DENSE_TRANSFORMER),
    (Workload, "model_name"): lambda: _wl(model_name="Other"),
    (Workload, "tp"): lambda: _wl(tp=16),
    (Workload, "pp"): lambda: _wl(pp=3),
    (Workload, "ep"): lambda: _wl(ep=8),
    (Workload, "dp"): lambda: _wl(dp=4),
    (Workload, "param_count_b"): lambda: _wl(param_count_b=70.0),
    (Workload, "sequence_length"): lambda: _wl(sequence_length=8192),
    (Workload, "batch_size"): lambda: _wl(batch_size=32),
    (Workload, "precision"): lambda: _wl(precision="bf16"),
    (Workload, "serving_mode"): lambda: _wl(serving_mode=ServingMode.PREFILL_HEAVY),
    (Workload, "collectives"): lambda: _wl(collectives=(
        CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=8),)),
    (Workload, "trace_path"): lambda: _wl(trace_path="runs/traces/y.trace"),
    # CollectiveOp
    (CollectiveOp, "kind"): lambda: _coll(kind=CollectiveKind.ALLREDUCE),
    (CollectiveOp, "group_size"): lambda: _coll(group_size=4),
    (CollectiveOp, "bytes_per_element"): lambda: _coll(bytes_per_element=8192),
    # Requirement
    (Requirement, "qos_class"): lambda: _req(0, qos_class=QoSClass.BEST_EFFORT),
    (Requirement, "latency_ceiling_cycles"): lambda: _req(0, latency_ceiling_cycles=4321.0),
    (Requirement, "bandwidth_floor_gbps"): lambda: _req(0, bandwidth_floor_gbps=55.0),
    (Requirement, "binding"): lambda: _req(0, binding=False),
    # Agent
    (Agent, "kind"): lambda: _ag(0, kind=AgentKind.NIC),
    (Agent, "count"): lambda: _ag(0, count=128),
    (Agent, "data_width"): lambda: _ag(0, data_width=1024),
    (Agent, "addr_width"): lambda: _ag(0, addr_width=64),
    (Agent, "protocol"): lambda: _ag(0, protocol="AXI"),
    (Agent, "clock_domain"): lambda: _ag(0, clock_domain="clk9"),
    (Agent, "power_domain"): lambda: _ag(0, power_domain="pd9"),
    # Dependency
    (Dependency, "source"): lambda: _dep(0, source="cls_z"),
    (Dependency, "target"): lambda: _dep(0, target="cls_z"),
    (Dependency, "kind"): lambda: _dep(0, kind=DepKind.INDEPENDENT),
    # DependencyGraph
    (DependencyGraph, "dependencies"): lambda: replace(B, dependencies=_deps(
        dependencies=(B.dependencies.dependencies[0],))),
    # NocConfig
    (NocConfig, "topology_family"): lambda: _noc(topology_family=TopologyFamily.MESH),
    (NocConfig, "radix"): lambda: _noc(radix=16),
    (NocConfig, "concentration"): lambda: _noc(concentration=4),
    (NocConfig, "arbitration"): lambda: _noc(arbitration="fixed"),
    (NocConfig, "rcu_enabled"): lambda: _noc(rcu_enabled=False),
    (NocConfig, "link_width"): lambda: _noc(link_width=512),
    (NocConfig, "mcast_groups"): lambda: _noc(mcast_groups=8),
    (NocConfig, "mcast_setup_cycles"): lambda: _noc(mcast_setup_cycles=99),
    (NocConfig, "output_formats"): lambda: _noc(
        output_formats=(OutputFormat.SYSTEMVERILOG,)),
    (NocConfig, "obfuscation_level"): lambda: _noc(obfuscation_level=1),
    # AddressMap
    (AddressMap, "ranges"): lambda: replace(B, address_map=AddressMap(
        ranges=(B.address_map.ranges[0],))),
    # AddressRange
    (AddressRange, "name"): lambda: _rng(1, name="HBM1"),
    (AddressRange, "base"): lambda: _rng(1, base=0x1000),
    (AddressRange, "size"): lambda: _rng(1, size=0x20000000),
    (AddressRange, "target_agent_idx"): lambda: _rng(1, target_agent_idx=0),
    # PhysicalContext
    (PhysicalContext, "default_clock_freq_mhz"): lambda: _phys(default_clock_freq_mhz=1500.0),
    (PhysicalContext, "default_data_width"): lambda: _phys(default_data_width=256),
    (PhysicalContext, "num_power_domains"): lambda: _phys(num_power_domains=5),
    (PhysicalContext, "process_node_nm"): lambda: _phys(process_node_nm=3),
}


# ── mutation matrix ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "key", sorted(MUTATORS, key=lambda k: (k[0].__name__, k[1])),
    ids=[f"{c.__name__}.{f}" for (c, f) in sorted(
        MUTATORS, key=lambda k: (k[0].__name__, k[1]))])
def test_semantic_field_mutation_changes_design_hash(key):
    mutated = MUTATORS[key]()
    assert mutated.design_hash() != B.design_hash(), (
        f"mutating {key[0].__name__}.{key[1]} did not change design identity")


def test_mutation_coverage_matches_classification():
    """Every identity-bearing leaf field is mutated; nothing else is."""
    assert set(MUTATORS) == set(_LEAF_FIELDS)


# ── field-coverage sentinel (positive classification) ───────────────────────

@pytest.mark.parametrize("cls", list(IDENTITY_FIELDS), ids=lambda c: c.__name__)
def test_field_coverage_sentinel(cls):
    """A new dataclass field fails here until it is classified.

    Identity and non-semantic sets must together equal the actual fields
    and must be disjoint, so merely existing cannot auto-enroll a field
    as semantic.
    """
    names = {f.name for f in dataclasses.fields(cls)}
    identity = IDENTITY_FIELDS[cls]
    non_semantic = NON_SEMANTIC_FIELDS[cls]
    assert not (identity & non_semantic), f"{cls.__name__}: overlapping classes"
    assert identity | non_semantic == names, (
        f"{cls.__name__}: unclassified fields "
        f"{sorted(names ^ (identity | non_semantic))}")


# ── deep immutability ───────────────────────────────────────────────────────

def test_dependencies_list_is_not_retained():
    deps = [Dependency(source="a", target="b", kind=DepKind.BLOCKING)]
    cr = replace(B, dependencies=deps)
    h = cr.design_hash()
    deps.append(Dependency(source="b", target="c", kind=DepKind.ORDERING))
    assert cr.design_hash() == h
    assert isinstance(cr.dependencies.dependencies, tuple)


def test_dependency_graph_dependencies_are_immutable():
    deps = [Dependency(source="a", target="b", kind=DepKind.BLOCKING)]
    g = DependencyGraph(deps)
    h = g.dependencies
    deps.clear()
    assert g.dependencies == h  # tuple snapshot, not the caller's list
    with pytest.raises((AttributeError, TypeError)):
        g.dependencies.append(deps)


def test_requirements_list_is_not_retained():
    reqs = [_requirement()]
    cr = replace(B, requirements=reqs, agents=(_agent(),))
    h = cr.design_hash()
    reqs.append(_requirement(qos_class=QoSClass.BANDWIDTH,
                             latency_ceiling_cycles=None,
                             bandwidth_floor_gbps=1.0, binding=False))
    assert cr.design_hash() == h
    assert isinstance(cr.requirements, tuple)


def test_agents_list_is_not_retained():
    agents = [_agent()]
    cr = replace(B, agents=agents, requirements=())
    h = cr.design_hash()
    agents.append(_agent(kind=AgentKind.NIC, count=2))
    assert cr.design_hash() == h
    assert isinstance(cr.agents, tuple)


def test_workload_collectives_list_is_not_retained():
    colls = [CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=8)]
    wl = Workload(model_family=ModelFamily.MOE, collectives=colls)
    h = replace(B, workload=wl).design_hash()
    colls.append(CollectiveOp(kind=CollectiveKind.ALLGATHER, group_size=4))
    assert replace(B, workload=wl).design_hash() == h
    assert isinstance(wl.collectives, tuple)


def test_address_ranges_list_is_not_retained():
    rs = [_address_range()]
    am = AddressMap(ranges=rs)
    h = replace(B, address_map=am).design_hash()
    rs.append(AddressRange(name="X", base=0x40000000, size=0x1000))
    assert replace(B, address_map=am).design_hash() == h
    assert isinstance(am.ranges, tuple)


# ── strict primitive typing + canonical numerics ────────────────────────────

@pytest.mark.parametrize("build", [
    lambda: _workload(tp=True),
    lambda: _workload(tp=1.0),
    lambda: _workload(pp=2.0),
    lambda: _workload(batch_size=True),
    lambda: _workload(sequence_length=4096.0),
    lambda: _agent(count=True),
    lambda: _agent(data_width=256.0),
    lambda: _agent(addr_width=True),
    lambda: _requirement(binding=1),
    lambda: _requirement(latency_ceiling_cycles=True),
    lambda: _noc_config(rcu_enabled="false"),
    lambda: _noc_config(rcu_enabled=1),
    lambda: _noc_config(radix=8.0),
    lambda: _noc_config(obfuscation_level=True),
    lambda: _physical(num_power_domains=True),
    lambda: _physical(default_data_width=256.0),
    lambda: _address_range(base=0.0),
    lambda: _address_range(size=True),
    lambda: CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=8.0),
    lambda: Dependency(source="a", target="b", kind="blocking"),
], ids=lambda f: "case")
def test_primitive_type_violations_refused(build):
    with pytest.raises((ValueError, TypeError)):
        build()


def test_int_and_float_real_identity_are_equal():
    assert _phys(default_clock_freq_mhz=1000).design_hash() \
        == _phys(default_clock_freq_mhz=1000.0).design_hash()
    assert _req(0, latency_ceiling_cycles=500).design_hash() \
        == _req(0, latency_ceiling_cycles=500.0).design_hash()
    assert _req(0, bandwidth_floor_gbps=10).design_hash() \
        == _req(0, bandwidth_floor_gbps=10.0).design_hash()
    assert _wl(param_count_b=30).design_hash() \
        == _wl(param_count_b=30.0).design_hash()


def test_schema_version_float_representation_refused():
    d = B.to_dict()
    d["schema_version"] = 2.0
    with pytest.raises(CompileRequestSchemaError, match="schema_version"):
        CompileRequest.from_dict(d)


def test_compiler_semantics_float_representation_refused():
    d = B.to_dict()
    d["compiler_semantics_version"] = 1.0
    with pytest.raises(CompileRequestSchemaError, match="compiler_semantics"):
        CompileRequest.from_dict(d)


def test_wrong_int_types_in_doc_refused():
    d = B.to_dict()
    d["workload"]["tp"] = 1.0
    with pytest.raises(ValueError):
        CompileRequest.from_dict(d)


# ── version contract (unrepresentable in memory) ────────────────────────────

def test_unsupported_schema_unrepresentable():
    with pytest.raises(ValueError, match="schema_version"):
        replace(B, schema_version=COMPILE_REQUEST_SCHEMA_VERSION + 1)


def test_unsupported_semantics_unrepresentable():
    with pytest.raises(ValueError, match="compiler_semantics_version"):
        replace(B, compiler_semantics_version=COMPILER_SEMANTICS_VERSION + 1)


def test_missing_compiler_semantics_version_refused():
    d = B.to_dict()
    del d["compiler_semantics_version"]
    with pytest.raises(CompileRequestSchemaError,
                       match="missing required field root.compiler_semantics_version"):
        CompileRequest.from_dict(d)


# ── round trip ──────────────────────────────────────────────────────────────

def test_complete_round_trip_is_lossless():
    restored = CompileRequest.from_dict(B.to_dict())
    assert restored == B
    assert restored.to_dict() == B.to_dict()
    assert restored.design_hash() == B.design_hash()


@pytest.mark.parametrize("path", [
    "workload.pp", "workload.param_count_b", "workload.sequence_length",
    "workload.batch_size", "workload.precision", "workload.trace_path",
    "agents.0.clock_domain", "agents.0.power_domain",
    "physical.num_power_domains", "noc_config.output_formats",
])
def test_previously_dropped_fields_survive_serialization(path):
    cur = B.to_dict()
    for part in path.split("."):
        cur = cur[int(part)] if part.isdigit() else cur[part]
    assert cur is not None


def test_json_key_order_does_not_affect_hash():
    d = B.to_dict()
    reordered = dict(reversed(list(d.items())))
    assert CompileRequest.from_dict(reordered).design_hash() == B.design_hash()


# ── collection order semantics ──────────────────────────────────────────────

def test_requirements_order_is_irrelevant():
    assert replace(B, requirements=tuple(reversed(B.requirements))).design_hash() \
        == B.design_hash()


def test_address_ranges_order_is_irrelevant():
    rev = replace(B, address_map=AddressMap(
        ranges=tuple(reversed(B.address_map.ranges))))
    assert rev.design_hash() == B.design_hash()


def test_output_formats_order_is_irrelevant():
    fmts = (OutputFormat.SYSTEMVERILOG, OutputFormat.UVM, OutputFormat.JSON)
    a = _noc(output_formats=fmts)
    b = _noc(output_formats=tuple(reversed(fmts)))
    assert a.design_hash() == b.design_hash()


def test_agents_order_is_semantic():
    assert replace(B, agents=tuple(reversed(B.agents))).design_hash() \
        != B.design_hash()


def test_collectives_order_is_semantic():
    colls = (CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=8),
             CollectiveOp(kind=CollectiveKind.ALLGATHER, group_size=4))
    a = _wl(collectives=colls)
    b = _wl(collectives=tuple(reversed(colls)))
    assert a.design_hash() != b.design_hash()


def test_dependencies_order_is_irrelevant():
    deps = (Dependency(source="a", target="b", kind=DepKind.BLOCKING),
            Dependency(source="b", target="c", kind=DepKind.ORDERING))
    a = replace(B, dependencies=DependencyGraph(deps))
    b = replace(B, dependencies=DependencyGraph(tuple(reversed(deps))))
    assert a.design_hash() == b.design_hash()


def test_dependencies_order_is_semantic_under_legacy_v1():
    deps = (Dependency(source="a", target="b", kind=DepKind.BLOCKING),
            Dependency(source="b", target="c", kind=DepKind.ORDERING))
    a = replace(B, compiler_semantics_version=1,
                dependencies=DependencyGraph(deps))
    b = replace(B, compiler_semantics_version=1,
                dependencies=DependencyGraph(tuple(reversed(deps))))
    assert a.design_hash() != b.design_hash()


# ── unknown fields and metadata allowlist ───────────────────────────────────

@pytest.mark.parametrize("mutate", [
    lambda d: d.__setitem__("tpp", 16),
    lambda d: d["workload"].__setitem__("tpp", 16),
    lambda d: d["agents"][0].__setitem__("width", 4),
    lambda d: d["noc_config"].__setitem__("routing", "dor"),
    lambda d: d["physical"].__setitem__("voltage", 1.0),
    lambda d: d["address_map"]["ranges"][0].__setitem__("owner", "x"),
])
def test_unknown_field_refused(mutate):
    d = B.to_dict()
    mutate(d)
    with pytest.raises(CompileRequestSchemaError, match="unknown field"):
        CompileRequest.from_dict(d)


def test_allowlisted_root_metadata_is_ignored():
    for key in ("_comment", "_docs"):
        d = B.to_dict()
        d[key] = "documentation"
        assert CompileRequest.from_dict(d).design_hash() == B.design_hash()


def test_non_allowlisted_underscore_field_refused():
    d = B.to_dict()
    d["_routing_override"] = "dor"
    with pytest.raises(CompileRequestSchemaError, match="unknown field"):
        CompileRequest.from_dict(d)


# ── schema behavior ─────────────────────────────────────────────────────────

def test_current_schema_accepted():
    CompileRequest.from_dict(B.to_dict())


def test_missing_schema_version_refused():
    d = B.to_dict()
    del d["schema_version"]
    with pytest.raises(CompileRequestSchemaError, match="missing schema_version"):
        CompileRequest.from_dict(d)


def test_old_schema_version_refused():
    d = B.to_dict()
    d["schema_version"] = 1
    with pytest.raises(CompileRequestSchemaError, match="unsupported"):
        CompileRequest.from_dict(d)


def test_future_schema_version_refused():
    d = B.to_dict()
    d["schema_version"] = COMPILE_REQUEST_SCHEMA_VERSION + 1
    with pytest.raises(CompileRequestSchemaError, match="unsupported"):
        CompileRequest.from_dict(d)


def test_future_compiler_semantics_refused():
    d = B.to_dict()
    d["compiler_semantics_version"] = COMPILER_SEMANTICS_VERSION + 1
    with pytest.raises(CompileRequestSchemaError, match="compiler_semantics"):
        CompileRequest.from_dict(d)


# ── compiler-semantics versions and migration (B3.0-pre) ────────────────────

def test_legacy_semantics_v1_is_loadable():
    v1 = replace(B, compiler_semantics_version=1)
    loaded = CompileRequest.from_dict(v1.to_dict())
    assert loaded.compiler_semantics_version == 1
    assert loaded.design_hash() == v1.design_hash()


def test_semantics_versions_produce_distinct_identities():
    assert replace(B, compiler_semantics_version=1).design_hash() \
        != replace(B, compiler_semantics_version=2).design_hash()


@pytest.mark.parametrize("bad", [0, 3, 99])
def test_unsupported_compiler_semantics_refused(bad):
    d = B.to_dict()
    d["compiler_semantics_version"] = bad
    with pytest.raises(CompileRequestSchemaError, match="compiler_semantics"):
        CompileRequest.from_dict(d)


@pytest.mark.parametrize("bad", [0, 3, 99])
def test_direct_construction_rejects_unsupported_semantics(bad):
    with pytest.raises(ValueError, match="compiler_semantics_version"):
        replace(B, compiler_semantics_version=bad)


def test_migrate_design_from_v1_reemits_current_semantics():
    from veritx_dse.model.compile_model import migrate_design
    v1 = replace(B, compiler_semantics_version=1)
    migrated, prov = migrate_design(v1.to_dict())
    assert migrated.compiler_semantics_version == COMPILER_SEMANTICS_VERSION
    assert migrated.design_hash() == CompileRequest.from_dict(
        migrated.to_dict()).design_hash()
    assert prov["from_semantics"] == 1
    assert prov["to_semantics"] == COMPILER_SEMANTICS_VERSION
    assert prov["changed"] is True
    assert prov["dependency_order_canonicalized"] is True


def test_migrate_design_current_semantics_is_noop():
    from veritx_dse.model.compile_model import migrate_design
    migrated, prov = migrate_design(B)
    assert migrated.design_hash() == B.design_hash()
    assert prov["changed"] is False
    assert prov["dependency_order_canonicalized"] is False


def test_migrated_identity_is_dependency_order_independent():
    from veritx_dse.model.compile_model import migrate_design
    deps = (Dependency(source="a", target="b", kind=DepKind.BLOCKING),
            Dependency(source="b", target="c", kind=DepKind.ORDERING))
    v1a = replace(B, compiler_semantics_version=1,
                  dependencies=DependencyGraph(deps))
    v1b = replace(B, compiler_semantics_version=1,
                  dependencies=DependencyGraph(tuple(reversed(deps))))
    assert v1a.design_hash() != v1b.design_hash()
    migrated_a, _ = migrate_design(v1a)
    migrated_b, _ = migrate_design(v1b)
    assert migrated_a.design_hash() == migrated_b.design_hash()


def test_tampered_design_hash_refused():
    d = B.to_dict()
    d["design_hash"] = "0" * 64
    with pytest.raises(CompileRequestSchemaError, match="does not match"):
        CompileRequest.from_dict(d)


# ── invalid numerics ────────────────────────────────────────────────────────

@pytest.mark.parametrize("mutate", [
    lambda d: d["workload"].__setitem__("tp", 0),
    lambda d: d["workload"].__setitem__("pp", -1),
    lambda d: d["workload"].__setitem__("param_count_b", float("nan")),
    lambda d: d["workload"].__setitem__("param_count_b", float("inf")),
    lambda d: d["workload"].__setitem__("param_count_b", 0),
    lambda d: d["workload"].__setitem__("sequence_length", 0),
    lambda d: d["workload"].__setitem__("batch_size", 0),
    lambda d: d["agents"][0].__setitem__("count", 0),
    lambda d: d["agents"][0].__setitem__("data_width", 4),
    lambda d: d["agents"][0].__setitem__("addr_width", 0),
    lambda d: d["requirements"][0].__setitem__("latency_ceiling_cycles", float("nan")),
    lambda d: d["requirements"][0].__setitem__("latency_ceiling_cycles", -1.0),
    lambda d: d["requirements"][0].__setitem__("bandwidth_floor_gbps", float("inf")),
    lambda d: d["physical"].__setitem__("clock_freq_mhz", float("nan")),
    lambda d: d["physical"].__setitem__("clock_freq_mhz", 0.0),
    lambda d: d["physical"].__setitem__("num_power_domains", 0),
    lambda d: d["physical"].__setitem__("process_node_nm", 0),
    lambda d: d["address_map"]["ranges"][0].__setitem__("size", 0),
    lambda d: d["address_map"]["ranges"][0].__setitem__("base", -1),
    lambda d: d["address_map"]["ranges"][0].__setitem__("target_agent_idx", -1),
])
def test_invalid_numerics_refused(mutate):
    d = B.to_dict()
    mutate(d)
    with pytest.raises(ValueError):
        CompileRequest.from_dict(d)


# ── hash domain separation and provenance exclusion ─────────────────────────

def test_canonical_envelope_carries_type_discriminator():
    c = B.canonical_dict()
    assert c["type"] == "srota/CompileRequest"
    assert c["schema_version"] == COMPILE_REQUEST_SCHEMA_VERSION
    assert c["compiler_semantics_version"] == COMPILER_SEMANTICS_VERSION


_PROVENANCE_TOKENS = (
    "commit", "dirty", "binary", "bin_path", "hostname", "host",
    "python", "timestamp", "created_at", "run_id", "seed", "container",
    "git", "argv", "env",
)


def test_no_execution_provenance_in_canonical_identity():
    canon = json.dumps(B.canonical_dict(), sort_keys=True)
    for tok in _PROVENANCE_TOKENS:
        assert tok not in canon, f"provenance token {tok!r} leaked into identity"
    assert set(B.canonical_dict()) == {
        "type", "schema_version", "compiler_semantics_version",
        "workload", "requirements", "agents", "dependencies", "noc_config",
        "address_map", "physical",
    }


def test_same_intent_same_hash_across_construction_contexts():
    b = CompileRequest.from_dict(json.loads(json.dumps(B.to_dict())))
    assert B.design_hash() == b.design_hash()
    assert B.design_hash() == CompileRequest.from_dict(B.to_dict()).design_hash()


# ── golden hash ─────────────────────────────────────────────────────────────

def test_golden_design_hash_is_stable():
    """Deliberate change detector.

    If this fails, canonical serialization changed. Do NOT just update the
    constant: bump COMPILE_REQUEST_SCHEMA_VERSION or
    COMPILER_SEMANTICS_VERSION (whichever semantics moved) and explain why.
    """
    assert B.design_hash() == GOLDEN_DESIGN_HASH


# ── container sealing: only list (JSON) or tuple (memory) allowed ──────────

def _bad_container(kind, item):
    from collections import deque
    if kind == "deque":
        return deque([item])
    if kind == "set":
        return {item}
    if kind == "dict":
        return {"k": item}
    if kind == "str":
        return "abc"
    if kind == "generator":
        return (x for x in [item])
    raise AssertionError(kind)


_CONTAINER_KINDS = ("deque", "set", "dict", "str", "generator")


@pytest.mark.parametrize("kind", _CONTAINER_KINDS)
def test_workload_collectives_rejects_non_sequence(kind):
    with pytest.raises(ValueError, match="collectives"):
        Workload(model_family=ModelFamily.MOE,
                 collectives=_bad_container(
                     kind, CollectiveOp(kind=CollectiveKind.ALLREDUCE,
                                        group_size=8)))


@pytest.mark.parametrize("kind", _CONTAINER_KINDS)
def test_dependency_graph_rejects_non_sequence(kind):
    with pytest.raises(ValueError, match="dependencies"):
        DependencyGraph(_bad_container(
            kind, Dependency(source="a", target="b", kind=DepKind.BLOCKING)))


@pytest.mark.parametrize("kind", _CONTAINER_KINDS)
def test_address_map_rejects_non_sequence(kind):
    with pytest.raises(ValueError, match="ranges"):
        AddressMap(ranges=_bad_container(kind, _address_range()))


@pytest.mark.parametrize("kind", _CONTAINER_KINDS)
def test_noc_output_formats_rejects_non_sequence(kind):
    with pytest.raises(ValueError, match="output_formats"):
        NocConfig(output_formats=_bad_container(kind, OutputFormat.UVM))


@pytest.mark.parametrize("kind", _CONTAINER_KINDS)
def test_request_requirements_rejects_non_sequence(kind):
    with pytest.raises(ValueError, match="requirements"):
        replace(B, requirements=_bad_container(kind, _requirement()))


@pytest.mark.parametrize("kind", _CONTAINER_KINDS)
def test_request_agents_rejects_non_sequence(kind):
    with pytest.raises(ValueError, match="agents"):
        replace(B, agents=_bad_container(kind, _agent()))


@pytest.mark.parametrize("kind", _CONTAINER_KINDS)
def test_request_dependencies_rejects_non_graph_container(kind):
    with pytest.raises(ValueError):
        replace(B, dependencies=_bad_container(
            kind, Dependency(source="a", target="b", kind=DepKind.BLOCKING)))


def test_collections_are_stored_as_tuples():
    assert isinstance(B.requirements, tuple)
    assert isinstance(B.agents, tuple)
    assert isinstance(B.workload.collectives, tuple)
    assert isinstance(B.dependencies.dependencies, tuple)
    assert isinstance(B.address_map.ranges, tuple)
    assert isinstance(B.noc_config.output_formats, tuple)


def test_deque_not_retained():
    from collections import deque
    reqs = deque([_requirement()])
    with pytest.raises(ValueError):
        replace(B, requirements=reqs)


def test_generator_not_accepted_as_design_collection():
    with pytest.raises(ValueError):
        replace(B, requirements=(r for r in [_requirement()]))


# ── enum-typed fields validated on direct construction ─────────────────────

@pytest.mark.parametrize("build", [
    lambda: Agent(kind="compute_tile", count=1),
    lambda: Workload(model_family="mixture_of_experts"),
    lambda: Workload(model_family=ModelFamily.MOE, serving_mode="mixed"),
    lambda: CollectiveOp(kind="allreduce"),
    lambda: Requirement(qos_class="latency_critical"),
    lambda: Dependency(source="a", target="b", kind="blocking"),
], ids=["agent.kind", "workload.model_family", "workload.serving_mode",
        "collective.kind", "requirement.qos_class", "dependency.kind"])
def test_enum_fields_require_enum_type(build):
    with pytest.raises(ValueError):
        build()


# ── negative zero canonicalization ─────────────────────────────────────────

def test_negative_zero_real_values_canonicalize():
    for field in ("latency_ceiling_cycles", "bandwidth_floor_gbps"):
        h_int = _req(0, **{field: 0}).design_hash()
        h_pos = _req(0, **{field: 0.0}).design_hash()
        h_neg = _req(0, **{field: -0.0}).design_hash()
        assert h_int == h_pos == h_neg, f"{field}: signed zero forked identity"


def test_negative_zero_serializes_positive():
    d = _req(0, latency_ceiling_cycles=-0.0).to_dict()
    assert d["requirements"][0]["latency_ceiling_cycles"] == 0.0
    assert "-0.0" not in json.dumps(d["requirements"][0])


# ── tracked examples ────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", sorted(EXAMPLES_DIR.glob("*.json")),
                         ids=lambda p: p.name)
def test_tracked_example_round_trips(path):
    cr = CompileRequest.from_dict(json.loads(path.read_text()))
    assert CompileRequest.from_dict(cr.to_dict()).design_hash() == cr.design_hash()
    assert cr.design_hash() == CompileRequest.from_dict(
        json.loads(path.read_text())).design_hash()

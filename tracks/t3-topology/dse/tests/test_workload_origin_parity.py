"""Workload-origin parity (WOP) and capability-truth (CAP) tests.

AMEND-6 / AMEND-7. The reclamation audit found canonical downstream
workload semantics that current product intent cannot originate. These
tests pin the EVIDENCE-BASED decisions rather than the enum presence.

The governing distinction: a kind existing downstream does NOT make it
authorable. For every kind the question is who PRODUCES it, not who
consumes it.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
REGISTRY = ROOT / "docs/product/capability-registry.yaml"

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.model.compile_model import (
    CollectiveDimension,
    CollectiveIntent,
    CollectiveKind,
    WorkloadV3,
)


@pytest.fixture(scope="module")
def reg() -> dict:
    return yaml.safe_load(REGISTRY.read_text())


def _row(reg, cid) -> dict:
    return next(c for c in reg["capabilities"] if c["id"] == cid)


# ══ WOP-7: BROADCAST is refused or lowered, never silently dropped ══════

def test_wop_7_broadcast_without_root_refuses():
    """The historical scientific-corruption risk was a silently dropped
    BROADCAST. It is UNREPRESENTABLE without an explicit root."""
    with pytest.raises(ValueError) as e:
        CollectiveIntent(
            kind=CollectiveKind.BROADCAST, dimension=CollectiveDimension.TP,
            payload_bytes=1024, traffic_class="tc0", source_rank=None)
    msg = str(e.value)
    assert "source_rank" in msg
    assert "participants[0] is a legacy" in msg, \
        "the refusal must name the legacy invention it prevents"


def test_wop_7b_broadcast_with_root_is_accepted():
    op = CollectiveIntent(
        kind=CollectiveKind.BROADCAST, dimension=CollectiveDimension.TP,
        payload_bytes=1024, traffic_class="tc0", source_rank=3)
    assert op.source_rank == 3


def test_wop_7c_broadcast_is_a_declared_collective_kind():
    assert CollectiveKind.BROADCAST.value == "broadcast"


# ══ WOP-8: all five collectives remain independently declared ═══════════

def test_wop_8_five_collective_kinds_are_authorable():
    kinds = {k.value for k in CollectiveKind}
    assert kinds == {"allreduce", "allgather", "reducescatter",
                     "broadcast", "alltoall"}
    for k in CollectiveKind:
        op = CollectiveIntent(kind=k, dimension=CollectiveDimension.TP,
                              payload_bytes=512, traffic_class="tc0",
                              source_rank=0 if k is CollectiveKind.BROADCAST
                              else None)
        assert op.kind is k


# ══ WOP-9 / CAP-3: MoE model declaration != static expert lowering ═════

def test_wop_9_moe_model_declaration_does_not_imply_expert_lowering():
    """ModelFamily.MOE is SHAPE metadata. WorkloadV3 exposes collectives
    only — no expert dispatch/combine field."""
    fields = set(WorkloadV3.__dataclass_fields__)
    assert "collectives" in fields
    for absent in ("operations", "experts", "dispatch", "combine", "p2p",
                   "multicast", "pim"):
        assert absent not in fields, \
            f"WorkloadV3 must not silently gain an {absent!r} field"


def test_cap_3_moe_static_and_serving_cannot_collapse(reg):
    static = _row(reg, "WORK-002")
    static_expert = _row(reg, "WORK-009")
    serving = _row(reg, "WORK-004")
    assert static["id"] != serving["id"]
    # Static expert lowering is NOT authorable.
    assert static_expert["stages"]["DECLARABLE"] in ("NO", "LEGACY_ONLY")
    assert "not authorable" in static_expert["claim_scope"]
    # Serving MoE IS wired — and must stay a separate row.
    assert serving["stages"]["PRODUCT_WIRED"] == "YES"
    assert "Serving expert execution is WORK-004" in \
        static_expert["claim_scope"]


# ══ WOP-11 / CAP-1: the PIM decision is represented exactly ════════════

def test_cap_1_mem_007_matches_the_code(reg):
    """PIM's code is LIVE; its provenance is LEGACY. The row must say both
    and must not claim a product capability."""
    row = _row(reg, "MEM-007")
    assert row["stages"]["DECLARABLE"] == "LEGACY_ONLY"
    assert row["wiring"] == "NOT_AVAILABLE"
    scope = row["claim_scope"]
    assert "LIVE" in scope
    assert "legacy" in scope.lower()
    assert "no WorkloadV3 intent originates PIM" in scope
    assert "workload/migration.py" in scope


def test_cap_1b_mem_007_obeys_the_terminal_law(reg):
    """TERMINAL: a LEGACY_ONLY stage makes every later stage NO."""
    stages = _row(reg, "MEM-007")["stages"]
    order = ("DECLARABLE", "DERIVABLE", "VERIFIABLE", "PROJECTABLE",
             "EXECUTABLE", "QUALIFIED", "EVIDENCE_CAPABLE", "PRODUCT_WIRED")
    seen_terminal = False
    for s in order:
        v = stages[s]
        if seen_terminal:
            assert v == "NO", f"{s}={v} after a terminal stage"
        if v in ("LEGACY_ONLY", "FUTURE_CONTRACT"):
            seen_terminal = True


def test_wop_11_pim_producer_is_the_legacy_migration_path():
    """Evidence, not enum presence: the only producer of PIM_CHANNEL is
    workload/migration.py, and it is not on the product path."""
    dse = Path(__file__).parent.parent
    hits = []
    for path in (dse / "veritx_dse").rglob("*.py"):
        text = path.read_text()
        if "KIND_PIM_CHANNEL" in text:
            hits.append(path.name)
    assert "migration.py" in hits
    assert "graph.py" in hits
    # No intent/lowering module produces it.
    assert "lowering.py" not in hits, \
        "PIM_CHANNEL must not be produced by the canonical lowering"


# ══ WOP-12: CXL / REMOTE / STORAGE still refuse ════════════════════════

def test_wop_12_memory_locations_still_refuse():
    """The refusal vocabulary is intact and names each location."""
    src = (Path(__file__).parent.parent
           / "veritx_dse/workload/memory_lowering.py").read_text()
    for loc in ("REMOTE", "CXL", "STORAGE"):
        assert f'base == "{loc}"' in src, f"{loc} refusal disappeared"
    assert "is never HBM" in src          # STORAGE
    assert "not local memory" in src      # REMOTE


def test_cap_12_mem_006_stays_legacy_only(reg):
    row = _row(reg, "MEM-006")
    assert row["stages"]["DECLARABLE"] == "LEGACY_ONLY"
    assert row["wiring"] == "NOT_AVAILABLE"
    assert "refused at lowering" in row["claim_scope"]


# ══ CAP-2: logical and hardware multicast cannot collapse ══════════════

def test_cap_2_multicast_rows_are_distinct(reg):
    logical = _row(reg, "WORK-007")
    hardware = _row(reg, "WORK-008")
    assert logical["id"] != hardware["id"]
    assert "logical" in logical["name"].lower()
    assert "hardware" in hardware["name"].lower()
    # Hardware multicast is a FUTURE contract; logical is not.
    assert hardware["reason"] == "FUTURE_CONTRACT"
    assert hardware["wiring"] == "NOT_AVAILABLE"
    # The collapse is explicitly forbidden in the row text.
    assert "Never collapse this row with WORK-007" in hardware["claim_scope"]


def test_cap_2b_hardware_multicast_has_no_replication_artifact(reg):
    """mcast_groups/mcast_setup_cycles are switch-engine LIMITS, not a
    replication-tree resource — the row must say so."""
    scope = _row(reg, "WORK-008")["claim_scope"]
    assert "no hardware replication artifact exists" in scope
    assert "NOT a replication-tree resource" in scope


# ══ WOP-13: class binding uses the canonical authority ═════════════════

def test_wop_13_class_binding_is_the_canonical_authority():
    """CollectiveIntent carries traffic_class, the unified-namespace
    identity — there is no second QoS field on the operation."""
    fields = set(CollectiveIntent.__dataclass_fields__)
    assert "traffic_class" in fields
    for duplicate in ("qos", "priority", "service_class", "class_id"):
        assert duplicate not in fields, \
            f"a second class field {duplicate!r} would fork the authority"


# ══ CAP-4 / CAP-5: FlatFly and custom stage honesty ════════════════════

def test_cap_4_flatfly_materializable_does_not_imply_executable():
    fam = yaml.safe_load(
        (ROOT / "docs/product/topology-family-registry.yaml").read_text())
    flat = fam["families"]["flatfly"]["stages"]
    assert flat["MATERIALIZABLE"] == "YES"
    assert flat["EXECUTABLE"] == "NO"
    assert flat["QUALIFIED"] == "NO"
    assert flat["AUTHORABLE"] == "NO"


def test_cap_5_custom_materializable_does_not_imply_qualified():
    fam = yaml.safe_load(
        (ROOT / "docs/product/topology-family-registry.yaml").read_text())
    cust = fam["families"]["custom"]["stages"]
    assert cust["MATERIALIZABLE"] == "YES"
    assert cust["QUALIFIED"] != "YES", \
        "custom materialization must not advertise qualification"


# ══ CAP-6: Wave-E exposure reflects current wiring ═════════════════════

def test_cap_6_wave_e_metrics_are_registered_but_still_analytical():
    from veritx_dse.optimization.metric_registry import (
        CERTIFIED_METRIC_REGISTRY, wave_e_honesty_metadata,
    )
    names = set(CERTIFIED_METRIC_REGISTRY.metric_names())
    for m in ("makespan", "critical_path", "request_latency_mean",
              "resource_utilization_max"):
        assert m in names, f"{m} is not registered"
    meta = wave_e_honesty_metadata({})
    assert meta["authority"] == "ANALYTICAL_MODEL"
    assert meta["measured"] is False
    assert meta["predictive_validation"] == "NOT_ESTABLISHED"


# ══ registry gates ═════════════════════════════════════════════════════

def test_capability_registry_checker_passes():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_capability_registry.py")],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_topology_registry_checker_passes():
    r = subprocess.run(
        [sys.executable,
         str(ROOT / "scripts/check_topology_family_registry.py")],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

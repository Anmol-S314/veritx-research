"""Gen 6-class switch-fabric experiment: template, registry, dry-run, real run.

The template and workload are AUTHORED. These tests pin that the authored
document compiles, that the registry entry is discoverable, that the
experiment builder keeps 16 port-proxy ranks and the six declared classes,
and that a missing BookSim producer produces a blocker report with no
metrics rather than a fabricated result.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

import tools.run_microchip_switch as experiment  # noqa: E402
from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.application.fabric_evaluator import (  # noqa: E402
    BACKEND_UNAVAILABLE, EVALUATED,
)
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.model.compile_model import AgentKind  # noqa: E402
from veritx_dse.product.service import ProductConfig, ProductService  # noqa: E402
from veritx_dse.product.workload_registry import (  # noqa: E402
    load_registry, materialize, resolve,
)
from veritx_dse.simulation.booksim import find_booksim_bin  # noqa: E402
from veritx_dse.workload.intent_lowering import lower_compile_workload  # noqa: E402

WORKLOAD_ID = "switch-gen6-class"
EXPECTED_CLASSES = {
    "incast_ssd0", "multicast_equiv", "read_256k", "read_4k",
    "write_256k", "write_4k",
}
_DIRTY_MARKERS = ("producer tree is DIRTY", "no verified build-time manifest",
                  "not qualified", "not pinned")


@pytest.fixture(scope="module")
def binary() -> Path:
    try:
        return find_booksim_bin(REPO)
    except FileNotFoundError as exc:
        pytest.skip(f"no qualified BookSim producer: {exc}")


def test_template_parses_and_compiles_pass():
    document = experiment.load_template_doc()
    request = experiment.build_request()

    assert request.total_nodes == 16
    agents = [agent for agent in request.agents
              if agent.kind is AgentKind.COMPUTE_TILE]
    assert sum(agent.count for agent in agents) == 16
    assert not [agent for agent in request.agents
                if agent.kind is AgentKind.HBM_CONTROLLER]
    assert request.topology.kind == "mesh"
    assert request.topology.side_length == 4
    assert request.topology.concentration == 1
    assert len(request.workload.traffic_profiles) == 170

    comment = document["_comment"].lower()
    for phrase in ("authored hypothetical", "port proxies",
                   "not a model of any switchtec product",
                   "not a pcie protocol model", "no partition isolation"):
        assert phrase in comment, phrase

    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    assert compilation.certificate.overall == "PASS"


def test_workload_catalog_includes_switch_gen6_class(tmp_path):
    entries = {entry.workload_id: entry for entry in load_registry(REPO)}
    assert WORKLOAD_ID in entries
    entry = resolve(REPO, WORKLOAD_ID)
    assert entry is not None
    assert entry.origin == "registry"
    assert entry.display_name == "Gen 6-class switch fabric · hypothetical"
    assert entry.owners == 16
    description = entry.description.lower()
    assert "authored hypothetical" in description
    assert "not switchtec" in description

    document = materialize(entry, REPO)
    assert document["schema_version"] == 4
    assert len(document["workload"]["traffic_profiles"]) == 170

    service = ProductService(ProductConfig(projects_root=tmp_path / "p"))
    catalog = service.workload_catalog()["workloads"]
    row = next(w for w in catalog if w["workload_id"] == WORKLOAD_ID)
    assert row["evaluation_support"] == "SUPPORTED"
    assert row["agents"] == [{"kind": "compute_tile", "count": 16}]
    assert len(row["request"]["workload"]["traffic_profiles"]) == 170


def test_builder_returns_sixteen_ranks_and_expected_classes_on_all_five():
    requests = experiment.build_requests()
    assert set(requests) == {"mesh", "fattree", "flatfly", "srota", "gec_mecs"}

    hashes = set()
    for topology_id, request in requests.items():
        assert request.total_nodes == 16, topology_id
        if topology_id == "srota":
            assert request.topology.parameters()["planes"] == ["d"]
        summary = experiment.workload_summary(request)
        assert summary["rank_count"] == 16
        assert summary["host_ranks"] == list(range(8))
        assert summary["ssd_ranks"] == list(range(8, 16))
        assert summary["profile_count"] == 170
        assert set(summary["classes"]) == EXPECTED_CLASSES
        assert summary["base_read_share"] == pytest.approx(0.7)
        assert summary["base_write_share"] == pytest.approx(0.3)
        lowered = lower_compile_workload(request)
        assert set(lowered.classes) == EXPECTED_CLASSES
        hashes.add(request.design_hash())
    assert len(hashes) == 5


def test_srota_plane_d_multiclass_evaluates_when_booksim_is_available(
        binary, tmp_path):
    request = experiment.build_requests()["srota"]
    spec = next(row for row in experiment.TOPOLOGY_SPECS
                if row["topology_id"] == "srota")
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    assert compilation.certificate.overall == "PASS"

    row = experiment.evaluate_topology(
        request, spec, binary=binary, timeout_s=180,
        run_dir=tmp_path / "srota")
    if row["status"] == BACKEND_UNAVAILABLE and any(
            marker in (row.get("reason") or "") for marker in _DIRTY_MARKERS):
        pytest.skip(f"pinned producer unqualified in this worktree: "
                    f"{row.get('reason')}")
    assert row["status"] == EVALUATED, row
    assert row["backend_profile"] == "CERTIFIED_BOOKSIM_SROTA_ROW_FIRST_V1"
    assert row["evidence"]["execution_fidelity"] == "QUALIFIED"
    assert row["metrics"]["flits_injected"] == row["metrics"]["flits_accepted"]
    assert row["metrics"]["p50"] <= row["metrics"]["p95"] <= row["metrics"]["p99"]


def test_real_gec_mecs_evaluation_when_booksim_is_available(binary, tmp_path):
    request = experiment.build_requests()["gec_mecs"]
    spec = next(row for row in experiment.TOPOLOGY_SPECS
                if row["topology_id"] == "gec_mecs")
    row = experiment.evaluate_topology(
        request, spec, binary=binary, timeout_s=180,
        run_dir=tmp_path / "gec_mecs")

    if row["status"] == BACKEND_UNAVAILABLE and any(
            marker in (row.get("reason") or "") for marker in _DIRTY_MARKERS):
        pytest.skip(f"pinned producer unqualified in this worktree: "
                    f"{row.get('reason')}")
    assert row["status"] == EVALUATED, row
    assert row["backend_profile"] == "CERTIFIED_BOOKSIM_GEC_MECS_V1"
    assert row["metrics"]["completion_cycles"] > 0
    assert row["metrics"]["p50"] <= row["metrics"]["p95"] <= row["metrics"]["p99"]


def test_dry_run_does_not_require_booksim(monkeypatch, tmp_path):
    def unavailable(_repo_root):
        raise FileNotFoundError("BookSim deliberately absent for a dry run")

    monkeypatch.setattr(experiment, "find_booksim_bin", unavailable)
    exit_code = experiment.main(["--dry-run", "--out-dir", str(tmp_path)])
    assert exit_code == 0
    assert not (tmp_path / "results.json").exists()
    assert not (tmp_path / "results.md").exists()


def test_missing_booksim_writes_a_blocker_not_metrics(monkeypatch, tmp_path):
    def unavailable(_repo_root):
        raise FileNotFoundError("BookSim deliberately absent")

    monkeypatch.setattr(experiment, "find_booksim_bin", unavailable)
    result = experiment.run_experiment(out_dir=tmp_path / "out")

    assert result["status"] == "BLOCKED_BACKEND"
    assert result["blocker"]["kind"] == "BOOKSIM_NOT_FOUND"
    assert all(row["status"] == "NOT_EVALUATED"
               for row in result["topologies"])
    assert all("metrics" not in row for row in result["topologies"])

    json_path, md_path = experiment.write_outputs(result, tmp_path / "out")
    persisted = json.loads(json_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "BLOCKED_BACKEND"
    assert all("metrics" not in row for row in persisted["topologies"])
    assert "BLOCKED" in md_path.read_text(encoding="utf-8")


def test_real_mesh_evaluation_when_booksim_is_available(binary, tmp_path):
    request = experiment.build_request()
    spec = next(row for row in experiment.TOPOLOGY_SPECS
                if row["topology_id"] == "mesh")
    row = experiment.evaluate_topology(
        request, spec, binary=binary, timeout_s=180,
        run_dir=tmp_path / "mesh")

    if row["status"] == BACKEND_UNAVAILABLE and any(
            marker in (row.get("reason") or "") for marker in _DIRTY_MARKERS):
        pytest.skip(f"pinned producer unqualified in this worktree: "
                    f"{row.get('reason')}")
    assert row["status"] == EVALUATED, row
    assert row["compilation"]["status"] == "COMPILED"
    assert row["compilation"]["certificate_overall"] == "PASS"
    assert row["backend_profile"] == "CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1"

    metrics = row["metrics"]
    assert metrics["completion_cycles"] > 0
    assert metrics["flits_injected"] == metrics["flits_accepted"]
    assert metrics["p50"] <= metrics["p95"] <= metrics["p99"]
    assert row["class_metrics"]["class_names"] == sorted(EXPECTED_CLASSES)
    assert len(row["class_metrics"]["classes"]) == len(EXPECTED_CLASSES)
    assert row["evidence"]["raw_evidence_digest"]

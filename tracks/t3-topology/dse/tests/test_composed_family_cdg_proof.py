from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from veritx_dse.core.paths import REPO

FORMAL_AVAILABLE = all(shutil.which(tool) for tool in ("sby", "yosys", "z3"))


def _params(family: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "cd_mod", str(REPO / "scripts" / "complete_design.py"))
    cd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cd)
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.product import project_top_rtl
    request = cd.make_family_request(family)
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED", compiled.error
    params = project_top_rtl.composed_family_params_from_request(request, compiled)
    return params, compiled.bundle.topology


def _prove(family: str):
    from veritx_dse.product.composed_formal import run_composed_family_cdg_proof
    params, topology = _params(family)
    work = Path(tempfile.mkdtemp(prefix="cdg-"))
    return params, run_composed_family_cdg_proof(
        work_dir=work, params=params, topology=topology)


@pytest.mark.skipif(not FORMAL_AVAILABLE,
                    reason="formal toolchain (sby/yosys/z3) not installed")
@pytest.mark.parametrize("family", ["torus", "mesh", "flatfly", "ring", "fly"])
def test_composed_family_channel_dependency_graphs_are_acyclic(family):
    """The composed family's own route tables must not admit a circular wait.

    Same machinery and same honest scope as the mesh proof: the rank witness
    is complete over the extracted edge set; arbitration fairness, credit
    correctness and liveness under arbitrary traffic are not covered here.

    The ring is included because its VC is the fork's dateline half, so its
    two classes are proved separately.
    """
    params, result = _prove(family)
    assert result["status"] == "PASS", result
    assert result["stats"]["routers"] == params.n_routers
    assert sum(v["edges"] for v in result["stats"].values()
               if isinstance(v, dict) and "edges" in v) > 0


@pytest.mark.skipif(not FORMAL_AVAILABLE,
                    reason="formal toolchain (sby/yosys/z3) not installed")
def test_gec_shared_ingress_storage_is_proved_as_one_merged_cdg():
    params, result = _prove("gec_mecs")
    assert result["status"] == "PASS", result
    assert result["scope"].startswith("COMPLETE")
    assert set(result["stats"]) == {"routers", "shared_ingress"}
    assert result["stats"]["shared_ingress"]["edges"] > 0


@pytest.mark.skipif(not FORMAL_AVAILABLE,
                    reason="formal toolchain (sby/yosys/z3) not installed")
def test_gec_proof_refuses_topology_missing_a_shared_wire_hop():
    from dataclasses import replace
    from veritx_dse.product.composed_formal import run_composed_family_cdg_proof

    params, topology = _params("gec_mecs")
    adjacency = list(params.adjacency)
    adjacency[0] = tuple()
    result = run_composed_family_cdg_proof(
        work_dir=Path(tempfile.mkdtemp(prefix="gec-cdg-mutated-")),
        params=replace(params, adjacency=tuple(adjacency)), topology=topology)
    assert result["status"] == "NOT_RUN", result
    assert "not an emitted shared-wire tap" in result["reason"]


def test_gec_proof_refuses_missing_physical_wire_even_if_route_table_is_unchanged():
    from dataclasses import replace
    from veritx_dse.product.composed_formal import run_composed_family_cdg_proof

    params, topology = _params("gec_mecs")
    result = run_composed_family_cdg_proof(
        work_dir=Path(tempfile.mkdtemp(prefix="gec-cdg-wire-mutation-")),
        params=replace(params, resources=params.resources[:-1]), topology=topology)
    assert result["status"] == "NOT_RUN", result
    assert "full row/column shared wires" in result["reason"]


@pytest.mark.skipif(not FORMAL_AVAILABLE,
                    reason="formal toolchain (sby/yosys/z3) not installed")
def test_ring_family_dateline_halves_split_the_dependency_graph():
    """The ring's two VC classes are proved apart, and both are acyclic.

    The ring routes each (source, destination) over the shorter direction,
    so the union of its channels is cyclic. The VC is therefore not a
    class but the fork's dateline half — the injection router against the
    destination — and the proof is per VC class, because a buffer wait can
    only be against a buffer of the same VC.
    """
    params, result = _prove("ring")
    assert result["status"] == "PASS", result
    assert set(result["stats"]) == {"routers", "vc0_dateline_half",
                                    "vc1_dateline_half"}
    assert result["stats"]["vc0_dateline_half"]["edges"] > 0
    assert result["stats"]["vc1_dateline_half"]["edges"] > 0

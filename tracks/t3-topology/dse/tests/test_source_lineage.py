"""Source-lineage regressions (LIN-*).

A reclamation pass that "discovers" a missing behaviour and re-implements it
is only correct if no stronger implementation already exists elsewhere.
`integration/canonical` is a migration DESTINATION, not a quality ranking.

These tests pin the two regressions found and the law that prevents them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

def test_lin_10_hardened_milp_loader_rejects_malformed_input(tmp_path):
    """The hardened loader already existed on
    p1b/verified-evaluation / integration/p1-product. The current tree had
    regressed to the integration/canonical copy, which validated nothing,
    and Tranche 3 re-implemented those checks elsewhere. Reclaimed here."""
    from veritx_dse.synthesis.milp_topology_v2 import load_matrix

    cases = {
        "empty": "# only a comment\n",
        "ragged": "1 2\n3\n",
        "non_square": "1 2 3\n4 5 6\n",
        "non_numeric": "1 two\n3 4\n",
        "nan": "0 1\n1 nan\n",
        "inf": "0 1\n1 inf\n",
        "negative": "0 -1\n1 0\n",
    }
    for label, content in cases.items():
        p = tmp_path / f"{label}.mat"
        p.write_text(content)
        with pytest.raises(SystemExit):
            load_matrix(p)
    ok = tmp_path / "ok.mat"
    ok.write_text("0 1\n2 0\n")
    assert load_matrix(ok).shape == (2, 2)

def test_lin_10b_one_validation_authority():
    """SynthesisTrafficMatrix is the CANONICAL authority; the file parser is
    developer tooling. They must not drift into two independent
    validations of the same science."""
    from veritx_dse.synthesis.traffic import SynthesisTrafficMatrix
    src = (Path(__file__).parent.parent
           / "veritx_dse/synthesis/traffic.py").read_text()
    assert "source_artifact_id" in src
    with pytest.raises(Exception):
        SynthesisTrafficMatrix.from_rows(
            [[0, 1], [1, 0]], source_artifact_id="", namespace="r",
            unit="messages", aggregation="sum_over_workload")

def test_lin_10c_reclaimed_loader_records_its_provenance():
    """A reclaimed file must say where it came from, so the next worker does
    not default to integration/canonical because the name sounds right."""
    src = (Path(__file__).parent.parent
           / "veritx_dse/synthesis/milp_topology_v2.py").read_text()
    assert "RECLAIMED, not re-invented" in src
    assert "verified-evaluation" in src
    assert "integration/canonical" in src

def test_lin_1_route_artifact_gap_is_recorded_and_closed():
    """The strongest historical route_artifact.py carried functions the
    current tree lacked (equivalence_report, artifact_from_anynet,
    upgrade_v1_to_v2, ...). PHASE 2 reclaimed them; the record must name
    both the gap and its closure, so nobody re-opens or forgets it."""
    audit = (Path(__file__).parents[4]
             / "docs/product/SOURCE-LINEAGE-AUDIT.md").read_text()
    for fn in ("equivalence_report", "artifact_from_anynet",
               "upgrade_v1_to_v2"):
        assert fn in audit, f"{fn} must stay recorded"
    assert "RECLAIMED (PHASE 2)" in audit
    assert "route_observation.py" in audit
    assert "compare_first_hop_tables" in audit
    assert "simulator adapter" in audit

def test_lin_1b_authority_selection_law_is_documented():
    audit = (Path(__file__).parents[4]
             / "docs/product/SOURCE-LINEAGE-AUDIT.md").read_text()
    assert "does NOT mean" in audit
    assert "strongest historical source implementation" in audit

def test_lin_2_presets_missing_authorities_are_present():
    """These four were absent while live callers imported them. Their
    absence was a latent ImportError, not a design decision."""
    from veritx_dse.model.presets import (
        topo_size, parallel_world_size, resolve_fabric, normalize_collective,
    )
    assert topo_size("mesh", {"k": 8, "n": 2}) == (64, 112)
    assert parallel_world_size(2, 2, 4, 1) == 16
    assert normalize_collective("ALL_REDUCE") == "allreduce"
    topo, reason = resolve_fabric("mesh_8x8")
    assert topo is not None and reason is None
    assert resolve_fabric("mesh_8x8", "bogus")[0] is None

def test_lin_2b_presets_delegates_anynet_parsing_to_core_anynet():
    """core/anynet.py documents that presets delegates to it. That
    delegation had been lost while the buggy inline parser stayed."""
    src = (Path(__file__).parent.parent
           / "veritx_dse/model/presets.py").read_text()
    assert "from ..core.anynet import" in src
    assert "len(parts) < 5" not in src

def test_lin_2c_mesh_edge_count_is_not_the_torus_count():
    """The weaker copy returned n*k**n for BOTH mesh and torus, so a mesh
    was credited with wrap links it does not have."""
    from veritx_dse.model.presets import Topology, lookup_topo
    mesh = Topology("mesh_8x8", "mesh", "min_adapt", {"k": 8, "n": 2})
    torus = Topology("torus_8x8", "torus", "dim_order", {"k": 8, "n": 2})
    assert mesh.edges() == 112
    assert torus.edges() == 128
    assert mesh.edges() != torus.edges()
    m = lookup_topo("gec_mesh_k8")
    assert m.params.get("mesh") == 1 and m.edges() == 112

def test_lin_2d_presets_reclamation_is_recorded():
    audit = (Path(__file__).parents[4]
             / "docs/product/SOURCE-LINEAGE-AUDIT.md").read_text()
    assert "model/presets.py" in audit
    assert "parallel_world_size" in audit
    assert "silent duplicate of `gec_express_k8`" in audit

def test_lin_3_reclaimed_route_artifact_functions_exist():
    from veritx_dse.core.route_artifact import (
        RouteArtifact, route_entries_from_adj, topology_hash_from_adj,
        standalone_channel_dst, first_hop_table, artifact_from_anynet,
        equivalence_report, upgrade_v1_to_v2, compare_first_hop_tables,
    )
    adj = {0: {1, 2}, 1: {0, 3}, 2: {0, 3}, 3: {1, 2}}
    art = RouteArtifact.from_adjacency(adj, name="t")
    cdst = standalone_channel_dst(adj)
    fh = first_hop_table(art, cdst)
    assert equivalence_report(art, fh, channel_dst=cdst)["status"] \
        == "COMPARABLE"
    assert compare_first_hop_tables(fh, fh)["status"] == "COMPARABLE"
    assert topology_hash_from_adj(adj) == art.topology_hash
    assert callable(artifact_from_anynet) and callable(upgrade_v1_to_v2)
    assert route_entries_from_adj(adj) == fh

def test_lin_3b_public_name_aliases_the_private_one():
    """One implementation, two names — never two implementations."""
    from veritx_dse.core.route_artifact import (
        route_entries_from_adj, _route_entries_from_adj,
    )
    assert _route_entries_from_adj is route_entries_from_adj

def test_lin_3c_current_hardening_survived_the_merge():
    """The strong ancestor was NOT a strict superset: the current tree had
    later hardening that a wholesale replace would have destroyed."""
    from types import MappingProxyType
    from veritx_dse.core.errors import SemanticError
    from veritx_dse.core.route_artifact import (
        RouteArtifact, RouteArtifactError, RoutingClassDefinition,
    )
    assert issubclass(RouteArtifactError, SemanticError)
    d = RoutingClassDefinition(id="X", algorithm="a", algorithm_version=1,
                               parameters=(("k", [1, 2]),))
    assert d.parameters == (("k", (1, 2)),)
    adj = {0: {1}, 1: {0}}
    art = RouteArtifact.from_adjacency(adj, name="t")
    assert isinstance(art.entries, MappingProxyType)
    before = art.artifact_hash
    adj[0].add(99)
    assert art.artifact_hash == before

def test_lin_3d_comparison_has_one_authority():
    """route_observation must DELEGATE the verdict, not re-implement it."""
    src = (Path(__file__).parent.parent
           / "veritx_dse/backend/route_observation.py").read_text()
    assert "compare_first_hop_tables" in src
    assert "mismatches = [" not in src
    assert "missing = sorted(set(expected) - set(executed))" not in src

def test_lin_3e_deadlock_routing_from_adjacency_caller_resolves():
    """tools/deadlock_routing.py:426 already called from_adjacency while
    the constructor did not exist — a live AttributeError."""
    from veritx_dse.core.route_artifact import RouteArtifact
    assert hasattr(RouteArtifact, "from_adjacency")

def test_lin_3f_anynet_min_hops_identity_is_pinned():
    """CUSTOM must route with the SEALED executable class; the earlier
    WEIGHTED_SHORTEST_PATH choice is what cost the backend."""
    from veritx_dse.model.routing import _POLICY_BY_FAMILY
    from veritx_dse.model.topology_artifact import MaterializedFamily
    from veritx_dse.core.route_artifact import ANYNET_MIN_HOPS
    assert _POLICY_BY_FAMILY[MaterializedFamily.CUSTOM] == ANYNET_MIN_HOPS

def _audit_text():
    return (Path(__file__).parents[4]
            / "docs/product/SOURCE-LINEAGE-AUDIT.md").read_text()

def test_lin_4_phase_3_rerun_is_recorded_with_its_candidates():
    """The re-run must name its discriminator and every candidate, so the
    residual can be re-checked instead of assumed."""
    audit = _audit_text()
    assert "PHASE 3 — first re-run of the source-lineage audit" in audit
    assert "PHASE 3.1 — semantic closure of the body-level residual" in audit
    assert "Blob identity" in audit
    for cand in ("application/service.py", "simulation/model_to_trace.py",
                 "simulation/traces.py", "synthesis/iterative_synthesizer.py",
                 "synthesis/bo_synthesizer.py", "core/logging.py",
                 "application/resources.py", "application/store.py",
                 "reports/artifact.py", "reports/reports.py",
                 "backend/contracts.py", "synthesis/event_objective.py",
                 "simulation/trace_to_binary.py", "cli/pipeline.py",
                 "__init__.py"):
        assert cand in audit, f"{cand} must stay in the record"

def test_lin_4b_the_retracted_verdict_is_marked_retracted():
    """PHASE 3 claimed '0 unresolved weaker-ancestor regressions' from a
    symbol-set-only check. That claim was wrong and must stay visibly
    retracted, not quietly reworded."""
    audit = _audit_text()
    assert "Verdict of the first re-run — RETRACTED" in audit
    assert "Both sentences were wrong" in audit
    assert "**OPEN-BLOCKER** | **0**" in audit
    assert "OPEN-BLOCKER = 0" in audit

def test_lin_4c_supersession_claims_name_their_successor():
    """A SUPERSEDED classification without a named successor is a guess."""
    audit = _audit_text()
    assert "product/service.py::ProductService" in audit
    assert "workload/lowering.py:41" in audit
    assert "SynthesisTrafficMatrix" in audit
    assert "presets.topo_size" in audit
    assert "application/comparison" in audit
    assert "LEGACY_INTERNAL" in audit

def test_lin_4d_reclaimed_files_left_the_candidate_set():
    """PHASE 1/2 changed the blobs, so those files must no longer be
    identical to integration/canonical — the discriminator must agree."""
    import subprocess
    repo = Path(__file__).parents[4]
    for rel in ("tracks/t3-topology/dse/veritx_dse/synthesis/milp_topology_v2.py",
                "tracks/t3-topology/dse/veritx_dse/model/presets.py",
                "tracks/t3-topology/dse/veritx_dse/core/route_artifact.py"):
        cur = subprocess.run(["git", "rev-parse", f"HEAD:{rel}"], cwd=repo,
                             capture_output=True, text=True).stdout.strip()
        can = subprocess.run(["git", "rev-parse", f"integration/canonical:{rel}"],
                             cwd=repo, capture_output=True, text=True).stdout.strip()
        assert cur and can and cur != can, (
            f"{rel} is still byte-identical to integration/canonical — the "
            "reclamation did not land")

def test_lin_4e_phase_3_1_counts_are_exact():
    """The corrected record must state counts, not prose."""
    audit = _audit_text()
    assert "Exact counts over the 15 audited weaker-ancestor candidates" in audit
    for row in ("| RECLAIM | **4** |", "| CURRENT-STRONGER | **3** |",
                "| SUPERSEDED-BY-NAMED-AUTHORITY | **5** |",
                "| INTENTIONAL-REMOVAL | **1** |",
                "| COSMETIC / DOCUMENTATION | **2** |",
                "| **TOTAL** | **15** |"):
        assert row in audit, f"missing count row: {row}"

def test_lin_4f_all_six_body_level_files_are_dispositioned():
    """PHASE 3 left SIX files as 'NO STRONG-ONLY SYMBOL'. Each must now
    carry a real body-level disposition, not that placeholder."""
    audit = _audit_text()
    section = audit.split("**Body-level disposition of the six residual files**")[1]
    section = section.split("**Exact counts")[0]
    for f in ("`reports/artifact.py`", "`cli/pipeline.py`",
              "`reports/reports.py`", "`backend/contracts.py`",
              "`synthesis/event_objective.py`", "`simulation/trace_to_binary.py`"):
        assert f in section, f"{f} has no body-level disposition row"
    for disp in ("**RECLAIM**", "**CURRENT-STRONGER (proven)**",
                 "**COSMETIC**"):
        assert disp in section

def test_lin_5_audit_claims_match_the_code():
    """The audit document is EVIDENCE, not decoration. A PHASE-2 claim
    ("the stale routing diagnostic was fixed") was false while the prose
    said otherwise, so each headline claim is now checked against code."""
    import inspect
    from veritx_dse.synthesis import milp_topology_v2 as milp
    from veritx_dse.core.constants import DEFAULT_K
    assert "isfinite" in inspect.getsource(milp.load_matrix)
    assert inspect.signature(milp.solve_tmcf).parameters["timeout"].default is None
    assert milp.DEFAULT_K == DEFAULT_K

    from veritx_dse.model.presets import (
        topo_size, parallel_world_size, resolve_fabric, count_anynet_edges,
        anynet_usability, SWEEP_TOPOS, WORKLOAD_PRESETS, Topology,
    )
    assert topo_size("mesh", {"k": 8, "n": 2}) == (64, 112)
    assert parallel_world_size(2, 2, 4, 1) == 16
    assert resolve_fabric("mesh_8x8")[0] is not None
    assert "from ..core.anynet import" in inspect.getsource(count_anynet_edges)

    from veritx_dse.core.errors import SemanticError
    from veritx_dse.core import route_artifact as ra
    for fn in ("equivalence_report", "artifact_from_anynet", "upgrade_v1_to_v2",
               "topology_hash_from_adj", "standalone_channel_dst",
               "first_hop_table", "compare_first_hop_tables"):
        assert callable(getattr(ra, fn)), f"{fn} missing"
    assert hasattr(ra.RouteArtifact, "from_adjacency")
    assert issubclass(ra.RouteArtifactError, SemanticError)

    assert len(SWEEP_TOPOS) == 7
    for absent in ("fbfly_64", "cmesh_64", "fattree_k4n3", "qtree_64",
                   "tree4_64", "dragonfly_72"):
        assert all(t.name != absent for t in SWEEP_TOPOS)

    for p in WORKLOAD_PRESETS.values():
        assert "collectives" not in p.get("workload", {})

    from veritx_dse.core import constants as C
    from veritx_dse.model import compile_model as M
    assert M.PLANE_C_MAX_VC is C.PLANE_C_MAX_VC

    from veritx_dse.model.routing import routing_policy_for, _POLICY_BY_FAMILY
    from veritx_dse.model.topology_artifact import MaterializedFamily
    from veritx_dse.core.route_artifact import ANYNET_MIN_HOPS, RouteArtifactError

    class _T:
        def __init__(self, fam):
            self.family = fam

    assert routing_policy_for(_T(MaterializedFamily.CUSTOM)) == ANYNET_MIN_HOPS
    from veritx_dse.core.route_artifact import DOR_TORUS_XY
    assert routing_policy_for(_T(MaterializedFamily.TORUS)) == DOR_TORUS_XY
    with pytest.raises(RouteArtifactError) as e:
        routing_policy_for(_T(MaterializedFamily.RING))
    assert "custom -> ANYNET_MIN_HOPS" in str(e.value)

    from veritx_dse.reports import artifact as art
    assert not hasattr(art, "_DEFAULT_SECRET")
    assert issubclass(art.MissingSigningKey, TypeError)
    assert callable(art.DesignManifest.create_unsigned)

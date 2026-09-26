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


# ══ LIN-10: the hardened MILP loader is reclaimed ═════════════════════

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
    # The typed artifact carries something the loader does not: source
    # provenance. That is why it remains the authority.
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


# ══ LIN-1: a stronger ancestor cannot be silently replaced ════════════

def test_lin_1_route_artifact_gap_is_recorded_not_silently_accepted():
    """The strongest historical route_artifact.py carries functions the
    current tree lacks (equivalence_report, artifact_from_anynet,
    upgrade_v, ...). The gap is a recorded blocker, and this test fails if
    someone closes it without updating the record — or silently drops it."""
    audit = (Path(__file__).parents[4]
             / "docs/product/SOURCE-LINEAGE-AUDIT.md").read_text()
    for fn in ("equivalence_report", "artifact_from_anynet", "upgrade_v"):
        assert fn in audit, f"{fn} must stay recorded as missing"
    assert "NEEDS_RECONCILIATION" in audit
    # And the locally invented comparator is named as a duplicate.
    assert "route_observation.py" in audit
    assert "locally invented" in audit


def test_lin_1b_authority_selection_law_is_documented():
    audit = (Path(__file__).parents[4]
             / "docs/product/SOURCE-LINEAGE-AUDIT.md").read_text()
    assert "does NOT mean" in audit
    assert "strongest historical source implementation" in audit


# ══ LIN-2: the presets authorities are reclaimed, not re-invented ═════

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
    # The >=5-token inline parser must be gone.
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
    # gec_mesh_k8 must not be a silent express duplicate.
    m = lookup_topo("gec_mesh_k8")
    assert m.params.get("mesh") == 1 and m.edges() == 112


def test_lin_2d_presets_reclamation_is_recorded():
    audit = (Path(__file__).parents[4]
             / "docs/product/SOURCE-LINEAGE-AUDIT.md").read_text()
    assert "model/presets.py" in audit
    assert "parallel_world_size" in audit
    assert "silent duplicate of `gec_express_k8`" in audit

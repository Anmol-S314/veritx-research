"""FabricIntentView normalization across v2/v3/v4 (PHASE B.1 §15–§17).

The load-bearing properties:

  * ONE dispatch seam serves every generation, and it always yields a
    normalized typed `topology` — the topology stage reads THAT, never legacy
    `topology_family`/`radix`/`concentration`;
  * normalizing a legacy request is TRANSIENT: it cannot move a persisted
    identity, because the view is not serializable and its `design_hash` is
    copied verbatim;
  * the same topology science produces the same artifact whether it arrives
    as v3 or as v4.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).parent.parent
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

from veritx_dse.model.compile_model import (  # noqa: E402
    CompileRequestV3, TopologyFamily, fabric_intent_view,
)
from veritx_dse.model.compile_request_v4 import migrate_v3_to_v4  # noqa: E402
from veritx_dse.model.generation import (  # noqa: E402
    generation_of, is_any_compile_request, is_v4_request,
)
from veritx_dse.model.topology_artifact import (  # noqa: E402
    MaterializedFamily, materialize_topology, materialize_topology_intent,
)
from veritx_dse.model.topology_intent import (  # noqa: E402
    FatTreeIntent, GecMode, GecTopologyIntent, MeshIntent,
)

EX = REPO / "tracks/t3-topology/examples"

def _v3(**noc):
    d = json.loads((EX / "dense_1b_16tiles-v3.json").read_text())
    d.pop("design_hash", None)
    d.pop("guardrail_hash", None)
    d["agents"] = [{"kind": "compute_tile", "count": 16, "data_width": 256,
                    "addr_width": 64, "protocol": "AXI"}]
    d["noc_config"] = dict(d["noc_config"])
    d["noc_config"].update(noc)
    return CompileRequestV3.from_dict(d)

def test_generation_predicate_recognises_every_generation():
    v3 = _v3(topology_family="mesh", radix=4, concentration=None)
    v4 = migrate_v3_to_v4(v3)
    assert generation_of(v3) == "v3"
    assert generation_of(v4) == "v4"
    assert is_any_compile_request(v3) and is_any_compile_request(v4)
    assert is_v4_request(v4) and not is_v4_request(v3)
    assert not is_any_compile_request({"not": "a request"})

def test_the_view_always_carries_a_typed_topology():
    for req in (_v3(topology_family="mesh", radix=4, concentration=None),
                _v3(topology_family="torus", radix=4, concentration=None),
                _v3(topology_family="concentrated_mesh", radix=2,
                    concentration=4)):
        view = fabric_intent_view(req)
        assert view.topology is not None
        assert view.source_generation == "v3"

def test_v4_view_carries_the_declared_intent_verbatim():
    v4 = migrate_v3_to_v4(_v3(topology_family="mesh", radix=2,
                              concentration=None))
    view = fabric_intent_view(v4)
    assert view.source_generation == "v4"
    assert view.topology == v4.topology
    assert view.noc_controls is v4.noc_controls
    assert view.noc_config is None

def test_normalization_is_transient_and_cannot_move_an_identity():
    """The view has no to_dict/from_dict and copies design_hash verbatim, so
    a legacy document's persisted identity cannot change because of it."""
    req = _v3(topology_family="mesh", radix=4, concentration=None)
    view = fabric_intent_view(req)
    assert view.design_hash == req.design_hash()
    assert not hasattr(view, "to_dict")
    assert view.topology_normalization is not None

def test_legacy_implicit_mesh_normalizes_with_the_frozen_sizing_law():
    req = _v3(topology_family=None, radix=None, concentration=None)
    view = fabric_intent_view(req)
    assert view.topology == MeshIntent(side_length=4, concentration=1)
    assert "frozen_v3_autosize" in \
        view.topology_normalization["radix_resolution"]

def test_normalization_REFUSES_a_family_the_legacy_spelling_cannot_express():
    with pytest.raises(Exception, match="does not determine"):
        fabric_intent_view(_v3(topology_family="gec", radix=8,
                               concentration=1))

def _inv(n=16):
    """A real NodeInventory with `n` agents (the materializers read
    `agent_count`, which is a derived property of the agent universe)."""
    from veritx_dse.model.placement import (AgentInstance, NodeInventory,
                                            ParallelismShape)
    from veritx_dse.model.compile_model import AgentKind
    from veritx_dse.model.placement import LogicalRank, coords_of
    agents = tuple(AgentInstance(group_index=0, instance_index=i,
                                 kind=AgentKind.COMPUTE_TILE)
                   for i in range(n))
    shape = ParallelismShape(tp=1, pp=1, ep=1, dp=n)
    ranks = tuple(LogicalRank(rank=r, **coords_of(r, tp=1, pp=1, ep=1, dp=n))
                  for r in range(shape.world_size))
    return NodeInventory(parallelism=shape, agents=agents, ranks=ranks)

def test_materialization_seam_maps_supported_families():
    assert materialize_topology_intent(_inv(16), MeshIntent(side_length=4)) \
        .family.value == "mesh"
    assert materialize_topology_intent(
        _inv(16), __import__("veritx_dse.model.topology_intent",
                             fromlist=["TorusIntent"]).TorusIntent(
                                 side_length=4)).family.value == "torus"

def test_materialization_seam_materializes_gec_families():
    mesh = materialize_topology_intent(
        _inv(64), GecTopologyIntent(
            mode=GecMode.MESH, grid_side_length=8, concentration=1))
    assert mesh.family is MaterializedFamily.MESH

    mecs = materialize_topology_intent(_inv(64), GecTopologyIntent(
        mode=GecMode.MULTIDROP, grid_side_length=8, concentration=1,
        express_channel_groups_per_dimension=1,
        destinations_per_express_channel=7))
    assert mecs.family is MaterializedFamily.GEC_MECS
    assert mecs.shared_links

    hybrid = materialize_topology_intent(_inv(64), GecTopologyIntent(
        mode=GecMode.HYBRID, grid_side_length=8, concentration=1,
        express_channel_groups_per_dimension=1,
        destinations_per_express_channel=7))
    assert hybrid.family is MaterializedFamily.GEC_HYBRID
    assert hybrid.shared_links

    express = materialize_topology_intent(_inv(64), GecTopologyIntent(
        mode=GecMode.EXPRESS, grid_side_length=8, concentration=1,
        express_channel_groups_per_dimension=7,
        destinations_per_express_channel=1))
    assert express.family is MaterializedFamily.GEC_EXPRESS

def test_materialization_seam_materializes_fattree():
    """Was `REFUSES_fattree_by_name` while the materializer was later-phase
    work. That refusal said so itself: "no canonical materializer YET ...
    materialization is later-phase work". This is that phase — the intent now
    yields the canonical k-ary L-level fat-tree graph (L * k^(L-1) routers,
    every one of degree k).

    It materializes through the generic materialize-IR seam, so the artifact
    records family CUSTOM: MaterializedFamily has no FAT_TREE member. The
    graph is right; the family LABEL is the remaining gap.
    """
    art = materialize_topology_intent(_inv(16),
                                      FatTreeIntent(switch_radix=4,
                                                    level_count=2))
    assert art.router_count == 8          # level_count * k^(level_count - 1)
    assert art.family is MaterializedFamily.CUSTOM

def test_legacy_and_v4_materialize_the_SAME_science():
    """The seam is a normalization, not a reinterpretation: v3 and the v4
    migrated from it must produce the same topology artifact."""
    v3 = _v3(topology_family="mesh", radix=4, concentration=None)
    v4 = migrate_v3_to_v4(v3)
    inv = _inv(16)
    a = materialize_topology(inv, fabric_intent_view(v3))
    b = materialize_topology(inv, fabric_intent_view(v4))
    assert a.family == b.family
    assert a.router_count == b.router_count
    assert a.topology_hash() == b.topology_hash()

def test_topology_materialization_path_does_not_read_legacy_shape():
    """After the seam, topology materialization must not inspect legacy
    topology_family/radix/concentration. Checked at SOURCE level against the
    seam and the family materializers it delegates to."""
    src = (DSE / "veritx_dse/model/topology_artifact.py").read_text()
    start = src.index("def materialize_topology_intent(")
    end = src.index("def materialize_topology(", start)
    body = src[start:end]
    for legacy in ("topology_family", "noc_config.radix",
                   "noc_config.concentration"):
        assert legacy not in body, (
            f"materialize_topology_intent reads legacy {legacy!r}: the typed "
            "intent is the authority")

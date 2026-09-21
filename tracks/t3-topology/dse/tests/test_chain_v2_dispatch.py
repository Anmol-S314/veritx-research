"""tests/test_chain_v2_dispatch.py — M1.5: the re-derivation dispatch, PROVEN.

`chain_ids_from_traffic` is generation-dispatched, but its v2 branch was
exercised only through v1 traffic — the same gap seam 0.1 had. This test
drives real v1 and real v2 artifacts through the one dispatcher and pins
what each returns, so M1.6's writer switch cannot land on an unproven
branch.
"""
from __future__ import annotations

import sys
from pathlib import Path

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_physical_traffic_v2 import bundle as bundle_v2  # noqa: E402
from test_physical_traffic_v2 import graph as graph_v2  # noqa: E402
from test_wave_d_physical import _bundle, _logical  # noqa: E402

from veritx_dse.application.waved_resources import (  # noqa: E402
    CHAIN_SCHEMA_VERSION_V2, chain_ids_from_traffic, chain_version,
)
from veritx_dse.workload.messages import (  # noqa: E402
    LogicalMessageArtifactV2,
)
from veritx_dse.workload.traffic import (  # noqa: E402
    PhysicalTrafficArtifact, PhysicalTrafficArtifactV2,
)


def v1_traffic():
    b = _bundle()
    logical = _logical(b)
    return PhysicalTrafficArtifact(logical=logical, bundle=b)


def v2_traffic():
    g = graph_v2(4)
    logical = LogicalMessageArtifactV2(g)
    return PhysicalTrafficArtifactV2(logical=logical, bundle=bundle_v2())


def test_v1_traffic_rederives_the_wave_d_chain():
    chain = chain_ids_from_traffic(v1_traffic())
    assert chain_version(chain) == 1
    assert "chain_schema_version" not in chain
    assert "operation_graph_id" in chain
    assert "workload_graph_id" not in chain


def test_v2_traffic_rederives_the_canonical_chain():
    traffic = v2_traffic()
    chain = chain_ids_from_traffic(traffic)
    assert chain["chain_schema_version"] == CHAIN_SCHEMA_VERSION_V2
    assert chain["workload_graph_id"] == \
        traffic.logical.graph.workload_id()
    assert chain["message_artifact_id"] == \
        traffic.logical.message_artifact_id()
    assert chain["physical_traffic_id"] == traffic.physical_traffic_id()
    assert "operation_graph_id" not in chain
    assert "waved_workload_id" not in chain
    assert "wave_d_semantics_id" not in chain


def test_the_two_chains_share_products_but_not_parents():
    """v2 proves the new ancestry, never the ghosts of the old one.

    Both generations name the *products* by artifact id (messages,
    traffic) — those keys are shared by design. The *parents* must not
    be: v1 names operation_graph_id, v2 names workload_graph_id, and
    the product values differ because each generation computes its own
    identities.
    """
    c1 = chain_ids_from_traffic(v1_traffic())
    c2 = chain_ids_from_traffic(v2_traffic())
    assert "operation_graph_id" in c1 and "workload_graph_id" not in c1
    assert "workload_graph_id" in c2 and "operation_graph_id" not in c2
    assert "waved_workload_id" not in c2
    assert "wave_d_semantics_id" not in c2
    for key in ("message_artifact_id", "physical_traffic_id"):
        assert key in c1 and key in c2
        assert c1[key] != c2[key]

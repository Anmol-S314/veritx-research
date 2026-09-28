"""Torus dump-harness patch: injection-port query + tie carve-out.

REGRESSION CONTEXT: the fork dump harness queried routing functions with
in_channel=-1. For dor_next_torus, (-1/2)==0 takes the straight-through
branch and returns port -2, so NO torus first-hop table could ever be
dumped (refusal verbatim: "returned port -2 outside [0,5)"). The patch
queries as if injected at the router (2*gN, the fork's own injection
convention) for the cube family + channel-ignorers, keeping the legacy
-1 query for fattree/qtree/tree4/gec (different injection indexing;
their dumps are uncertified).

EPISTEMIC STATUS: backend-level execution evidence (dump produced by the
real binary, compared against the canonical sealed table). Dump
equivalence is first-hop realization only, never packet-path observation.
Midpoint ties on even k resolve randomly in the fork and are OUT OF
SCOPE via the exact dor_torus_xy_tie_flows() carve-out — never claimed.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.core.paths import REPO  # noqa: E402

BINARY = REPO / "third_party/booksim2/src/booksim"
needs_binary = pytest.mark.skipif(
    not (BINARY.exists() and shutil.which("true")),
    reason="vendored BookSim binary not built")


def _run(cfg_text: str, tmp_path: Path) -> subprocess.CompletedProcess:
    cfg = tmp_path / "run.cfg"
    cfg.write_text(cfg_text)
    return subprocess.run(
        [str(BINARY), str(cfg)], cwd=tmp_path, capture_output=True,
        text=True, timeout=300)


_MESH_CFG = """topology = mesh;
k = 4;
n = 2;
routing_function = dim_order;
routing_dump_file = mesh.dump;
use_noc_latency = 0;
num_vcs = 2;
traffic = uniform;
sim_count = 10;
injection_rate = 0.01;
packet_size = 1;
"""

_TORUS5_CFG = """topology = torus;
k = 5;
n = 2;
routing_function = dim_order;
routing_dump_file = torus.dump;
use_noc_latency = 0;
num_vcs = 2;
traffic = uniform;
sim_count = 10;
injection_rate = 0.01;
packet_size = 1;
"""

_TORUS4_CFG = """topology = torus;
k = 4;
n = 2;
routing_function = dim_order;
routing_dump_file = torus4.dump;
use_noc_latency = 0;
num_vcs = 2;
traffic = uniform;
sim_count = 10;
injection_rate = 0.01;
packet_size = 1;
"""

_FATTREE_CFG = """topology = fattree;
k = 4;
n = 2;
routing_function = nca;
routing_dump_file = ft.dump;
use_noc_latency = 0;
num_vcs = 2;
traffic = uniform;
sim_count = 10;
injection_rate = 0.01;
packet_size = 1;
"""


def test_patch_queries_the_injection_port_per_topology():
    """Guard against silent revert of the harness fix (owned files)."""
    src = (REPO / "third_party/booksim2/src/networks/network.cpp"
           ).read_text()
    assert "query_port = 2*gN" in src
    assert "query_port," in src or "query_port," in src.replace(" ", "")
    hpp = (REPO / "third_party/booksim2/src/networks/network.hpp"
           ).read_text()
    assert "int query_port" in hpp


@needs_binary
def test_mesh_dump_matches_canonical_dor_xy(tmp_path):
    """The new query path is faithful where the old one worked: mesh
    matches the canonical DOR_XY table over every flow."""
    from veritx_dse.backend.route_observation import (  # noqa: E402
        expected_route_rows, parse_route_dump,
    )
    from veritx_dse.core.route_artifact import (  # noqa: E402
        DOR_XY, RouteArtifact, compare_first_hop_tables,
    )
    from veritx_dse.model.topology_artifact import (  # noqa: E402
        MaterializedFamily, materialize_family,
    )

    proc = _run(_MESH_CFG, tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    f = materialize_family(MaterializedFamily.MESH, endpoint_count=16,
                           radix=4)
    r = RouteArtifact.from_topology(f, name="m4",
                                    routing_classes=(DOR_XY,))
    rows = expected_route_rows(routing_class=DOR_XY, topology=f, route=r,
                               node_to_router={n: n for n in range(16)})
    dump = parse_route_dump((tmp_path / "mesh.dump").read_text())
    report = compare_first_hop_tables({(s, d): n for s, d, n in rows},
                                      dump)
    assert report["status"] == "COMPARABLE", report["mismatched"][:5]
    assert report["coverage"]["matched"] == 256


@needs_binary
def test_torus_k5_dump_matches_canonical_on_all_flows(tmp_path):
    """k=5 is odd: the tie carve-out is empty, so all 625 flows are
    COMPARABLE — full first-hop equivalence, zero mismatches."""
    from veritx_dse.backend.route_observation import (  # noqa: E402
        expected_route_rows, parse_route_dump,
    )
    from veritx_dse.core.route_artifact import (  # noqa: E402
        DOR_TORUS_XY, RouteArtifact, compare_first_hop_tables,
        dor_torus_xy_tie_flows,
    )
    from veritx_dse.model.topology_artifact import (  # noqa: E402
        MaterializedFamily, materialize_family,
    )

    proc = _run(_TORUS5_CFG, tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    f = materialize_family(MaterializedFamily.TORUS, endpoint_count=25,
                           radix=5)
    assert len(dor_torus_xy_tie_flows(f)) == 0
    r = RouteArtifact.from_topology(f, name="t5",
                                    routing_classes=(DOR_TORUS_XY,))
    rows = expected_route_rows(routing_class=DOR_TORUS_XY, topology=f,
                               route=r,
                               node_to_router={n: n for n in range(25)})
    dump = parse_route_dump((tmp_path / "torus.dump").read_text())
    report = compare_first_hop_tables({(s, d): n for s, d, n in rows},
                                      dump)
    assert report["status"] == "COMPARABLE", report["mismatched"][:5]
    assert report["coverage"]["matched"] == 625


@needs_binary
def test_torus_k4_midpoint_tie_refuses_cleanly_inside_carve_out(tmp_path):
    """Even-k midpoint ties resolve randomly in the fork: the harness
    must refuse naming determinism (never crash, never a false table),
    and the refused flow must lie in the canonical carve-out set."""
    from veritx_dse.core.route_artifact import (  # noqa: E402
        dor_torus_xy_tie_flows,
    )
    from veritx_dse.model.topology_artifact import (  # noqa: E402
        MaterializedFamily, materialize_family,
    )

    proc = _run(_TORUS4_CFG, tmp_path)
    assert proc.returncode != 0
    assert "no deterministic first-hop table" in proc.stderr
    assert "port -2" not in proc.stderr
    m = re.search(r"\(router,dst\)=\((\d+),(\d+)\)", proc.stderr)
    assert m is not None, proc.stderr[-500:]
    f = materialize_family(MaterializedFamily.TORUS, endpoint_count=16,
                           radix=4)
    assert (int(m.group(1)), int(m.group(2))) in dor_torus_xy_tie_flows(f)


def test_torus_tie_carve_out_is_exact():
    """Every carve-out flow is a genuine even-k midpoint tie (X-first
    dimension order: X tie, else same-column Y tie); odd k is empty."""
    from veritx_dse.core.route_artifact import (  # noqa: E402
        dor_torus_xy_tie_flows,
    )
    from veritx_dse.model.topology_artifact import (  # noqa: E402
        MaterializedFamily, materialize_family,
    )

    f5 = materialize_family(MaterializedFamily.TORUS, endpoint_count=25,
                            radix=5)
    assert dor_torus_xy_tie_flows(f5) == frozenset()
    f4 = materialize_family(MaterializedFamily.TORUS, endpoint_count=16,
                            radix=4)
    ties = dor_torus_xy_tie_flows(f4)
    assert len(ties) > 0
    coords = {r.router_id: (r.coordinates[0], r.coordinates[1])
              for r in f4.routers}
    for src, dst in ties:
        x, y = coords[src]
        dx, dy = coords[dst]
        assert src != dst
        assert (x != dx and (dx - x) % 4 == 2) or (
            x == dx and y != dy and (dy - y) % 4 == 2), (src, dst)


@needs_binary
def test_fattree_dump_never_certifies_and_never_aborts(tmp_path):
    """Fattree keeps the legacy query: RNG refusal (never a table), and
    crucially no assert-abort — a crash must never replace a refusal."""
    proc = _run(_FATTREE_CFG, tmp_path)
    assert proc.returncode != 0
    assert "Assertion" not in proc.stderr
    assert "no deterministic first-hop table" in proc.stderr

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.backend.route_observation import (  # noqa: E402
    parse_route_dump_rows,
)
from veritx_dse.model.shared_resource import ResourceKind  # noqa: E402
from veritx_dse.verification.gec_hybrid_candidate_cdg import (  # noqa: E402
    GecHybridCandidateError,
    GecHybridParams,
    build_gec_hybrid_candidate_cdg,
    gec_hybrid_candidates,
    select_gec_hybrid_candidate,
)


def test_candidate_pair_matches_hybrid_gec_ports_tap_and_phase_vcs():
    params = GecHybridParams(k=4, c=1, o=1, d=3, num_vcs=6)
    mesh, mecs = gec_hybrid_candidates(
        params, src_router=0, dest_node=3)

    assert mesh.is_mesh and mesh.next_router == 1
    assert mesh.phase == 0 and mesh.vcs == (0, 1, 2)
    assert mesh.out_port == 1
    assert mecs.resource.kind is ResourceKind.SHARED_LINK
    assert mecs.next_router == 3 and mecs.tap == 2
    assert mecs.phase == 0 and mecs.vcs == (2,)
    assert mecs.out_port == 3


def test_column_candidates_use_upper_phase_vcs():
    params = GecHybridParams(k=4, c=1, o=1, d=3, num_vcs=6)
    mesh, mecs = gec_hybrid_candidates(
        params, src_router=0, dest_node=12)
    assert mesh.phase == mecs.phase == 1
    assert mesh.vcs == (3, 4, 5)
    assert mecs.vcs == (5,)
    assert mecs.next_router == 12


@pytest.mark.parametrize("mesh,mecs,hops,expected", [
    (1, 5, 2, "mesh"),
    (3, 4, 2, "mecs"),
    (2, 4, 2, "mecs"),  # tie goes to MECS
])
def test_selector_matches_credit_cost_rule(mesh, mecs, hops, expected):
    assert select_gec_hybrid_candidate(
        mesh_used_credit=mesh, mecs_used_credit=mecs,
        mesh_hops=hops) == expected


def test_candidate_union_is_acyclic_on_small_conformant_instances():
    # Exhaust small tap packings, concentrations, and floor-compatible VC
    # counts. This is per-instance evidence, not a general closed-form proof.
    for k in range(3, 8):
        for d in range(1, k):
            if (k - 1) % d:
                continue
            o = (k - 1) // d
            for c in (1, 2):
                for num_vcs in (2 * d, 2 * d + 1):
                    params = GecHybridParams(
                        k=k, c=c, o=o, d=d, num_vcs=num_vcs)
                    cdg = build_gec_hybrid_candidate_cdg(params)
                    assert cdg.candidate_count > 0
                    assert cdg.find_cycle() is None, (
                        k, o, d, c, num_vcs, cdg.find_cycle())


def test_candidate_union_preserves_odd_vc_tail_as_unused():
    params = GecHybridParams(k=4, c=1, o=1, d=3, num_vcs=7)
    assert params.phase_vcs == ((0, 1, 2), (3, 4, 5))
    assert 6 not in set(params.phase_vcs[0] + params.phase_vcs[1])


def test_hybrid_requires_source_vc_floor():
    with pytest.raises(GecHybridCandidateError, match="num_vcs"):
        GecHybridParams(k=4, c=1, o=1, d=3, num_vcs=5)


def test_zero_credit_runtime_dump_matches_mecs_tie_choice(tmp_path):
    binary = DSE.parents[2] / "third_party/booksim2/src/booksim"
    if not binary.is_file():
        pytest.skip("no built BookSim binary in tree")
    dump = tmp_path / "hybrid.dump"
    config = tmp_path / "hybrid.cfg"
    config.write_text(f"""topology = gec;
routing_function = hybrid_gec;
k = 4;
c = 1;
o = 1;
d = 3;
mesh = 0;
hybrid = 1;
num_vcs = 6;
use_noc_latency = 0;
routing_dump_file = {dump.name};
traffic = uniform;
injection_rate = 0.001;
packet_size = 2;
sim_type = latency;
""")
    subprocess.run([str(binary), config.name], cwd=tmp_path,
                   capture_output=True, text=True, check=True, timeout=120)
    rows = parse_route_dump_rows(dump.read_text())
    params = GecHybridParams(k=4, c=1, o=1, d=3, num_vcs=6)
    assert len(rows) == params.router_count * params.node_count
    for (src, dest), row in rows.items():
        candidates = gec_hybrid_candidates(
            params, src_router=src, dest_node=dest)
        if not candidates:
            assert row.next_router == src
            assert row.port == dest % params.c
            continue
        mecs = candidates[1]  # all credits are zero; tie selects MECS
        assert (row.port, row.drop, row.vc_start, row.vc_end,
                row.next_router) == (
                    mecs.out_port, mecs.tap, mecs.vcs[0], mecs.vcs[-1],
                    mecs.next_router)

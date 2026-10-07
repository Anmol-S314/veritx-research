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


def test_runtime_observations_match_credit_cost_choice(tmp_path):
    """Compare real selector inputs and outputs under nonzero traffic credits."""
    binary = DSE.parents[2] / "third_party/booksim2/src/booksim"
    if not binary.is_file():
        pytest.skip("no built BookSim binary in tree")
    observation = tmp_path / "hybrid.observations"
    config = tmp_path / "hybrid-runtime.cfg"
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
hybrid_gec_observation_file = {observation.name};
traffic = uniform;
injection_rate = 0.2;
packet_size = 2;
sim_type = latency;
sample_period = 200;
max_samples = 2;
seed = 0;
""")
    subprocess.run([str(binary), config.name], cwd=tmp_path,
                   capture_output=True, text=True, check=True, timeout=120)
    params = GecHybridParams(k=4, c=1, o=1, d=3, num_vcs=6)
    observed = []
    selected_modes = set()
    saw_nonzero_tie = False
    for line in observation.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        (src, dest, _in_channel, mesh_credit, mecs_credit, hops, mesh_cost,
         mecs_cost, selected, port, tap, vc_start, vc_end, phase) = \
            line.split()
        src, dest = int(src), int(dest)
        mesh_credit, mecs_credit, hops = (int(mesh_credit), int(mecs_credit),
                                          int(hops))
        mesh_cost, mecs_cost = int(mesh_cost), int(mecs_cost)
        assert mesh_cost == mesh_credit * hops
        assert mecs_cost == mecs_credit
        expected = select_gec_hybrid_candidate(
            mesh_used_credit=mesh_credit,
            mecs_used_credit=mecs_credit, mesh_hops=hops)
        assert selected == expected
        selected_modes.add(selected)
        if mesh_cost == mecs_cost and mesh_cost > 0:
            saw_nonzero_tie = True
            assert selected == "mecs"
        candidates = gec_hybrid_candidates(
            params, src_router=src, dest_node=dest)
        chosen = candidates[0] if selected == "mesh" else candidates[1]
        assert (int(port), int(tap), int(vc_start), int(vc_end)) == (
            chosen.out_port, chosen.tap if chosen.tap is not None else -1,
            chosen.vcs[0], chosen.vcs[-1])
        assert int(phase) == chosen.phase
        observed.append((mesh_credit, mecs_credit))
    assert observed, "the traffic run did not exercise hybrid routing"
    assert selected_modes == {"mesh", "mecs"}, selected_modes
    assert any(mesh or mecs for mesh, mecs in observed), (
        "the run produced no nonzero-credit selector observation")
    assert saw_nonzero_tie, "the run did not exercise a nonzero-cost tie"

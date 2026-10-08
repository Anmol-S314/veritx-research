"""Differential: the canonical SROTA rank union vs the simulator's dump.

The rank policy is the only one the fork accepts with Valiant enabled, and
its proof is a walk over every (source, destination, shape, Valiant
intermediate) route. This test runs the fork's own route dump under
``srota_vc_policy=rank`` and checks that the realized first hop is a member
of the canonical union — the same membership obligation the shape-policy
live test uses, because the runtime picks one realization of an adaptive
rule.

Kept separate from the row-first differential on purpose: row-first has ONE
realization per pair, so its comparison is equality; rank has many, so its
comparison is membership and the failure mode (a hop the union never
admitted) is different.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

from veritx_dse.backend.route_observation import (  # noqa: E402
    parse_route_dump_rows,
)
from veritx_dse.model.srota_rank_route import (  # noqa: E402
    rank_policy_route_for_srota,
)

_CONFIG = """\
topology = srota;
routing_function = o1turn;
k = {k};
c = {c};
srota_planes    = 5;
srota_mecs      = 3;
srota_path_en   = {path_en};
srota_vc_policy = rank;
srota_cdg_radix = {k};
srota_router       = sidebuf;
num_vcs            = {num_vcs};
vc_buf_size        = 2;
srota_sb_depth     = 8;
srota_sb_watermark = 6;
use_noc_latency = 0;
routing_dump_file = srota.dump;
traffic = uniform;
injection_rate = 0.01;
packet_size = 2;
sim_type = latency;
"""


def _booksim_bin() -> Path | None:
    candidate = REPO / "third_party" / "booksim2" / "src" / "booksim"
    if candidate.is_file():
        return candidate
    found = shutil.which("booksim")
    return Path(found) if found else None


def _run_dump(tmp: Path, *, k: int, c: int, path_en: int, num_vcs: int):
    binary = _booksim_bin()
    if binary is None:
        pytest.skip("no built BookSim binary in tree")
    tmp.mkdir(parents=True, exist_ok=True)
    dump = tmp / "srota.dump"
    cfg = tmp / "srota.cfg"
    cfg.write_text(_CONFIG.format(k=k, c=c, path_en=path_en,
                                  num_vcs=num_vcs))
    proc = subprocess.run([str(binary), cfg.name], cwd=tmp,
                          capture_output=True, text=True, timeout=600)
    assert dump.is_file(), (
        f"no routing dump (rc={proc.returncode})\n{proc.stdout[-2500:]}\n"
        f"{proc.stderr[-2500:]}")
    return parse_route_dump_rows(dump.read_text())


def _check(tmp: Path, *, k: int, c: int, shapes: frozenset[str],
           path_en: int, num_vcs: int) -> None:
    rows = _run_dump(tmp, k=k, c=c, path_en=path_en, num_vcs=num_vcs)
    route = rank_policy_route_for_srota(
        k=k, c=c, shapes=shapes, mecs_row=True, mecs_col=True,
        topology_hash="rank-differential")
    stride = c + 4
    mismatches: list[str] = []
    checked = 0
    for (src, node), options in route.choices.items():
        if src == node // c:
            # Local ejection: its VC set is whatever arrived, and the
            # fork's dump records the eject port rather than a rank hop.
            continue
        row = rows.get((src, node))
        assert row is not None, (src, node)
        actual = (row.port, row.drop, row.vc_start, row.vc_end,
                  row.next_router)
        expected = set()
        for d in options:
            port = d.resource.resource_id - src * stride
            vc = d.vc_partition
            expected.add((port, -1 if d.tap is None else d.tap, vc, vc,
                          d.next_router))
        checked += 1
        if actual not in expected:
            mismatches.append(
                f"router {src} -> node {node}: simulator "
                f"(port,drop,vc_lo,vc_hi,next)={actual} is not one of the "
                f"certified choices {sorted(expected)}")
    assert checked > 0
    assert not mismatches, (
        f"{len(mismatches)} of {checked} realized hops are not in the "
        f"certified union; first few:\n  " + "\n  ".join(mismatches[:8]))


@pytest.fixture(scope="module")
def _tmp_root(tmp_path_factory):
    return tmp_path_factory.mktemp("srota-rank-differential")


def test_rank_with_valiant_realizes_a_certified_hop(_tmp_root):
    # ROW|COL|VALIANT, four rank VC sets.
    _check(_tmp_root / "all", k=4, c=1,
           shapes=frozenset({"row", "column", "valiant"}),
           path_en=7, num_vcs=4)


def test_rank_without_valiant_uses_two_sets(_tmp_root):
    _check(_tmp_root / "direct", k=4, c=1,
           shapes=frozenset({"row", "column"}), path_en=3, num_vcs=2)


def test_rank_direct_shapes_on_a_concentrated_fabric(_tmp_root):
    _check(_tmp_root / "c2", k=4, c=2,
           shapes=frozenset({"row", "column"}), path_en=3, num_vcs=2)

"""Differential: the canonical SROTA row-first rule vs the simulator's dump.

Same oracle as the GEC differential, deliberately kept as a SEPARATE test
rather than a parameterised one: the two fabrics have different wire
topologies (SROTA's MECS wires are directional, GEC's are not), so a rule
that happened to satisfy both would be a coincidence, not a proof. If these
two files ever get merged, that is the moment to worry.
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
from veritx_dse.model.srota_rowfirst_route import (  # noqa: E402
    SHIPPABLE_SROTA_ROW_FIRST,
    SrotaRowFirstParams,
    derive_srota_rowfirst_table,
)

#: Mirrors tracks/t3-topology/configs/srota16_xy.cfg: Plane D + T, MECS on
#: both dimensions, row-first only, one VC, side-buffered router.
_CONFIG = """\
topology = srota;
routing_function = o1turn;
k = {k};
c = {c};
srota_planes    = 5;
srota_mecs      = {mecs};
srota_path_en   = 1;
srota_vc_policy = none;
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
    candidate = (REPO / "third_party" / "booksim2" / "src" / "booksim")
    if candidate.is_file():
        return candidate
    found = shutil.which("booksim")
    return Path(found) if found else None

def _run_dump(tmp: Path, params: SrotaRowFirstParams):
    binary = _booksim_bin()
    if binary is None:
        pytest.skip("no built BookSim binary in tree")
    tmp.mkdir(parents=True, exist_ok=True)
    dump = tmp / "srota.dump"
    mecs = (1 if params.mecs_row else 0) | (2 if params.mecs_col else 0)
    cfg = tmp / "srota.cfg"
    cfg.write_text(_CONFIG.format(k=params.k, c=params.c, num_vcs=params.num_vcs,
                                  mecs=mecs))
    proc = subprocess.run([str(binary), cfg.name], cwd=tmp,
                          capture_output=True, text=True, timeout=600)
    assert dump.is_file(), (
        f"no routing dump (rc={proc.returncode})\n{proc.stdout[-2500:]}\n"
        f"{proc.stderr[-2500:]}")
    return parse_route_dump_rows(dump.read_text())

@pytest.fixture(scope="module")
def _tmp_root(tmp_path_factory):
    return tmp_path_factory.mktemp("srota-rowfirst-differential")

def _check(tmp: Path, params: SrotaRowFirstParams) -> None:
    rows = _run_dump(tmp, params)
    derived = derive_srota_rowfirst_table(params)
    assert len(rows) == len(derived), (
        f"dump has {len(rows)} realizations, the rule derives {len(derived)}")
    mismatches: list[str] = []
    for hop in derived:
        row = rows[(hop.src_router, hop.dest_node)]
        actual = (row.port, row.drop, row.vc_start, row.vc_end,
                  row.next_router)
        expected = (hop.port, hop.drop, hop.vc_start, hop.vc_end,
                    hop.next_router)
        if actual != expected:
            mismatches.append(
                f"router {hop.src_router} -> node {hop.dest_node} "
                f"({hop.direction}): simulator (port,drop,vc_lo,vc_hi,next)"
                f"={actual} rule={expected}")
    assert not mismatches, (
        f"{len(mismatches)} of {len(rows)} hops disagree; first few:\n  "
        + "\n  ".join(mismatches[:8]))

def test_shippable_plane_d_matches(_tmp_root):
    """The configuration srota16_xy.cfg calls the shippable Plane D."""
    _check(_tmp_root / "shippable", SHIPPABLE_SROTA_ROW_FIRST)

def test_radix_6_matches(_tmp_root):
    """A different k changes the port set per position and the tap count."""
    _check(_tmp_root / "k6", SrotaRowFirstParams(k=6, c=1, num_vcs=1))

def test_concentration_2_matches_including_local_ejection(_tmp_root):
    _check(_tmp_root / "c2", SrotaRowFirstParams(k=4, c=2, num_vcs=1))

def test_express_is_directional_unlike_gec(_tmp_root):
    """The finding that makes a shared abstraction necessary, pinned.

    SROTA's westbound wire from the last column taps 2,1,0 in that order;
    GEC's single wire from the same column taps 0,2,3. Same shape, opposite
    tap index — so a model that assumed one ordering would place every
    dropped packet on the wrong router.
    """
    rows = _run_dump(_tmp_root / "directional",
                     SrotaRowFirstParams(k=4, c=1, num_vcs=1))
    # Router 15 is (x=3, y=3): only XNEG and YNEG exist there.
    xneg = rows[(15, 12)]
    assert (xneg.port, xneg.drop, xneg.next_router) == (1, 2, 12)
    assert rows[(15, 13)].drop == 1 and rows[(15, 13)].next_router == 13
    assert rows[(15, 14)].drop == 0 and rows[(15, 14)].next_router == 14
    # ...whereas the tap index counts the DISTANCE minus one, not a peer rank.
    assert rows[(0, 3)].drop == 2 and rows[(0, 3)].next_router == 3
    assert rows[(0, 1)].drop == 0 and rows[(0, 1)].next_router == 1

def test_single_shape_needs_no_vc_partition(_tmp_root):
    """Row-first only: every shared hop carries the whole VC range.

    This is why the shippable Plane D is the cheapest proof of the
    representation — one shape means no partition machinery is required.
    """
    rows = _run_dump(_tmp_root / "onevc", SHIPPABLE_SROTA_ROW_FIRST)
    for row in rows.values():
        assert row.vc_start == 0 and row.vc_end == 0
        if row.is_shared():
            assert row.drop is not None and row.drop >= 0

def test_a_plain_dimension_is_refused_not_given_a_tap():
    from veritx_dse.model.srota_rowfirst_route import (
        SrotaRowFirstRouteError,
    )
    params = SrotaRowFirstParams(k=4, c=1, mecs_row=False, mecs_col=True)
    with pytest.raises(SrotaRowFirstRouteError, match="no express layer"):
        derive_srota_rowfirst_table(params)
    with pytest.raises(SrotaRowFirstRouteError, match="express layer"):
        SrotaRowFirstParams(k=4, c=1, mecs_row=False, mecs_col=False)

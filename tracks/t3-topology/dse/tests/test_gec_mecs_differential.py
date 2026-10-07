"""Differential: the canonical GEC-MECS hop rule vs the simulator's own dump.

This is the oracle that makes the shared-resource route representation
trustworthy. A hand-written Python re-implementation of ``dor_gec`` proves
nothing on its own; what proves something is running the REAL fork and
comparing every (router, terminal) first hop it executes against the rule
derived independently in ``model/gec_mecs_route.py``.

Four facts must agree for every pair, and all four are load-bearing:

    port        which WIRE (the shared resource)
    drop        which TAP (where the packet leaves that wire)
    vc range    which VCs that hop may use (the tap's own slice)
    next_router which router the tap actually lands at

``next_router`` is the one the old harness could not answer: it derived the
landing router from ``FlitChannel::GetSink()``, which for a shared wire
reports whichever tap registered last. A dump that gets that wrong is worse
than no dump, because it looks authoritative.
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
from veritx_dse.model.gec_mecs_route import (  # noqa: E402
    GecMecsParams,
    derive_gec_mecs_table,
)

_CONFIG = """\
topology = gec;
routing_function = dor_gec;
k = {k};
c = {c};
o = {o};
d = {d};
mesh = 0;
num_vcs = {num_vcs};
use_noc_latency = 0;
routing_dump_file = {dump};
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

def _run_dump(tmp: Path, params: GecMecsParams):
    binary = _booksim_bin()
    if binary is None:
        pytest.skip("no built BookSim binary in tree")
    tmp.mkdir(parents=True, exist_ok=True)
    dump = tmp / "gec.dump"
    cfg = tmp / "gec.cfg"
    cfg.write_text(_CONFIG.format(
        k=params.k, c=params.c, o=params.o, d=params.d,
        num_vcs=params.num_vcs, dump=dump.name))
    proc = subprocess.run([str(binary), cfg.name], cwd=tmp,
                          capture_output=True, text=True, timeout=600)
    assert dump.is_file(), (
        f"the run produced no routing dump (rc={proc.returncode})\n"
        f"--- stdout ---\n{proc.stdout[-3000:]}\n"
        f"--- stderr ---\n{proc.stderr[-3000:]}")
    # One parser for both fabrics: the product's own route-dump reader.
    return parse_route_dump_rows(dump.read_text())

@pytest.fixture(scope="module")
def _tmp_root(tmp_path_factory):
    return tmp_path_factory.mktemp("gec-mecs-differential")

def _check(tmp: Path, params: GecMecsParams) -> None:
    rows = _run_dump(tmp, params)
    derived = derive_gec_mecs_table(params)
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
                f"router {hop.src_router} -> node {hop.dest_node}: "
                f"simulator (port,drop,vc_lo,vc_hi,next)={actual} "
                f"rule={expected}")
    assert not mismatches, (
        f"{len(mismatches)} of {len(rows)} hops disagree with the "
        f"independently derived rule; first few:\n  "
        + "\n  ".join(mismatches[:8]))

def test_dump_actually_expresses_a_shared_hop(_tmp_root):
    """Guard: a legacy 4-column dump would pass nothing and hide the gap."""
    params = GecMecsParams(k=4, c=1, o=1, d=3, num_vcs=3)
    rows = _run_dump(_tmp_root / "shape-check", params)
    shared = [r for r in rows.values() if r.is_shared()]
    local = [r for r in rows.values() if not r.is_shared()]
    assert shared and local, (
        "the dump must contain both shared hops (tap >= 0) and local "
        "ejections (tap = -1); a dump with neither is not the new format")
    # Every shared hop's VC range is its tap's own disjoint slice.
    for row in shared:
        assert row.vc_start == row.drop * params.vcs_per_tap
        assert row.vc_end == row.vc_start + params.vcs_per_tap - 1
    # Every shared hop lands somewhere other than its source router.
    for row in shared:
        assert row.next_router != row.src_router

def test_single_terminal_per_router_matches(_tmp_root):
    _check(_tmp_root / "c1", GecMecsParams(k=4, c=1, o=1, d=3, num_vcs=3))

def test_concentrated_matches_including_local_ejection(_tmp_root):
    """c > 1 exercises the `dest % c` local port and the wider VC slices."""
    _check(_tmp_root / "c2", GecMecsParams(k=4, c=2, o=1, d=3, num_vcs=6))

def test_larger_radix_matches(_tmp_root):
    """k=6, o=1, d=5: a different tap count, so the slice width changes."""
    _check(_tmp_root / "k6", GecMecsParams(k=6, c=1, o=1, d=5, num_vcs=10))

def test_the_rule_refuses_a_shape_the_source_would_refuse():
    """A shape that violates the source law must not produce a table."""
    from veritx_dse.model.gec_mecs_route import GecMecsRouteError
    with pytest.raises(GecMecsRouteError, match="o\\*d"):
        GecMecsParams(k=5, c=1, o=1, d=3, num_vcs=3)
    with pytest.raises(GecMecsRouteError, match="divide"):
        GecMecsParams(k=4, c=1, o=1, d=3, num_vcs=4)
    with pytest.raises(GecMecsRouteError, match="at least one VC"):
        GecMecsParams(k=4, c=1, o=1, d=3, num_vcs=2)

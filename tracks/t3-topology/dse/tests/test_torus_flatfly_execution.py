"""Live backend execution: torus / flatfly / gec-express on the real binary.

EPISTEMIC STATUS (read first): these are BACKEND-LEVEL measurements, the
same class as the PARETO-REPLAY rows — NOT certified qualification.
Certified execution additionally requires a COMPILED bundle (torus is
blocked at DEADLOCK_FREE pending the dateline-partition bridge, pinned
by test_torus_route.py). Nothing here claims a qualification the
modern chain has not issued.

- flatfly k=4 n=2: executed first-hop dump is byte-identical to the
  canonical FLATFLY_MIN table (256/256 COMPARABLE).
- torus k=5: uniform traffic completes with no deadlock under
  dim_order_torus (dump equivalence is blocked by the fork dump
  harness passing in_channel=-1, which dor_next_torus cannot resolve —
  exact patch location reported, not worked around).
- gec-express k=4: uniform traffic completes under dor_gec.
"""
from __future__ import annotations

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


_FF_CFG = """topology = flatfly;
k = 4;
n = 2;
c = 1;
x = 4;
y = 4;
xr = 1;
yr = 1;
routing_function = ran_min;
routing_dump_file = ff.dump;
use_noc_latency = 0;
num_vcs = 1;
traffic = uniform;
sim_count = 1;
injection_rate = 0.01;
packet_size = 1;
"""

_TORUS_CFG = """topology = torus;
k = 5;
n = 2;
routing_function = dim_order;
use_noc_latency = 0;
num_vcs = 2;
traffic = uniform;
sim_count = 2000;
injection_rate = 0.05;
packet_size = 4;
"""

_GEC_CFG = """topology = gec;
k = 4;
c = 1;
o = 3;
d = 1;
mesh = 0;
hybrid = 0;
routing_function = dor;
use_noc_latency = 0;
num_vcs = 1;
routing_delay = 1;
traffic = uniform;
sim_count = 2000;
injection_rate = 0.05;
packet_size = 4;
"""


@needs_binary
def test_flatfly_dump_is_byte_identical_to_canonical(tmp_path):
    from veritx_dse.backend.route_observation import (  # noqa: E402
        expected_route_rows,
        parse_route_dump,
    )
    from veritx_dse.core.route_artifact import (  # noqa: E402
        FLATFLY_MIN,
        RouteArtifact,
        compare_first_hop_tables,
    )
    from veritx_dse.model.topology_artifact import (  # noqa: E402
        materialize_flatfly,
    )

    proc = _run(_FF_CFG, tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    dump = (tmp_path / "ff.dump").read_text()
    f = materialize_flatfly(k=4, n=2, concentration=1)
    r = RouteArtifact.from_topology(
        f, name="ff", routing_classes=(FLATFLY_MIN,))
    rows = expected_route_rows(
        routing_class=FLATFLY_MIN, topology=f, route=r,
        node_to_router={n: n for n in range(16)})
    report = compare_first_hop_tables(
        {(s, d): n for s, d, n in rows}, parse_route_dump(dump))
    assert report["status"] == "COMPARABLE", report["mismatched"][:5]
    assert report["coverage"]["matched"] == 256


@needs_binary
def test_torus_uniform_traffic_completes_without_deadlock(tmp_path):
    proc = _run(_TORUS_CFG, tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "Packet latency average" in proc.stdout
    assert "Deadlock" not in proc.stdout and "deadlock" not in proc.stderr


@needs_binary
def test_gec_express_uniform_traffic_completes(tmp_path):
    proc = _run(_GEC_CFG, tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "Packet latency average" in proc.stdout

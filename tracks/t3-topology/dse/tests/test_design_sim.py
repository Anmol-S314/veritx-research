"""Design-cockpit candidate simulation boundary.

Covers the pure topology/projection helpers and the trace-resolution guard.
The BookSim execution itself is exercised by the gateway integration path;
these tests keep the geometry and the 'no caller-supplied path' rule cheap
and hermetic.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.core.errors import InvalidInput  # noqa: E402
from veritx_dse.gateway.design_sim import (  # noqa: E402
    CandidateSpec,
    DesignSimBody,
    _channel_for_port,
    _make_topology,
    _project,
    _resolve_trace,
    run_design_simulation,
)


class _Product:
    def __init__(self, documents=None, error=None):
        self._documents = documents or {}
        self._error = error

    def run_evidence(self, run_id):
        if self._error is not None:
            raise self._error
        return {"documents": self._documents}


def _trace(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "workload.trace"
    path.write_text("\n".join(lines) + "\n")
    return path


def test_mesh_and_torus_channel_counts():
    mesh = _make_topology("mesh", 9)
    torus = _make_topology("torus", 9)
    assert len(mesh["routers"]) == 81
    assert len(mesh["channels"]) == 288
    assert len(torus["channels"]) == 324
    assert len([c for c in torus["channels"] if c["wrap"]]) == 36


def test_book_sim_port_zero_is_east_and_wraps_on_torus():
    mesh = _make_topology("mesh", 9)
    torus = _make_topology("torus", 9)
    east = _channel_for_port(mesh, 0, 0)
    assert east is not None and east["dst_router"] == 1
    wrap = _channel_for_port(torus, 0, 1)  # west from column 0
    assert wrap is not None and wrap["dst_router"] == 8 and wrap["wrap"]


def test_projection_xy_and_torus_wrap(tmp_path):
    trace = _trace(tmp_path, ["0 0 0 1 8", "1 0 0 9 8"])
    mesh = _make_topology("mesh", 9)
    demand, flits, hops = _project(mesh, trace)
    assert flits == 16
    assert demand[0] == 8       # R0 -> R1 (east)
    assert demand[1] == 8       # R0 -> R9 (south)
    assert hops == 16

    torus = _make_topology("torus", 9)
    trace = _trace(tmp_path, ["0 0 0 80 8"])
    demand, flits, hops = _project(torus, trace)
    assert flits == 8
    assert len(demand) == 2     # west wrap then north wrap
    assert hops == 16


def test_trace_resolution_only_accepts_run_bundle_paths(tmp_path):
    root = tmp_path / "store"
    run_dir = root / "projects" / "p" / "runs" / "run-1" / "bundle" / "run"
    run_dir.mkdir(parents=True)
    trace = run_dir / "workload.trace"
    trace.write_text("0 0 0 1 8\n")
    product = _Product({"run/backend-evidence.json": {
        "attempt": {"run_dir": str(run_dir)},
    }})
    assert _resolve_trace(product, (root,), "run-1") == trace.resolve()

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "workload.trace").write_text("0 0 0 1 8\n")
    hostile = _Product({"run/backend-evidence.json": {
        "attempt": {"run_dir": str(outside)},
    }})
    empty_root = tmp_path / "empty-store"
    empty_root.mkdir()
    with pytest.raises(InvalidInput):
        _resolve_trace(hostile, (empty_root,), "run-1")
    # A legitimate trace under the root is still found by the fallback scan;
    # the outside path itself is never returned.
    assert _resolve_trace(hostile, (root,), "run-1") == trace.resolve()


def test_torus_candidate_requires_two_vcs_before_execution(tmp_path):
    root = tmp_path / "store"
    run_dir = root / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "workload.trace").write_text("0 0 0 1 8\n")
    product = _Product({"run/backend-evidence.json": {
        "attempt": {"run_dir": str(run_dir)},
    }})
    body = DesignSimBody(
        run_id="run-1",
        candidates=[CandidateSpec(id="torus", family="torus", side=9, vcs=1)],
    )
    with pytest.raises(InvalidInput, match="at least 2 VCs"):
        run_design_simulation(
            body, roots=(root,), product=product,
            booksim_bin=Path(sys.executable))

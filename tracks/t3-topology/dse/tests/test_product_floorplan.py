"""Authored floorplan infrastructure.

A floorplan is its own artifact bound to a topology identity: it never enters
the design draft, never changes a design hash, and is never applied to a
topology it was not authored for.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.product.floorplan import (  # noqa: E402
    Floorplan, Keepout, derive, from_grid,
)
from veritx_dse.product.service import (  # noqa: E402
    ProductConfig, ProductService,
)


def _service(tmp_path) -> ProductService:
    return ProductService(ProductConfig(projects_root=tmp_path / "projects"))


def _compiled_mesh(tmp_path):
    svc = _service(tmp_path)
    view = svc.create_project_from_preset("mesh4")
    project_id = view["project"]["project_id"]
    svc.compile_draft(project_id)
    topology = svc.get_revision_topology(
        svc.store.load_project(project_id)["active_revision_id"])
    return svc, project_id, topology


GRID = {
    "origin_x_um": 0, "origin_y_um": 0,
    "pitch_x_um": 2000, "pitch_y_um": 2000,
    "router_width_um": 800, "router_height_um": 800,
    "margin_um": 1000,
    "wire": {"ps_per_mm": 120, "fixed_ps": 40},
}


def test_floorplan_is_absent_until_declared(tmp_path):
    svc, project_id, topology = _compiled_mesh(tmp_path)
    state = svc.get_floorplan(project_id)
    assert state["declared"] is False
    assert state["topology_hash"] == topology["topology_hash"]
    assert state["floorplan"] is None and state["derived"] is None


def test_grid_floorplan_derives_area_and_declared_delay(tmp_path):
    svc, project_id, topology = _compiled_mesh(tmp_path)
    state = svc.put_floorplan(project_id, {"mode": "grid", "grid": GRID})
    assert state["declared"] is True
    assert state["stale"] is False
    derived = state["derived"]
    # mesh4 is a 2x2 grid: one pitch step plus one footprint plus the margin.
    assert derived["die"] == {"width_um": 3800, "height_um": 3800,
                             "area_um2": 3800 * 3800}
    assert derived["routers"]["count"] == 4
    assert derived["routers"]["area_um2"] == 4 * 800 * 800
    assert derived["routers"]["utilization"] == pytest.approx(
        4 * 800 * 800 / (3800 * 3800), abs=1e-6)
    # 2x2 mesh: 8 directed channels, adjacent centres one pitch apart.
    assert derived["links"]["channels"] == 8
    assert derived["links"]["length_um"] == {
        "min": 2000.0, "mean": 2000.0, "max": 2000.0}
    # 2 mm * 120 ps/mm + 40 ps fixed
    assert derived["links"]["delay_ps"] == {
        "min": 280.0, "mean": 280.0, "max": 280.0}


def test_the_artifact_round_trips_and_keeps_its_identity(tmp_path):
    _svc, _pid, topology = _compiled_mesh(tmp_path)
    plan = from_grid(topology, GRID)
    assert Floorplan.from_dict(json.loads(json.dumps(plan.to_dict()))) == plan
    assert plan.artifact_id() == from_grid(topology, GRID).artifact_id()


def test_a_pitch_smaller_than_the_footprint_is_refused(tmp_path):
    _svc, _pid, topology = _compiled_mesh(tmp_path)
    with pytest.raises(ValueError, match="pitch must be at least"):
        from_grid(topology, {**GRID, "pitch_x_um": 400})


def test_a_keepout_may_not_sit_on_a_router(tmp_path):
    _svc, _pid, topology = _compiled_mesh(tmp_path)
    plan = from_grid(topology, GRID)
    with pytest.raises(ValueError, match="keepout ko0 overlaps"):
        Floorplan(
            topology_hash=plan.topology_hash,
            die_width_um=plan.die_width_um, die_height_um=plan.die_height_um,
            routers=plan.routers,
            keepouts=(Keepout("ko0", 0, 0, 200, 200),),
            wire=plan.wire)


def test_a_floorplan_cannot_cover_a_different_router_set(tmp_path):
    _svc, _pid, topology = _compiled_mesh(tmp_path)
    plan = from_grid(topology, GRID).to_dict()
    plan["routers"] = plan["routers"][:-1]
    with pytest.raises(ValueError, match="cover exactly"):
        derive(topology, Floorplan.from_dict(plan))


def test_a_stale_floorplan_is_reported_not_applied(tmp_path):
    svc, project_id, topology = _compiled_mesh(tmp_path)
    svc.put_floorplan(project_id, {"mode": "grid", "grid": GRID})
    stored = svc.store.load_floorplan(project_id)
    stored["topology_hash"] = "sha256:" + "0" * 64
    svc.store.save_floorplan(project_id, stored)
    state = svc.get_floorplan(project_id)
    assert state["declared"] is False
    assert state["stale"] is True
    assert state["derived"] is None
    assert state["bound_topology_hash"] == "sha256:" + "0" * 64


def test_declaring_never_touches_the_design_hash(tmp_path):
    svc, project_id, _topology = _compiled_mesh(tmp_path)
    before = svc.draft_view(project_id)["design_hash"]
    svc.put_floorplan(project_id, {"mode": "grid", "grid": GRID})
    assert svc.draft_view(project_id)["design_hash"] == before

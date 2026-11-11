"""A shipped preset must be materializable as a runnable project.

"Ready to run" means the operation executes the canonical request the preset
already documents, not a second copy that can drift from it. This gate proves
the draft IS the preset's request and that an unknown preset is refused
rather than invented.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.presets import (  # noqa: E402
    build_versioned_preset_request, preset_catalog,
)
from veritx_dse.product.service import ProductService  # noqa: E402
from veritx_dse.product.service import (  # noqa: E402
    ProductConfig,
)


def _service(tmp_path) -> ProductService:
    return ProductService(ProductConfig(projects_root=tmp_path / "projects"))


def _preset_ids() -> list[str]:
    return [entry["preset_id"] for entry in preset_catalog()]


def test_catalog_is_not_empty():
    assert _preset_ids()


def test_every_shipped_preset_materializes_to_its_own_request(tmp_path):
    svc = _service(tmp_path)
    for preset_id in _preset_ids():
        view = svc.create_project_from_preset(preset_id)
        project_id = view["project"]["project_id"]
        draft = svc.store.load_draft(project_id)
        expected, _generation = build_versioned_preset_request(preset_id)
        assert draft["request"] == expected.to_dict()
        assert draft["source"].startswith(f"preset:{preset_id}:")


def test_materialized_preset_compiles(tmp_path):
    """A preset is only 'ready to run' if its draft actually compiles.

    Every shipped preset is asserted, because a catalog entry whose draft
    the compiler refuses is not an operation — it is a broken promise.
    """
    svc = _service(tmp_path)
    for preset_id in _preset_ids():
        view = svc.create_project_from_preset(preset_id)
        outcome = svc.compile_draft(view["project"]["project_id"])
        compilation = outcome.get("compilation") or {}
        assert compilation.get("status") == "COMPILED", (
            f"{preset_id} does not compile: "
            f"{compilation.get('status')}: {compilation.get('error')}")


def test_srota_preset_topology_view_exposes_shared_wires_and_planes(tmp_path):
    """The topology view must carry the MECS wires and declared planes.

    SROTA has zero directed channels by construction; dropping shared_links
    from the view leaves the UI with routers and no connectivity at all.
    """
    svc = _service(tmp_path)
    view = svc.create_project_from_preset("srota32_plane_c")
    compiled = svc.compile_draft(view["project"]["project_id"])
    assert compiled["compilation"]["status"] == "COMPILED"
    topology = svc.get_revision_topology(compiled["revision_id"])

    assert topology["family"] == "srota"
    assert topology["channels"] == []
    assert len(topology["shared_links"]) == 48
    assert topology["counts"]["shared_links"] == 48
    assert topology["planes"] == ["c", "d", "t"]

    result = svc.get_revision_compile_result(compiled["revision_id"])
    control = result["groups"]["control_plane"]
    assert control["available"] is True
    assert control["subnet"]["k"] == 4
    assert control["subnet"]["c"] == 2
    assert control["subnet"]["vcs"] == ["REQ", "RSP", "SNP"]


def test_unknown_preset_is_refused_not_invented(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(Exception) as excinfo:
        svc.create_project_from_preset("definitely-not-a-preset")
    assert "definitely-not-a-preset" in str(excinfo.value)


def test_name_defaults_to_the_preset_id(tmp_path):
    svc = _service(tmp_path)
    preset_id = _preset_ids()[0]
    view = svc.create_project_from_preset(preset_id)
    assert view["project"]["name"] == preset_id

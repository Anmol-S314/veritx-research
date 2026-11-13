"""The product store survives its root being deleted under a live process.

`scripts/cleanup_runs.sh` removes `runs/studio-store` wholesale. A long-lived
gateway then answered every `POST /api/v1/projects` with a bare 500
"internal server error", because `ProductStore._locked` opened `.store.lock`
inside a directory that no longer existed. The root is only created once, in
`__init__`, so nothing recreated it.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.product.store import ProductStore  # noqa: E402


def _draft() -> dict:
    return {"workload_id": "w", "topology": {"kind": "mesh"}}


def test_mutation_recreates_a_deleted_root(tmp_path):
    root = tmp_path / "studio-store" / "projects"
    store = ProductStore(root)
    before = store.create_project(name="before", draft_doc=_draft(),
                                  workload_id="w", source="catalog")

    shutil.rmtree(tmp_path / "studio-store")
    assert not root.exists()

    after = store.create_project(name="after", draft_doc=_draft(),
                                 workload_id="w", source="catalog")

    assert after["project_id"] != before["project_id"]
    assert (root / ".store.lock").exists()
    assert store.load_project(after["project_id"])["name"] == "after"
    assert [p["project_id"] for p in store.list_projects()] == [
        after["project_id"]]

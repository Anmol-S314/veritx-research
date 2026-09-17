"""PR6 Phase 4 — serving-slice spec boundary tests (no execution here).

Serving intent is strict like Slice A: registered IDs, never paths;
unknown fields rejected; mode=serving requires the serving block and
latency specs must keep resolving byte-identically (zero drift).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.core.paths import SERVING_CLUSTERS, SERVING_DATASETS
from veritx_dse.core.spec import (
    SpecError,
    canonical_json,
    experiment_hash,
    parse,
    resolve,
)


def _latency_dict():
    return {
        "name": "lat",
        "workload": {"id": "w", "trace": "archive/inputs/traces/x.trace"},
        "system": {"nodes": 64},
        "network": {"topology": "mesh_8x8"},
        "simulation": {"mode": "latency"},
    }


def _serving_dict(**kw):
    d = {
        "name": "serve",
        "workload": {"id": "w", "trace": "archive/inputs/traces/x.trace"},
        "system": {"nodes": 1},
        "network": {"topology": "mesh_8x8"},
        "simulation": {"mode": "serving", "timeout_s": 300},
        "serving": {
            "cluster": "single_tp2_ep2",
            "dataset": "example",
            "num_reqs": 1,
        },
    }
    d["serving"].update(kw)
    return d


class TestServingSpecBoundary:
    def test_serving_block_required_for_serving_mode(self):
        d = _serving_dict()
        del d["serving"]
        with pytest.raises(SpecError, match="serving"):
            resolve(parse(d))

    def test_serving_block_rejected_for_latency_mode(self):
        d = _latency_dict()
        d["serving"] = {"cluster": "x", "dataset": "y", "num_reqs": 1}
        with pytest.raises(SpecError, match="serving"):
            resolve(parse(d))

    def test_unknown_fields_rejected(self):
        with pytest.raises(SpecError, match="lossy"):
            parse(_serving_dict(allow_lossy=True))

    def test_unknown_backend_rejected(self):
        with pytest.raises(SpecError, match="network_backend"):
            parse(_serving_dict(network_backend="vibes"))

    def test_num_reqs_positive(self):
        with pytest.raises(SpecError, match="num_reqs"):
            parse(_serving_dict(num_reqs=0))

    def test_resolved_serving_shape(self):
        r = resolve(parse(_serving_dict()))
        assert r["serving"]["cluster"] == "single_tp2_ep2"
        assert r["serving"]["dataset"] == "example"
        assert r["serving"]["num_reqs"] == 1
        assert r["serving"]["network_backend"] == "booksim"
        assert r["serving"]["cycle_accurate"] is True
        assert r["serving"]["request_routing_policy"] == "LOAD"
        assert r["simulation"]["mode"] == "serving"

    def test_serving_specs_hash_distinctly(self):
        h1 = experiment_hash(resolve(parse(_serving_dict())))
        h2 = experiment_hash(resolve(parse(_serving_dict(num_reqs=2))))
        assert h1 != h2
        assert experiment_hash(resolve(parse(_serving_dict()))) == h1

    def test_latency_resolution_unchanged(self):
        r = resolve(parse(_latency_dict()))
        assert r["serving"] is None
        assert set(r) == {"schema_version", "workload", "system",
                          "network", "simulation", "replication",
                          "comparison", "serving"}


class TestServingRegistry:
    def test_golden_ids_resolve_to_real_files(self):
        for _id, rel in list(SERVING_CLUSTERS.items()) + \
                list(SERVING_DATASETS.items()):
            p = Path(rel)
            assert p.is_file(), f"registered { _id} missing: {rel}"

    def test_golden_clusters_cover_both_shapes(self):
        from veritx_dse.core.serving import preflight_serve  # noqa: F401
        import json
        singles = [i for i in SERVING_CLUSTERS
                   if "single" in i or "tp2" in i]
        multis = [i for i in SERVING_CLUSTERS if "multi" in i or "dp" in i]
        assert singles and multis, \
            "registry must hold a single-instance and a multi-instance ID"
        for _id in singles + multis:
            cfg = json.loads(Path(SERVING_CLUSTERS[_id]).read_text())
            ninst = sum(len(n.get("instances", []))
                        for n in cfg.get("nodes", []))
            if _id in multis:
                assert ninst > 1
            else:
                assert ninst == 1

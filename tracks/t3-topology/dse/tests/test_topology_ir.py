"""Tests for TopologyIR v0 — schema, expand, translators, CLI.

Live diff test runs both real frontends on golden fixtures when present
(mirrors TestLiveAstra): mesh16 IR + one-coll.et (16 ranks, vendored).
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.cli.cli import cmd_topology_render, cmd_topology_stats, cmd_topology_diff
from veritx_dse.core.logging import Ctx
from veritx_dse.core.paths import ASTRA_BS_BIN
from veritx_dse.model import topology_ir as tir
from veritx_dse.core.errors import TopologyError

FIX = Path(__file__).parent / "fixtures" / "astra_tiny"


def _doc(**kw):
    base = {"name": "t", "kind": "mesh", "nodes": 16,
            "params": {"k": 4, "n": 2},
            "link_attrs": {"bandwidth_GBs": 50, "latency_ns": 500}}
    base.update(kw)
    return base


# ── schema ───────────────────────────────────────────────────────────────

class TestSchema:
    def test_mesh_ok(self):
        ir = tir.from_dict(_doc())
        assert ir.effective_routing == "dim_order"

    def test_explicit_routing_wins(self):
        ir = tir.from_dict(_doc(routing="min_adapt"))
        assert ir.effective_routing == "min_adapt"

    def test_bad_kind(self):
        with pytest.raises(TopologyError):
            tir.from_dict(_doc(kind="hypercube"))

    def test_mesh_count_mismatch(self):
        with pytest.raises(TopologyError):
            tir.from_dict(_doc(params={"k": 4, "n": 3}))

    def test_mesh_missing_k(self):
        with pytest.raises(TopologyError):
            tir.from_dict(_doc(params={"k": 4}))

    def test_template_rejects_links(self):
        with pytest.raises(TopologyError):
            tir.from_dict(_doc(links=[[0, 1]]))

    def test_anynet_needs_links(self):
        with pytest.raises(TopologyError):
            tir.from_dict(_doc(kind="anynet", nodes=4))

    def test_link_out_of_range(self):
        with pytest.raises(TopologyError):
            tir.from_dict(_doc(kind="anynet", nodes=4, links=[[0, 9]]))

    def test_link_self_loop(self):
        with pytest.raises(TopologyError):
            tir.from_dict(_doc(kind="custom", nodes=4, links=[[1, 1]]))

    def test_link_duplicate(self):
        with pytest.raises(TopologyError):
            tir.from_dict(_doc(kind="custom", nodes=4,
                               links=[[0, 1], [1, 0]]))

    def test_missing_bandwidth(self):
        bad = _doc()
        del bad["link_attrs"]["bandwidth_GBs"]
        with pytest.raises(TopologyError):
            tir.from_dict(bad)

    def test_dims_product_mismatch(self):
        with pytest.raises(TopologyError):
            tir.from_dict(_doc(dims=[{"topology": "Ring", "count": 4,
                                      "bandwidth_GBs": 50, "latency_ns": 500}]))

    def test_load_missing_file(self, tmp_path):
        with pytest.raises(TopologyError):
            tir.load(tmp_path / "nope.json")

    def test_load_bad_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json")
        with pytest.raises(TopologyError):
            tir.load(p)

    def test_booksim_defaults_track_canonical(self):
        from veritx_dse.simulation.booksim import BASE_PARAMS
        for k, v in tir.BOOKSIM_DEFAULTS.items():
            assert BASE_PARAMS[k] == v, f"drift: {k}"


# ── expand / stats ───────────────────────────────────────────────────────

class TestExpandStats:
    def test_mesh4x4(self):
        m = tir.expand(tir.from_dict(_doc()))
        assert len(m.nodes) == 16 and len(m.edges) == 24
        s = tir.stats(tir.from_dict(_doc()), m)
        assert s["diameter"] == 6 and s["connected"] is True
        assert s["degree_histogram"] == {"2": 4, "3": 8, "4": 4}

    def test_torus4x4(self):
        ir = tir.from_dict(_doc(kind="torus"))
        m = tir.expand(ir)
        assert len(m.edges) == 32
        assert tir.stats(ir, m)["diameter"] == 4

    def test_ring8(self):
        ir = tir.from_dict({"name": "r", "kind": "ring", "nodes": 8,
                            "params": {"n": 8},
                            "link_attrs": {"bandwidth_GBs": 50, "latency_ns": 500}})
        m = tir.expand(ir)
        assert len(m.edges) == 8
        assert tir.stats(ir, m)["diameter"] == 4

    def test_star(self):
        ir = tir.from_dict({"name": "s", "kind": "star", "nodes": 5,
                            "params": {"leaves": 4},
                            "link_attrs": {"bandwidth_GBs": 400, "latency_ns": 100}})
        m = tir.expand(ir)
        assert len(m.edges) == 4
        assert tir.stats(ir, m)["diameter"] == 2

    def test_disconnected_reports(self):
        ir = tir.from_dict({"name": "c", "kind": "custom", "nodes": 4,
                            "links": [[0, 1], [2, 3]],
                            "link_attrs": {"bandwidth_GBs": 50, "latency_ns": 500}})
        s = tir.stats(ir)
        assert s["connected"] is False and s["diameter"] is None
        assert s["components"] == 2

    def test_ascii_cap(self):
        ir = tir.from_dict(_doc(nodes=64, params={"k": 8, "n": 2}))
        with pytest.raises(TopologyError):
            tir.render_ascii(ir)


# ── translators ─────────────────────────────────────────────────────────

class TestTranslators:
    def test_cfg_mesh(self):
        ir = tir.from_dict(_doc())
        cfg = tir.to_booksim_cfg(ir)
        assert "topology = mesh;" in cfg
        assert "k = 4;" in cfg and "n = 2;" in cfg
        assert "routing_function = dim_order;" in cfg
        assert "total_nodes = 16;" in cfg
        # topology comes after k/n (build_config ordering convention)
        assert cfg.index("k = 4;") < cfg.index("topology = mesh;")

    def test_cfg_ring_is_1d_torus(self):
        ir = tir.from_dict({"name": "r", "kind": "ring", "nodes": 8,
                            "params": {"n": 8},
                            "link_attrs": {"bandwidth_GBs": 50, "latency_ns": 500}})
        cfg = tir.to_booksim_cfg(ir)
        assert "topology = torus;" in cfg and "k = 8;" in cfg

    def test_cfg_anynet_needs_file(self):
        ir = tir.from_dict({"name": "s", "kind": "star", "nodes": 5,
                            "params": {"leaves": 4},
                            "link_attrs": {"bandwidth_GBs": 400, "latency_ns": 100}})
        with pytest.raises(TopologyError):
            tir.to_booksim_cfg(ir)
        cfg = tir.to_booksim_cfg(ir, network_file="/tmp/x.anynet")
        assert "topology = anynet;" in cfg
        assert "network_file = /tmp/x.anynet;" in cfg
        assert "routing_function = min;" in cfg

    def test_anynet_star_shape(self):
        """Same line shape as scorpio-demo/gen_star.py output."""
        ir = tir.from_dict({"name": "s", "kind": "star", "nodes": 5,
                            "params": {"leaves": 4},
                            "link_attrs": {"bandwidth_GBs": 400, "latency_ns": 100}})
        lines = tir.to_anynet(ir).splitlines()
        assert len(lines) == 5
        assert lines[0] == "router 0 node 0 router 4"
        assert lines[4] == "router 4 node 4 router 0 router 1 router 2 router 3"

    def test_yml_mesh(self):
        yml = tir.to_analytical_yml(tir.from_dict(_doc()))
        assert "topology: [Ring]" in yml
        assert "npus_count: [16]" in yml
        # House style matches ASTRA examples (float rendering).
        assert "bandwidth: [50.0]" in yml
        assert "latency: [500.0]" in yml

    def test_yml_star_is_switch(self):
        ir = tir.from_dict({"name": "s", "kind": "star", "nodes": 5,
                            "params": {"leaves": 4},
                            "link_attrs": {"bandwidth_GBs": 400, "latency_ns": 100}})
        assert "topology: [Switch]" in tir.to_analytical_yml(ir)

    def test_yml_anynet_without_dims_fails(self):
        ir = tir.from_dict({"name": "a", "kind": "anynet", "nodes": 4,
                            "links": [[0, 2], [1, 3], [2, 3]],
                            "link_attrs": {"bandwidth_GBs": 50, "latency_ns": 500}})
        with pytest.raises(TopologyError):
            tir.to_analytical_yml(ir)

    def test_preset_bridge(self):
        p = tir.to_preset(tir.from_dict(_doc()))
        assert (p.backend, p.params) == ("mesh", {"k": 4, "n": 2})
        r = tir.to_preset(tir.from_dict({"name": "r", "kind": "ring", "nodes": 8,
                                         "params": {"n": 8},
                                         "link_attrs": {"bandwidth_GBs": 50,
                                                        "latency_ns": 500}}))
        assert (r.backend, r.params) == ("torus", {"k": 8, "n": 1})
        with pytest.raises(TopologyError):
            tir.to_preset(tir.from_dict(
                {"name": "s", "kind": "star", "nodes": 5, "params": {"leaves": 4},
                 "link_attrs": {"bandwidth_GBs": 400, "latency_ns": 100}}))

    def test_divergence_math(self):
        d = tir.divergence_report(119080, 115000)
        assert d["verdict"] == "agree" and d["divergence_pct"] == pytest.approx(3.43, abs=0.01)
        assert tir.divergence_report(100, 50)["verdict"] == "diverge"
        with pytest.raises(TopologyError):
            tir.divergence_report(0, 100)


# ── CLI ──────────────────────────────────────────────────────────────────

def _write_ir(tmp_path, **kw):
    p = tmp_path / "topo.json"
    p.write_text(json.dumps(_doc(**kw)))
    return str(p)


class TestTopologyCLI:
    def test_render_ascii_stdout(self, tmp_path, capsys):
        cmd_topology_render(Ctx(verbosity=0), SimpleNamespace(
            ir=_write_ir(tmp_path), format="ascii", out=None))
        out = capsys.readouterr().out
        assert "nodes=16 edges=24" in out and "0:" in out

    def test_render_anynet_file(self, tmp_path):
        out = str(tmp_path / "links.anynet")
        cmd_topology_render(Ctx(verbosity=0), SimpleNamespace(
            ir=_write_ir(tmp_path), format="anynet", out=out))
        assert Path(out).read_text().splitlines()[0].startswith("router 0 node 0")

    def test_render_cfg_star_needs_out(self, tmp_path, capsys):
        p = tmp_path / "star.json"
        p.write_text(json.dumps({"name": "s", "kind": "star", "nodes": 5,
                                 "params": {"leaves": 4},
                                 "link_attrs": {"bandwidth_GBs": 400,
                                                "latency_ns": 100}}))
        cmd_topology_render(Ctx(verbosity=0), SimpleNamespace(
            ir=str(p), format="cfg", out=None))
        assert "needs --out" in capsys.readouterr().err

    def test_render_cfg_star_sidecar(self, tmp_path):
        p = tmp_path / "star.json"
        p.write_text(json.dumps({"name": "s", "kind": "star", "nodes": 5,
                                 "params": {"leaves": 4},
                                 "link_attrs": {"bandwidth_GBs": 400,
                                                "latency_ns": 100}}))
        out = str(tmp_path / "star.cfg")
        cmd_topology_render(Ctx(verbosity=0), SimpleNamespace(
            ir=str(p), format="cfg", out=out))
        cfg = Path(out).read_text()
        assert "network_file = " in cfg and cfg.index("network_file") > 0
        side = Path(str(tmp_path / "star.anynet"))
        assert side.exists() and len(side.read_text().splitlines()) == 5

    def test_stats_table_and_file(self, tmp_path, capsys):
        cmd_topology_stats(Ctx(verbosity=0), SimpleNamespace(
            ir=_write_ir(tmp_path), out=None))
        assert "diameter=6" in capsys.readouterr().out
        out = str(tmp_path / "stats.json")
        cmd_topology_stats(Ctx(verbosity=0), SimpleNamespace(
            ir=_write_ir(tmp_path), out=out))
        assert json.loads(Path(out).read_text())["edges"] == 24

    def test_render_bad_ir_fails(self, tmp_path, capsys):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(_doc(kind="hypercube")))
        cmd_topology_render(Ctx(verbosity=0), SimpleNamespace(
            ir=str(p), format="ascii", out=None))
        assert "unknown kind" in capsys.readouterr().err

    def test_diff_missing_ets_fails(self, tmp_path, capsys):
        from unittest.mock import patch
        with patch("veritx_dse.core.paths.RESULTS_DIR", tmp_path):
            cmd_topology_diff(Ctx(verbosity=0), SimpleNamespace(
                ir=_write_ir(tmp_path), ets=str(tmp_path / "nope.et"),
                system_config=None, memory_config=None, timeout=60,
                booksim_flit_bytes=64))
        assert not list(tmp_path.glob("topology-diff/*/diff_*.json"))

    def test_diff_missing_ranks_fails(self, tmp_path, capsys):
        from unittest.mock import patch
        lonely = tmp_path / "lonely.et"
        lonely.write_bytes(b"junk")
        (tmp_path / "lonely.et.0.et").write_bytes(b"junk")
        with patch("veritx_dse.core.paths.RESULTS_DIR", tmp_path):
            cmd_topology_diff(Ctx(verbosity=0), SimpleNamespace(
                ir=_write_ir(tmp_path), ets=str(lonely),
                system_config=None, memory_config=None, timeout=60,
                booksim_flit_bytes=64))
        assert not list(tmp_path.glob("topology-diff/*/diff_*.json"))


needs_bins = pytest.mark.skipif(
    not ASTRA_BS_BIN.exists(),
    reason="AstraSim_BookSim2 frontend binary not built",
)


@needs_bins
class TestLiveDiff:
    def test_mesh16_two_legs_agree(self, tmp_path):
        """End-to-end: mesh16 IR, one-coll.et (16 ranks), both frontends."""
        import os
        ana = os.environ.get("ANALYTICAL_BIN")
        cands = [Path(ana)] if ana else []
        from veritx_dse.core.paths import REPO
        cands.append(REPO / "third_party" / "astra-sim" / "astra-sim" / "build"
                     / "astra_analytical" / "build" / "AnalyticalAstra" / "bin"
                     / "AnalyticalAstra")
        if not any(p.is_file() for p in cands):
            pytest.skip("AnalyticalAstra frontend not built")
        from unittest.mock import patch
        import veritx_dse.core.paths as _paths
        with patch.object(_paths, "RESULTS_DIR", tmp_path):
            cmd_topology_diff(Ctx(verbosity=0), SimpleNamespace(
                ir=_write_ir(tmp_path), ets=str(FIX / "one-coll.et"),
                system_config=str(FIX / "system.json"),
                memory_config=str(FIX / "memory.json"),
                timeout=300, booksim_flit_bytes=64))
        results = list(tmp_path.glob("topology-diff/*/diff_*.json"))
        assert len(results) == 1
        result = json.loads(results[0].read_text())
        assert result["status"] == "ok"
        assert result["booksim_leg"]["cycles"] > 0
        assert result["analytical_leg"]["cycles"] > 0
        assert result["booksim_leg"]["plat_stats"] is not None
        assert result["divergence"]["verdict"] in ("agree", "close", "diverge")

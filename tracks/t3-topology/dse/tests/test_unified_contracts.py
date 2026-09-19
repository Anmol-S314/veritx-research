"""Phase 4b unified-architecture contracts.

Locks in: evaluator numeric convergence (4a), the timeloop energy leg's full
error/success contract, live compare + pareto happy paths against the real
BookSim binary, and evaluate/certify/where validation surfaces. Fast except
the two live-sim tests (tiny 4-packet trace, mesh_4x4).
"""
import importlib.util
import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from veritx_dse.core.logging import Ctx


def _read_varint(buf, i):
    shift = 0
    val = 0
    while True:
        x = buf[i]
        i += 1
        val |= (x & 0x7F) << shift
        shift += 7
        if not (x & 0x80):
            return val, i


def _attr_wire_fields(pb):
    """{attr_name: (value_field_number, value)} for scalar attrs in a Node."""
    out = {}
    i = 0
    while i < len(pb):
        tag, i = _read_varint(pb, i)
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            _, i = _read_varint(pb, i)
        elif wire == 2:
            ln, i = _read_varint(pb, i)
            payload = pb[i:i + ln]
            i += ln
            if field != 10:
                continue
            j = 0
            name = None
            val = None
            while j < len(payload):
                t, j = _read_varint(payload, j)
                f2, w2 = t >> 3, t & 7
                if w2 == 0:
                    v, j = _read_varint(payload, j)
                    if f2 != 1:
                        val = (f2, v)
                elif w2 == 2:
                    l2, j = _read_varint(payload, j)
                    q = payload[j:j + l2]
                    j += l2
                    if f2 == 1:
                        name = q.decode()
            if name and val is not None:
                out[name] = val
        else:
            break
    return out


@pytest.fixture
def ctx(tmp_path):
    return Ctx(verbosity=0, log_file=str(tmp_path / "test.log"))


@pytest.fixture
def tiny4_trace(tmp_path):
    p = tmp_path / "tiny4.trace"
    p.write_text("0 0 0 1 4\n100 1 0 2 4\n200 2 0 3 4\n300 3 0 0 4\n")
    return str(p)


def _load_pareto_module():
    from veritx_dse.core.paths import REPO
    spec = importlib.util.spec_from_file_location(
        "mwp", str(Path(REPO) / "tracks/t3-topology/dse/veritx_dse/tools/multi_workload_pareto.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 4a convergence lock ──────────────────────────────────────────────────

class TestEvaluatorConvergence:
    """ITERATIVE == PARETO measurement protocol; BO keeps throughput identity."""

    def test_iterative_matches_pareto_protocol(self):
        from veritx_dse.synthesis.evaluator import ITERATIVE_PRESET as I, PARETO_PRESET as P
        for field in ("sample_period", "span_min", "span_margin", "max_samples",
                      "sim_type", "num_vcs", "vc_buf_size", "packet_size",
                      "latency_thres", "warmup_periods", "wait_for_tail_credit",
                      "injection_rate", "prefer_honest", "use_last_match"):
            assert getattr(I, field) == getattr(P, field), field

    def test_trace_configs_share_protocol(self):
        from veritx_dse.synthesis.evaluator import (
            build_trace_config, BO_PRESET, ITERATIVE_PRESET)
        Path("/tmp/_t4a.trace").write_text("0 0 0 1 4\n100 1 0 2 4\n")
        bo = build_trace_config("/tmp/_t4a.anynet", "/tmp/_t4a.trace", 42, BO_PRESET)
        it = build_trace_config("/tmp/_t4a.anynet", "/tmp/_t4a.trace", 42, ITERATIVE_PRESET)
        for line in ("sample_period = 50000;", "max_samples = 5;", "warmup_periods = 1;"):
            assert line in bo, f"BO: {line}"
            assert line in it, f"IT: {line}"
        assert "wait_for_tail" not in bo + it

    def test_bo_keeps_throughput_identity(self):
        from veritx_dse.synthesis.evaluator import (
            build_trace_config, build_matrix_config, BO_PRESET)
        Path("/tmp/_t4a.trace").write_text("0 0 0 1 4\n")
        bo = build_trace_config("/tmp/_t4a.anynet", "/tmp/_t4a.trace", 42, BO_PRESET)
        assert "sim_type = throughput;" in bo
        assert "latency_thres" not in bo  # cutoff undefined for throughput scoring
        mx = build_matrix_config("/tmp/_t4a.anynet", "/tmp/_t4a.mat", BO_PRESET)
        assert "sample_period = 100;" in mx and "max_samples = 5;" in mx
        assert "warmup_periods = 1;" in mx and "injection_rate = 0.04;" in mx


# ── Timeloop energy leg: full contract ───────────────────────────────────

class TestEnergyLeg:
    def _ns(self):
        import veritx_dse.cli.cli as cli_mod
        return cli_mod

    def test_missing_binary(self, ctx, tmp_path, monkeypatch):
        cli_mod = self._ns()
        monkeypatch.setattr(cli_mod, "REPO", tmp_path)
        r = cli_mod._run_energy_leg(ctx, tmp_path, budget=10)
        assert r["error"].startswith("timeloop-mapper not found")

    def test_missing_configs(self, ctx, tmp_path, monkeypatch):
        cli_mod = self._ns()
        (tmp_path / "third_party" / "timeloop" / "bin").mkdir(parents=True)
        (tmp_path / "third_party" / "timeloop" / "bin" / "timeloop-mapper").touch()
        monkeypatch.setattr(cli_mod, "REPO", tmp_path)
        monkeypatch.setattr(cli_mod, "DSE_DIR", tmp_path / "t3")
        r = cli_mod._run_energy_leg(ctx, tmp_path, budget=10)
        assert "timeloop configs missing" in r["error"]
        assert "mapper.yaml" in r["error"]

    def _with_bin_and_configs(self, tmp_path, monkeypatch):
        import veritx_dse.cli.cli as cli_mod
        (tmp_path / "third_party" / "timeloop" / "bin").mkdir(parents=True)
        (tmp_path / "third_party" / "timeloop" / "bin" / "timeloop-mapper").touch()
        tl = tmp_path / "timeloop"  # sibling of DSE_DIR, like track/timeloop is of dse/
        tl.mkdir(parents=True)
        for f in ("mapper.yaml", "arch.yaml", "problem.yaml"):
            (tl / f).write_text("# fake\n")
        monkeypatch.setattr(cli_mod, "REPO", tmp_path)
        monkeypatch.setattr(cli_mod, "DSE_DIR", tmp_path / "t3")
        return cli_mod, tl

    def test_timeout(self, ctx, tmp_path, monkeypatch):
        cli_mod, _ = self._with_bin_and_configs(tmp_path, monkeypatch)
        monkeypatch.setattr(subprocess, "run", _raise_timeout)
        r = cli_mod._run_energy_leg(ctx, tmp_path, budget=10)
        assert r["error"] == "timeloop-mapper timed out after 10s"

    def test_nonzero_exit_surfaces_tail(self, ctx, tmp_path, monkeypatch):
        from types import SimpleNamespace
        cli_mod, _ = self._with_bin_and_configs(tmp_path, monkeypatch)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
            returncode=1, stdout="", stderr="line1\nboom\n"))
        r = cli_mod._run_energy_leg(ctx, tmp_path, budget=10)
        assert "timeloop-mapper exit 1" in r["error"] and "boom" in r["error"]

    def test_no_stats_file(self, ctx, tmp_path, monkeypatch):
        from types import SimpleNamespace
        cli_mod, _ = self._with_bin_and_configs(tmp_path, monkeypatch)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="", stderr=""))
        r = cli_mod._run_energy_leg(ctx, tmp_path, budget=10)
        assert r["error"] == "timeloop ran but wrote no stats file"

    def test_parse_failure(self, ctx, tmp_path, monkeypatch):
        from types import SimpleNamespace
        import energy_report
        cli_mod, tl = self._with_bin_and_configs(tmp_path, monkeypatch)
        (tl / "timeloop-mapper.stats.txt").write_text("garbage\n")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="", stderr=""))
        monkeypatch.setattr(energy_report, "parse_energy", _raise_parse)
        r = cli_mod._run_energy_leg(ctx, tmp_path, budget=10)
        assert r["error"].startswith("energy_report parse failed")

    def test_ok_copies_artifacts(self, ctx, tmp_path, monkeypatch):
        from types import SimpleNamespace
        import energy_report
        cli_mod, tl = self._with_bin_and_configs(tmp_path, monkeypatch)
        (tl / "timeloop-mapper.stats.txt").write_text("fake stats\n")
        (tl / "timeloop-mapper.map+stats.xml").write_text("<map/>\n")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="", stderr=""))
        monkeypatch.setattr(energy_report, "parse_energy",
                            lambda text: {"energy_uJ": 1.5, "edp_uJ_cycles": 3.0,
                                          "dropped_none": None})
        run_dir = tmp_path / "rundir"
        run_dir.mkdir()
        r = cli_mod._run_energy_leg(ctx, run_dir, budget=10)
        assert r["status"] == "ok" and r["energy_uJ"] == 1.5
        assert "dropped_none" not in r  # None values filtered
        assert (run_dir / "timeloop-mapper.stats.txt").exists()
        assert (run_dir / "timeloop-mapper.map+stats.xml").exists()


def _raise_timeout(*a, **k):
    raise subprocess.TimeoutExpired(cmd="timeloop-mapper", timeout=10)


def _raise_parse(text):
    raise ValueError("no energy section")


# ── Live happy paths (real BookSim binary, tiny trace) ──────────────────

class TestLiveHappyPaths:
    def test_compare_mesh4x4_ok(self, ctx, tiny4_trace):
        from veritx_dse.cli.pipeline import run_compare
        from veritx_dse.model.presets import lookup_topo
        res = run_compare(ctx, tiny4_trace, [("mesh_4x4", lookup_topo("mesh_4x4"))],
                          seeds=1, timeout=120)
        assert len(res.summary) == 1
        row = res.summary[0]
        assert row["mean"] > 0 and row["n"] == 1
        assert all("error" not in r for r in res.results)
        assert res.results[0]["honest_latency"] > 0  # proves the binary ran

    def test_pareto_eval_once_ok(self, tiny4_trace):
        mwp = _load_pareto_module()
        spec = mwp._lookup("mesh_4x4")
        out = mwp.eval_once(tiny4_trace, spec, seed=42, timeout=120)
        assert out["status"] == "ok", out.get("error")
        assert out["latency"] is not None and out["latency"] > 0
        assert out["nodes"] == 16 and out["edges"] == 24  # mesh_4x4: 2*4*3
        assert "error" not in out


# ── Validation surfaces (no binary needed) ─────────────────────────────

class TestModelRegistry:
    """Phase 4d: one spelling, one NPU rule, loud unknown models."""

    def test_normalize_collective_spellings(self):
        from veritx_dse.model.presets import normalize_collective as n
        assert n("ALL_REDUCE") == n("all-reduce") == n("AllReduce") == "allreduce"
        assert n("ALL_TO_ALL") == n("alltoall") == "alltoall"
        assert n("reduce_scatter") == "reducescatter"
        with pytest.raises(ValueError):
            n("allcombine")

    def test_parallel_world_size(self):
        from veritx_dse.model.presets import parallel_world_size as w
        assert w(8, 8) == 64 and w(16, 1, 4) == 64 and w(2, 2, 2, 2) == 16

    def test_resolve_spec_unknown_raises(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        from generate_chakra_trace import ChakraTraceGenerator
        gen = ChakraTraceGenerator()
        assert gen.resolve_spec("llama7b")["hidden_size"] == 4096
        with pytest.raises(ValueError, match="unknown model"):
            gen.resolve_spec("typo_model_xyz")

    def test_get_model_none_contract(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "lib"))
        from t3models import get_model
        assert get_model("definitely_not_a_model_xyz") is None
        assert get_model("llama7b")["hidden_size"] == 4096

    def test_collective_wire_codes(self, capsys):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        from generate_chakra_trace import ChakraTraceGenerator
        gen = ChakraTraceGenerator()
        assert gen.build_collective_trace(comm_type="ALL_REDUCE")[1]["attr"]["comm_type"] == 0
        assert gen.build_collective_trace(comm_type="all_to_all")[1]["attr"]["comm_type"] == 6
        assert gen.build_collective_trace(comm_type="ALL_GATHER")[1]["attr"]["comm_type"] == 2
        assert "only supports ALL_REDUCE" not in capsys.readouterr().err
        with pytest.raises(ValueError):
            gen.build_collective_trace(comm_type="ALL_COMBINE")

    def test_collective_attr_wire_fields_match_feeder(self):
        """Binary ET must use the value field ETFeederNode reads.

        The feeder reads comm_type/comm_size via int64_val (proto field 9).
        Writing them as uint64_val (13) decodes silently as 0, so
        Sys::generate_collective's while(size>0) never runs and the run stalls
        in zero-injection drain.
        """
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        from generate_chakra_trace import (
            ChakraTraceGenerator, encode_chakra_node_protobuf,
        )
        node = ChakraTraceGenerator().build_collective_trace(
            comm_type="ALL_GATHER")[1]
        fields = _attr_wire_fields(encode_chakra_node_protobuf(node))
        assert fields["comm_type"] == (9, 2)
        assert fields["comm_size"][0] == 9
        assert fields["comm_size"][1] == 16777216

    def test_model_allreduce_attr_uses_int64(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        from generate_chakra_trace import (
            COMM_COLL_NODE, ChakraTraceGenerator, encode_chakra_node_protobuf,
        )
        nodes = ChakraTraceGenerator().build_llama7b_trace(num_layers=1)
        comm = next(n for n in nodes if n["type"] == COMM_COLL_NODE)
        fields = _attr_wire_fields(encode_chakra_node_protobuf(comm))
        assert fields["comm_size"][0] == 9 and fields["comm_size"][1] > 0
        assert fields["comm_type"] == (9, 0)  # ALL_REDUCE

    def test_et_coll_type_resume_key(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        from run_astrasim import _et_coll_type, _workload_tag
        assert _et_coll_type({"is_collective_microbenchmark": True, "model_name": "ALL_GATHER"}) == "allgather"
        assert _et_coll_type({"model_name": "llama7b"}) is None
        # bare label again (no substitution suffix); resume key carries the type
        assert _workload_tag({"model_name": "ALL_GATHER", "is_collective_microbenchmark": True}) == "ALL_GATHER (TP=1, PP=1)"


class TestSizesRouting:
    """Astrasim cfg-dir routing: explicit --sizes wins, auto sniffs suffix."""

    def _select(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        from run_astrasim import select_cfgdir
        return select_cfgdir

    def test_explicit_wins(self):
        s = self._select()
        assert s("baseline", "n64").name == "n64"
        assert s("baseline_N16_N16_N64", "n16").name == "n16"
        assert s("baseline", "legacy").name == "configs"

    def test_auto_sniffs_suffix(self):
        s = self._select()
        assert s("baseline_N16_N16_N64", "auto").name == "n64"
        assert s("foo_N16", "auto").name == "n16"
        assert s("baseline", "auto").name == "configs"


class TestPacketConservation:
    """chakra_to_dse: emitted flits == message flits exactly (cap trims,
    never fabricates); per-packet cap honored; override plumbing works."""

    def _gen(self):
        # chakra_to_dse moved to veritx_dse/tools/ during consolidation;
        # the package seam (veritx_dse.tools) is the import path now.
        from veritx_dse.tools.chakra_to_dse import generate_dse_trace, FLIT_BYTES
        return generate_dse_trace, FLIT_BYTES

    def test_remainder_trimmed(self):
        gen, FLIT_BYTES = self._gen()
        op = {"comp_us": 0, "comm_type": "ALLREDUCE",
              "comm_bytes": 20 * FLIT_BYTES}  # 20 flits: non-multiple of 16
        for coll in ("ring", "star", "tree", "butterfly"):
            sizes = [e[4] for e in gen([op], [0, 1, 2, 3], collective=coll)]
            assert sizes and max(sizes) <= 16, (coll, sizes)

    def test_ring_conserves_bytes(self):
        gen, FLIT_BYTES = self._gen()
        op = {"comp_us": 0, "comm_type": "ALLREDUCE",
              "comm_bytes": 20 * FLIT_BYTES}
        entries = gen([op], [0, 1, 2, 3], collective="ring")
        assert sum(e[4] for e in entries) == 4 * 20  # ranks × message flits

    def test_override_honored(self):
        gen, FLIT_BYTES = self._gen()
        op = {"comp_us": 0, "comm_type": "ALLREDUCE",
              "comm_bytes": 40 * FLIT_BYTES}
        sizes = [e[4] for e in gen([op], [0, 1], collective="ring",
                                   pkt_flits_override=8)]
        assert sizes and max(sizes) <= 8


class TestGECMeshHonest:
    """gec_mesh_k8 must build a real mesh, not silent full express.

    Regression: o=0/d=0 once fell through to BookSim's express defaults,
    making gec_mesh bit-identical to gec_express (29.80c twice). The mode
    line is the detector (duplicates print the same mode); the live part
    is binary-gated so clean checkouts stay green.
    """

    def test_cfg_emits_mesh_line(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from veritx_dse.model.presets import lookup_topo
        from veritx_dse.simulation.booksim import build_config
        mesh = lookup_topo("gec_mesh_k8")
        assert mesh is not None and mesh.params.get("mesh") == 1
        assert "mesh = 1;" in build_config(mesh, "/tmp/_t5_g.trace",
                                           sim_type="throughput", ir=0.04)
        exp = lookup_topo("gec_express_k8")
        assert "mesh = 1;" not in build_config(exp, "/tmp/_t5_g.trace",
                                               sim_type="throughput", ir=0.04)

    def _booksim(self):
        repo = Path(__file__).resolve().parents[4]
        cand = repo / "third_party" / "booksim2" / "src" / "booksim"
        if cand.is_file():
            return str(cand)
        import shutil
        return shutil.which("booksim")

    def test_live_modes_differ(self, tmp_path):
        import subprocess
        booksim = self._booksim()
        if not booksim:
            pytest.skip("booksim binary not built")
        modes = {}
        for tag, extra in (("express", "o = 3;"), ("mesh", "o = 1;\nd = 1;\nmesh = 1;")):
            cfg = tmp_path / f"gec_{tag}.cfg"
            cfg.write_text(
                "topology = gec;\nk = 4;\nn = 2;\nc = 1;\n" + extra +
                "routing_function = dor;\nnum_vcs = 4;\nvc_buf_size = 8;\n"
                "packet_size = 8;\ntraffic = uniform;\ninjection_rate = 0.05;\n"
                "use_noc_latency = 0;\n"
                "sample_period = 1000;\nmax_samples = 1;\n")
            r = subprocess.run([booksim, str(cfg)], capture_output=True,
                               text=True, timeout=120)
            out = r.stdout + r.stderr
            modes[tag] = out
        assert "mode=express(p2p)" in modes["express"], modes["express"][-500:]
        assert "mode=mesh" in modes["mesh"], modes["mesh"][-500:]


class TestSpatialBaseName:
    """Spatial config bases never chain tile suffixes (baseline_N16_N16)."""

    def test_strips_chained_suffixes(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        from run_spatial_pipeline import normalize_base_name as n
        assert n("baseline") == "baseline"
        assert n("baseline_N16") == "baseline"
        assert n("baseline_N16_N16_N32") == "baseline"
        assert n("compare_N64") == "compare"
        assert n("dragonfly_iso") == "dragonfly_iso"
        assert n("_N16") == "run"


class TestInputLabels:
    """Phase 4e: uniform LABEL:PATH rule across compare scripts."""

    def test_explicit_label_wins(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        from lib.t3load import input_label
        label, p = input_label("myrun:/tmp/x/sweep.json")
        assert (label, str(p)) == ("myrun", "/tmp/x/sweep.json")

    def test_bare_path_uses_stem(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        from lib.t3load import input_label
        assert input_label("/tmp/x/sweep.json")[0] == "sweep"  # never "tmp"
        assert input_label("rel.json") == ("rel", Path("rel.json"))

class TestValidationSurfaces:
    def test_evaluate_booksim_rejects_k(self):
        from veritx_dse.cli.cli import _resolve_eval_topology
        from argparse import Namespace
        topo, err = _resolve_eval_topology(
            Namespace(topo="mesh", k=1, routing="dim_order"))
        assert topo is None
        assert "k must be >= 2" in err

    def test_evaluate_booksim_missing_trace(self, ctx, tmp_path):
        from veritx_dse.cli.cli import cmd_evaluate_booksim
        cmd_evaluate_booksim(ctx, Namespace(k=4, trace=str(tmp_path / "no.trace"),
                                            topo="mesh_4x4"))
        assert ctx.failed

    def test_certify_flow_missing_model(self, ctx, tmp_path):
        from veritx_dse.cli.cli import cmd_certify_flow
        cmd_certify_flow(ctx, Namespace(model=str(tmp_path / "no.json"),
                                        topo=str(tmp_path / "no.anynet")))
        assert "Traffic model not found" in open(ctx.log_file).read()

    def test_where_miss_teaches(self, ctx):
        from veritx_dse.cli.cli import cmd_where
        cmd_where(ctx, Namespace(name="definitely_not_a_real_asset_xyz", kind="trace"))
        err = open(ctx.log_file).read()
        assert "No trace matching" in err

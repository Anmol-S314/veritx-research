"""Phase 1 T1 — serving preflight refuses before spawning.

Every refusal here is a failure that previously arrived as an expensive or
misleading runtime failure: a missing backend binary (Case 1: ns-3), an
infeasible model/memory placement (Case 2), or a workload the converter
cannot represent (Case 3: PP). Preflight never spawns — a refusal test
passing means the child was never launched, by construction.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.core.errors import ServingPreflightError
from veritx_dse.core.paths import REPO
from veritx_dse.core.serving import preflight_serve

SERVING_ROOT = REPO / "third_party" / "llmservingsim"
needs_serving = pytest.mark.skipif(
    not (SERVING_ROOT / "serving" / "__main__.py").exists(),
    reason="LLMServingSim not vendored",
)

MODEL = "meta-llama/Llama-3.1-8B"


def _shim_llmsim(tmp_path: Path, *, booksim_executable: bool = True,
                 ns3_present: bool = False) -> Path:
    """Synthetic LLMSIM_DIR so binary checks are hermetic (never executed).

    The serving *code* (rules preflight mirrors) is symlinked from the real
    vendored tree — one rule source, no mirror skew. Only the *binaries*
    are synthetic.
    """
    root = tmp_path / "llmsim"
    root.mkdir(parents=True, exist_ok=True)
    for name in ("serving", "configs"):
        link = root / name
        if not link.exists():
            link.symlink_to(SERVING_ROOT / name, target_is_directory=True)
    bs = root / "astra-sim" / "network_frontend" / "booksim2" / "bin" \
        / "AstraSim_BookSim2"
    if booksim_executable is not False:
        bs.parent.mkdir(parents=True, exist_ok=True)
        bs.write_bytes(b"")
        if booksim_executable is True:
            bs.chmod(0o755)
        else:
            bs.chmod(0o644)
    if ns3_present:
        ns = root / "astra-sim" / "extern" / "network_backend" / "ns-3" \
            / "build" / "scratch" / "ns3.42-AstraSimNetwork-default"
        ns.parent.mkdir(parents=True, exist_ok=True)
        ns.write_bytes(b"")
        ns.chmod(0o755)
    return root


def _cluster(tmp_path: Path, instances, name="cluster.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps({
        "num_nodes": 1,
        "nodes": [{
            "num_instances": len(instances),
            "cpu_mem": {"mem_size": 512, "mem_bw": 256, "mem_latency": 0},
            "instances": instances,
        }],
    }))
    return p


def _inst(npu_mem_gb=96, tp_size=1, pp_size=1, num_npus=1, **kw):
    d = {
        "model_name": MODEL,
        "hardware": "RTXPRO6000",
        "npu_mem": {"mem_size": npu_mem_gb, "mem_bw": 1597, "mem_latency": 0},
        "num_npus": num_npus,
        "tp_size": tp_size,
        "pp_size": pp_size,
        "pd_type": None,
    }
    d.update(kw)
    return d


def _dataset(tmp_path: Path) -> Path:
    p = tmp_path / "workload.jsonl"
    p.write_text('{"input_toks": 8, "output_toks": 8}\n')
    return p


def _preflight(tmp_path, instances, *, backend="booksim", cycle_accurate=False,
               dataset=True, cluster=True, **shim_kw):
    llmsim = _shim_llmsim(tmp_path, **shim_kw)
    cp = _cluster(tmp_path, instances) if cluster else tmp_path / "nope.json"
    dp = _dataset(tmp_path) if dataset else tmp_path / "nodata.jsonl"
    return preflight_serve(
        llmsim_dir=llmsim, cluster_path=cp, dataset_path=dp,
        network_backend=backend, cycle_accurate=cycle_accurate,
        cli_dtype=None)


@needs_serving
class TestBackendBinary:
    def test_missing_binary_refuses_before_spawn(self, tmp_path):
        llmsim = _shim_llmsim(tmp_path, booksim_executable=False)
        # remove the file the shim helper skipped: nothing to remove —
        # absence itself is the fixture. Build args directly.
        cp = _cluster(tmp_path, [_inst()])
        dp = _dataset(tmp_path)
        with pytest.raises(ServingPreflightError) as e:
            preflight_serve(
                llmsim_dir=llmsim, cluster_path=cp, dataset_path=dp,
                network_backend="booksim", cycle_accurate=False,
                cli_dtype=None)
        assert e.value.reason == "BACKEND_BINARY_MISSING"
        assert "AstraSim_BookSim2" in str(e.value)

    def test_non_executable_binary_refuses(self, tmp_path):
        with pytest.raises(ServingPreflightError) as e:
            _preflight(tmp_path, [_inst()], booksim_executable="present")
        assert e.value.reason == "BACKEND_BINARY_NOT_EXECUTABLE"

    def test_ns3_absent_binary_is_unavailable_not_stale_path(self, tmp_path):
        with pytest.raises(ServingPreflightError) as e:
            _preflight(tmp_path, [_inst()], backend="ns3")
        assert e.value.reason == "BACKEND_BINARY_MISSING"
        assert "ns3.42-AstraSimNetwork-default" in str(e.value)


@needs_serving
class TestInputs:
    def test_missing_dataset_refuses(self, tmp_path):
        with pytest.raises(ServingPreflightError) as e:
            _preflight(tmp_path, [_inst()], dataset=False)
        assert e.value.reason == "DATASET_MISSING"

    def test_missing_cluster_file_refuses(self, tmp_path):
        with pytest.raises(ServingPreflightError) as e:
            _preflight(tmp_path, [_inst()], cluster=False)
        assert e.value.reason == "CLUSTER_INVALID"

    def test_malformed_cluster_refuses(self, tmp_path):
        llmsim = _shim_llmsim(tmp_path)
        cp = tmp_path / "bad.json"
        cp.write_text("{not json")
        with pytest.raises(ServingPreflightError) as e:
            preflight_serve(
                llmsim_dir=llmsim, cluster_path=cp,
                dataset_path=_dataset(tmp_path),
                network_backend="booksim", cycle_accurate=False,
                cli_dtype=None)
        assert e.value.reason == "CLUSTER_INVALID"


@needs_serving
class TestFeasibility:
    def test_oversized_model_refuses_before_spawn(self, tmp_path):
        """Case 2 shape: Llama-8B weights cannot fit a 1 GiB NPU."""
        with pytest.raises(ServingPreflightError) as e:
            _preflight(tmp_path, [_inst(npu_mem_gb=1)])
        assert e.value.reason == "MODEL_DOES_NOT_FIT"
        msg = str(e.value)
        assert "required_weight_memory_gib" in msg
        assert "available_npu_memory_gib" in msg

    def test_inconsistent_parallelism_refuses(self, tmp_path):
        with pytest.raises(ServingPreflightError) as e:
            _preflight(tmp_path, [_inst(num_npus=3, tp_size=2, pp_size=1)])
        assert e.value.reason == "UNSUPPORTED_PARALLELISM"

    def test_pp_workload_refuses_until_converter_supports_it(self, tmp_path):
        with pytest.raises(ServingPreflightError) as e:
            _preflight(tmp_path, [_inst(num_npus=2, tp_size=1, pp_size=2)])
        assert e.value.reason == "UNSUPPORTED_WORKLOAD_SEMANTIC"
        assert "pp_stage_boundaries" in str(e.value)

    def test_cycle_accurate_outside_booksim_refuses(self, tmp_path):
        llmsim = _shim_llmsim(tmp_path)
        ana = llmsim / "astra-sim" / "astra-sim" / "build" / "astra_analytical" \
            / "build" / "AnalyticalAstra" / "bin" / "AnalyticalAstra"
        ana.parent.mkdir(parents=True, exist_ok=True)
        ana.write_bytes(b"")
        ana.chmod(0o755)
        with pytest.raises(ServingPreflightError) as e:
            _preflight(tmp_path, [_inst()], backend="analytical",
                       cycle_accurate=True)
        assert e.value.reason == "UNSUPPORTED_EXECUTION_MODE"

    def test_valid_pp_free_config_passes(self, tmp_path):
        binaries = _preflight(tmp_path, [_inst()])
        assert binaries, "passing preflight returns the binary paths"
        assert all(Path(b).is_file() for b in binaries)

"""PR6 Phase 4 — serving slice verdicts (pure) + goldens (live).

Terminal truth here is retirement + artifacts + process state — never
the liveness classifier, never exit code alone. Replay specs cannot
enter the slice at all (refused at the boundary); replay-as-negative
is additionally pinned at the gate predicate elsewhere.
"""
import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.core.experiment_serving import (
    check_fabric_activity,
    check_involved_dim_tripwire,
    fabric_evidence,
    run_serving_experiment,
)
from veritx_dse.core.errors import ServingResultError
from veritx_dse.core.serving import (
    engine_identity_from_binaries,
    fidelity_for_mode,
    mode_for_backend,
    serving_provenance,
)
from veritx_dse.core.spec import SpecError

from veritx_dse.core.paths import REPO  # noqa: E402
LLMSIM = REPO / "third_party" / "llmservingsim"
BOOKSIM_BIN = REPO / "third_party" / "astra-sim" / "astra-sim" / \
    "network_frontend" / "booksim2" / "bin" / "AstraSim_BookSim2"
ANALYTICAL_AWARE_BIN = REPO / "third_party" / "llmservingsim" / "astra-sim" \
    / "astra-sim" / "build" / "astra_analytical" / "build" \
    / "AnalyticalAstra" / "bin" / "AnalyticalAstra"
ANALYTICAL_UNAWARE_BIN = REPO / "third_party" / "llmservingsim" / "astra-sim" \
    / "build" / "astra_analytical_unaware" / "build" / "bin" \
    / "AnalyticalAstraUnaware"

needs_serving = pytest.mark.skipif(
    not (LLMSIM / "serving" / "__main__.py").exists(),
    reason="LLMServingSim not vendored")
needs_binary = pytest.mark.skipif(not BOOKSIM_BIN.exists(),
                                  reason="AstraSim_BookSim2 not built")
needs_analytical = pytest.mark.skipif(
    not (ANALYTICAL_AWARE_BIN.exists() and ANALYTICAL_UNAWARE_BIN.exists()),
    reason="AnalyticalAstra frontends not built")


def _spec_dict(**serving_kw):
    serving = {"cluster": "single_tp2_ep2", "dataset": "example",
               "num_reqs": 1}
    serving.update(serving_kw)
    return {
        "name": "pr6t",
        "workload": {"id": "w", "trace": "archive/inputs/traces/x.trace"},
        "system": {"nodes": 1},
        # Study-integrity P0: serving specs carry NO network block — the
        # serving CLUSTER owns fabric intent (single_tp2_ep2 lowers to
        # mesh k=2 n=1 dor); a standalone preset here is false intent.
        "simulation": {"mode": "serving", "timeout_s": 900},
        "serving": serving,
    }


class TestVerdictHelpers:
    def test_fabric_evidence_counts(self):
        err = ("[LEDGER][TOPO] npus=2 dims=2,2\n"
               "[LEDGER][COLL_SUBMIT] x involved_dims=[true,false]\n"
               "[LEDGER][COLL_COMPLETE] y\n"
               "[LEDGER][STATE] z retired_flits=1200 tail_deliveries=9\n")
        ev = fabric_evidence(err)
        assert ev["coll_completes"] == 1
        assert ev["max_retired_flits"] == 1200
        assert ev["submit_vectors"] == [[True, False]]
        assert ev["topo_dims"] == [2, 2]

    def test_tripwire_passes_scoped_multidim(self):
        ev = {"topo_dims": [2, 2],
              "submit_vectors": [[True, False], [True, True]],
              "coll_completes": 2, "max_retired_flits": 5}
        check_involved_dim_tripwire(ev)  # must not raise

    def test_tripwire_fails_fabricated_length(self):
        ev = {"topo_dims": [2, 2],
              "submit_vectors": [[True, True, True, True]],
              "coll_completes": 1, "max_retired_flits": 5}
        with pytest.raises(ServingResultError) as e:
            check_involved_dim_tripwire(ev)
        assert e.value.reason == "FABRICATION_SUSPECT"

    def test_tripwire_fails_unscoped_multidim(self):
        ev = {"topo_dims": [2, 2],
              "submit_vectors": [[True, True]],
              "coll_completes": 1, "max_retired_flits": 5}
        with pytest.raises(ServingResultError) as e:
            check_involved_dim_tripwire(ev)
        assert e.value.reason == "SCOPING_ABSENT"

    def test_tripwire_exempts_single_dim(self):
        ev = {"topo_dims": [2],
              "submit_vectors": [[True, True, True, True]],
              "coll_completes": 1, "max_retired_flits": 5}
        check_involved_dim_tripwire(ev)  # 1-dim: fallback unread, exempt


class TestAnalyticalIdentity:
    """PR7: backend engine identity is data, never prose.

    The N-dim→unaware fallback already existed as a printed notice;
    these tests pin it as machine-readable result fields (plan item 8.2:
    "make it data").
    """

    def test_analytical_1dim_is_congestion_aware(self):
        assert mode_for_backend("analytical", False) == "REAL_SIMULATION"
        assert (fidelity_for_mode("analytical", "REAL_SIMULATION")
                == "ANALYTICAL_ESTIMATE")
        ident = engine_identity_from_binaries(
            ["/x/build/AnalyticalAstra/bin/AnalyticalAstra"])
        assert ident == {"network_engine": "congestion_aware",
                         "engine_selected_by": "topology_dims"}

    def test_engine_identity_follows_unaware_binary(self):
        ident = engine_identity_from_binaries(
            ["/x/AnalyticalAstra", "/y/AnalyticalAstraUnaware"])
        assert ident["network_engine"] == "congestion_unaware"

    def test_engine_identity_without_analytical_binary_refused(self):
        with pytest.raises(ValueError, match="no analytical binary"):
            engine_identity_from_binaries(["/x/AstraSim_BookSim2"])

    def test_provenance_carries_engine_identity(self):
        base = serving_provenance(
            engine="llmservingsim", network_backend="analytical",
            network_mode="REAL_SIMULATION", semantic_losses=[])
        p = {**base,
             **engine_identity_from_binaries(
                 ["/x/build/AnalyticalAstra/bin/AnalyticalAstra"]),
             "fidelity": fidelity_for_mode("analytical",
                                           "REAL_SIMULATION")}
        assert p["network_engine"] == "congestion_aware"
        assert p["fidelity"] == "ANALYTICAL_ESTIMATE"
        assert p["semantic_losses"] == []


class TestAnalyticalFabric:
    """PR7: fabric evidence is backend-aware — flit accounting exists
    only in the BookSim frontend; analytical runs prove activity via
    collective construction/completion in the shared ASTRA ledger."""

    def test_analytical_requires_collectives(self):
        ev = {"coll_completes": 0, "max_retired_flits": 0}
        with pytest.raises(ServingResultError) as e:
            check_fabric_activity(ev, "analytical")
        assert e.value.reason == "NO_FABRIC_ACTIVITY"

    def test_analytical_passes_on_collectives(self):
        ev = {"coll_completes": 3, "max_retired_flits": 0}
        check_fabric_activity(ev, "analytical")  # must not raise

    def test_booksim_still_requires_flits(self):
        ev = {"coll_completes": 2, "max_retired_flits": 0}
        with pytest.raises(ServingResultError) as e:
            check_fabric_activity(ev, "booksim")
        assert e.value.reason == "NO_FABRIC_ACTIVITY"

    def test_booksim_flits_satisfy(self):
        ev = {"coll_completes": 2, "max_retired_flits": 64}
        check_fabric_activity(ev, "booksim")  # must not raise


class TestSliceRefusals:
    def test_non_serving_mode_rejected(self, tmp_path):
        d = _spec_dict()
        d["simulation"] = {"mode": "latency"}
        with pytest.raises(SpecError, match="serving"):
            run_serving_experiment(d, repo=tmp_path)

    def test_replay_spec_rejected(self, tmp_path):
        with pytest.raises(SpecError, match="cycle_accurate"):
            run_serving_experiment(_spec_dict(cycle_accurate=False),
                                   repo=tmp_path)

    def test_analytical_reaches_preflight(self, tmp_path, monkeypatch):
        """PR7: the slice boundary opens for analytical — the spec gets
        past validate/resolve and dies (only) in preflight, which owns
        binary resolution. Full-run proof lives in the goldens."""
        import veritx_dse.core.experiment_serving as es
        from veritx_dse.core.errors import ServingPreflightError
        monkeypatch.setattr(es, "preflight_serve",
                            lambda **kw: (_ for _ in ()).throw(
                                ServingPreflightError("BACKEND_BINARY_MISSING",
                                                      "boom")))
        monkeypatch.setattr("veritx_dse.core.runs.VERITX_RUNS_DIR",
                            tmp_path / "runs")
        d = _spec_dict(network_backend="analytical")
        d["serving"]["cycle_accurate"] = False
        run = run_serving_experiment(d, repo=tmp_path)
        assert run.state == "CANCELLED"
        results = json.loads(
            (run.root / "manifest.json").read_text())["results"]
        assert "BACKEND_BINARY_MISSING" in results[0]["error"]

    def test_stochastic_rejected(self, tmp_path):
        d = _spec_dict()
        d["replication"] = {"mode": "stochastic", "seeds": [1, 2]}
        with pytest.raises(SpecError, match="deterministic"):
            run_serving_experiment(d, repo=tmp_path)

    def test_unknown_fixture_rejected(self, tmp_path):
        with pytest.raises(SpecError, match="unknown serving cluster"):
            run_serving_experiment(_spec_dict(cluster="nope"),
                                   repo=tmp_path)

    @needs_serving
    @needs_binary
    def test_preflight_failure_cancels_without_success(
            self, tmp_path, monkeypatch):
        """Invalid execution leaves CANCELLED evidence, never success."""
        import veritx_dse.core.experiment_serving as es
        from veritx_dse.core.errors import ServingPreflightError
        monkeypatch.setattr(es, "preflight_serve",
                            lambda **kw: (_ for _ in ()).throw(
                                ServingPreflightError("CLUSTER_INVALID",
                                                      "boom")))
        monkeypatch.setattr("veritx_dse.core.runs.VERITX_RUNS_DIR",
                            tmp_path / "runs")
        run = run_serving_experiment(_spec_dict(), repo=tmp_path)
        assert run.state == "CANCELLED"
        results = json.loads(
            (run.root / "manifest.json").read_text())["results"]
        assert "CLUSTER_INVALID" in results[0]["error"]


@needs_serving
@needs_binary
def _result(run):
    return json.loads((run.root / "manifest.json").read_text())["results"][0]


class TestFastNegatives:
    """Every verdict arm, without paying for real simulation twice."""

    def _fake_run(self, tmp_path, monkeypatch, csv_rows=None,
                  returncode=0, timeout=False, cluster="single_tp2_ep2",
                  write_fabric=True, fabric_override=None):
        import veritx_dse.core.process as proc

        from veritx_dse.core.paths import serving_fixture
        from veritx_dse.core.serving import (
            render_expected_booksim_config,
            resolve_serving_fabric_identity,
        )
        # The fake child writes the SAME fabric artifact the real child
        # writes (config.cfg under the run-owned inputs root), derived
        # from the same cluster→fabric resolution the slice pins in the
        # experiment hash — it models the child's contract, it does not
        # bypass the checker.
        expected = resolve_serving_fabric_identity(
            serving_fixture("cluster", cluster))
        if fabric_override:
            expected = {**expected, **fabric_override}

        # Minimal honest fabric evidence: single-dim topology, one
        # collective completed, nonzero retired flits.
        err = ("[LEDGER][TOPO] npus=1 dims=1\n"
               "[LEDGER][COLL_COMPLETE] x\n"
               "[LEDGER][STATE] y retired_flits=64 tail_deliveries=2\n")

        class R:
            wall_time_s = 1.5

        def fake(cmd, **kw):
            csv_path = [a for a in cmd if a.endswith(".csv")]
            if csv_rows is not None and csv_path:
                with open(csv_path[0], "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["instance id", "request id", "arrival",
                                "end_time", "latency", "TTFT", "TPOT",
                                "ITL"])
                    w.writerows(csv_rows)
            if write_fabric and "--inputs-root" in cmd:
                cfg_dir = (Path(cmd[cmd.index("--inputs-root") + 1])
                           / "booksim")
                cfg_dir.mkdir(parents=True, exist_ok=True)
                (cfg_dir / "config.cfg").write_text(
                    render_expected_booksim_config(expected))
            # Phase 9: the real child saves trace text under the
            # run-owned --inputs-root; a run without saved traces fails
            # closed at canonicalization. The fake must save one too —
            # same layout and grammar as trace_generator._write_trace.
            if "--inputs-root" in cmd:
                tdir = (Path(cmd[cmd.index("--inputs-root") + 1])
                        / "trace" / "fake_hw" / "fake_model")
                tdir.mkdir(parents=True, exist_ok=True)
                (tdir / "instance0_batch1.txt").write_text(
                    "SYNTHETIC\\t\\tmodel_parallel_NPU_group: 1\n"
                    "1\n"
                    "embedding_0 1000 LOCAL 1024 LOCAL 2048 LOCAL 512"
                    " NONE 0 1\n")
            if timeout:
                raise subprocess.TimeoutExpired(cmd, 1)
            r = R()
            r.returncode, r.stdout, r.stderr = returncode, "out", err
            return r

        monkeypatch.setattr(proc, "supervised_run", fake)
        monkeypatch.setattr("veritx_dse.core.runs.VERITX_RUNS_DIR",
                            tmp_path / "runs")
        return run_serving_experiment(_spec_dict(), repo=tmp_path)

    def test_exact_retirement_succeeds(self, tmp_path, monkeypatch):
        run = self._fake_run(
            tmp_path, monkeypatch,
            csv_rows=[["0", "0", "100", "1100", "1000", "700", "100",
                       "[100]"]],
            returncode=0)
        assert run.state == "SUCCEEDED"
        res = _result(run)
        # P0 pin: expected cluster fabric is in the immutable spec hash
        # and the executed record matches it.
        spec = json.loads((run.root / "spec.resolved.json").read_text())
        assert spec["serving"]["expected_fabric"]["topology"] == "mesh"
        assert spec["serving"]["expected_fabric"]["k"] == 2
        assert res["executed_fabric"]["topology"] == "mesh"
        assert res["executed_fabric"]["routing"] == "dor"
        assert res["executed_fabric"]["size"] == {"k": "2", "n": "1"}

    def test_fabric_mismatch_fails(self, tmp_path, monkeypatch):
        """Executed fabric differs from the cluster-derived expected
        fabric → FAILED with FABRIC_INTENT_MISMATCH, never certified."""
        run = self._fake_run(
            tmp_path, monkeypatch,
            csv_rows=[["0", "0", "100", "1100", "1000", "700", "100",
                       "[100]"]],
            fabric_override={"k": 4, "n": 1})
        assert run.state == "FAILED"
        res = _result(run)
        assert res["error"] == "FABRIC_INTENT_MISMATCH"
        assert res["expected_fabric"]["k"] == 2
        assert res["executed_fabric"]["size"] == {"k": "4", "n": "1"}

    def test_missing_fabric_evidence_fails(self, tmp_path, monkeypatch):
        """No executed-fabric record → FAILED (never SUCCEEDED, never
        certified): a run that cannot show what it executed is not
        science, however healthy its metrics look."""
        run = self._fake_run(
            tmp_path, monkeypatch,
            csv_rows=[["0", "0", "100", "1100", "1000", "700", "100",
                       "[100]"]],
            write_fabric=False)
        assert run.state == "FAILED"
        res = _result(run)
        assert res["error"] == "EXECUTED_FABRIC_UNRECORDED"

    def test_retirement_mismatch_fails(self, tmp_path, monkeypatch):
        import veritx_dse.core.process as proc

        from veritx_dse.core.paths import serving_fixture
        from veritx_dse.core.serving import (
            render_expected_booksim_config,
            resolve_serving_fabric_identity,
        )
        expected = resolve_serving_fabric_identity(
            serving_fixture("cluster", "single_tp2_ep2"))

        def fake(cmd, **kw):
            if "--inputs-root" in cmd:
                cfg_dir = (Path(cmd[cmd.index("--inputs-root") + 1])
                           / "booksim")
                cfg_dir.mkdir(parents=True, exist_ok=True)
                (cfg_dir / "config.cfg").write_text(
                    render_expected_booksim_config(expected))
            csv_path = [a for a in cmd if a.endswith(".csv")][0]
            with open(csv_path, "w", newline="") as f:
                f.write("instance id,request id,TTFT,TPOT,ITL\n")
            r = type("R", (), {})()
            r.returncode, r.stdout, r.stderr = 0, "out", "err"
            r.wall_time_s = 1.0
            return r

        monkeypatch.setattr(proc, "supervised_run", fake)
        monkeypatch.setattr("veritx_dse.core.runs.VERITX_RUNS_DIR",
                            tmp_path / "runs")
        d = _spec_dict(num_reqs=2)
        run = run_serving_experiment(d, repo=tmp_path)
        assert run.state == "FAILED"
        results = json.loads(
            (run.root / "manifest.json").read_text())["results"]
        assert results[0]["error"] == "RETIREMENT_MISMATCH"

    def test_nonzero_exit_fails(self, tmp_path, monkeypatch):
        run = self._fake_run(tmp_path, monkeypatch, csv_rows=None,
                             returncode=3)
        assert run.state == "FAILED"

    def test_timeout_fails(self, tmp_path, monkeypatch):
        run = self._fake_run(tmp_path, monkeypatch, timeout=True)
        assert run.state == "FAILED"


@needs_serving
@needs_binary
class TestGoldenA:
    """Single-instance TP/EP>1 under REAL_SIMULATION: fabric activity."""

    def test_single_instance_fabric_golden(self, tmp_path, monkeypatch):
        monkeypatch.setattr("veritx_dse.core.runs.VERITX_RUNS_DIR",
                            tmp_path / "runs")
        run = run_serving_experiment(_spec_dict(), repo=tmp_path)
        assert run.state == "SUCCEEDED"
        res = _result(run)
        assert res["metrics"]["requests_retired"]["value"] == 1
        assert res["provenance"]["network_mode"] == "REAL_SIMULATION"
        assert res["provenance"]["semantic_losses"] == []
        assert res["provenance"]["fidelity"] == "SYSTEM_SERVING_SIMULATION"
        assert res["fabric"]["coll_completes"] >= 1
        assert res["fabric"]["max_retired_flits"] > 0
        assert res["metric_schema"] == 1
        assert res["metrics"]["TTFT"]["unit"] == "ns"
        assert res["metrics"]["sim_clock"]["unit"] == "ns"
        assert res["backend_binaries"][0]["sha256"] is not None
        assert res["cluster_sha256"] is not None
        assert res["dataset_sha256"] is not None
        # Phase 9: canonical workload provenance rides the run result.
        wl = res["workload"]
        assert wl["certified"] is True
        assert wl["identity"].startswith("sha256:")
        assert wl["artifact_count"] >= 1
        idx_path = run.root / "workload" / "index.json"
        assert idx_path.is_file()
        import json as _json
        import hashlib as _hashlib
        idx = _json.loads(idx_path.read_text())
        from veritx_dse.workload.canonical import WorkloadArtifact
        art = WorkloadArtifact.from_dict(_json.loads(
            (run.root / "workload" / idx["artifacts"][0]["file"])
            .read_text()))
        assert art.artifact_hash == idx["artifacts"][0]["artifact_hash"]
        assert art.comm_bytes_total() > 0
        # Phase 9 parity + sufficiency, end-to-end on the REAL run:
        # regenerate the backend ET from the artifact ALONE and compare
        # bytes with what the child actually executed.
        from veritx_dse.workload.lowering import (
            rows_from_artifact, lower_to_et)
        executed = sorted(
            (run.root / "inputs" / "workload").rglob("llm.*.et"))
        assert executed, "run produced no llm.*.et backend inputs"
        exec_sha = {"sha256:" + _hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in executed}
        matched = False
        for e in idx["artifacts"]:
            art_i = WorkloadArtifact.from_dict(_json.loads(
                (run.root / "workload" / e["file"]).read_text()))
            regen = lower_to_et(
                art_i, rows_from_artifact(art_i).rows,
                run.root / "artifacts" / "regen" / e["name"],
                num_npus=2, num_npu_group=1)
            if set(regen.et_sha256s) & exec_sha:
                matched = True
                break
        assert matched, (
            "artifact-alone regeneration does not reproduce any of the "
            f"run's executed backend inputs (executed={exec_sha})")


@needs_serving
@needs_binary
class TestGoldenB:
    """Multi-instance DP/TP under REAL_SIMULATION: ownership + retirement."""

    def test_multi_instance_ownership_golden(self, tmp_path, monkeypatch):
        import csv as _csv
        monkeypatch.setattr("veritx_dse.core.runs.VERITX_RUNS_DIR",
                            tmp_path / "runs")
        d = _spec_dict(cluster="multi_dp_tp", num_reqs=2,
                       request_routing_policy="RR")
        d["simulation"] = {"mode": "serving", "timeout_s": 1200}
        run = run_serving_experiment(d, repo=tmp_path)
        assert run.state == "SUCCEEDED"
        res = _result(run)
        assert res["metrics"]["requests_retired"]["value"] == 2
        csv_path = run.root / "artifacts" / "requests.csv"
        with open(csv_path, newline="") as f:
            seen = {r["instance id"] for r in _csv.DictReader(f)}
        # RR over 2 requests guarantees both instances serve: rebinding
        # bugs (all completions credited to instance 0) fail here.
        assert seen == {"0", "1"}, f"ownership broken: {seen}"
        assert res["fabric"]["coll_completes"] >= 1


@needs_serving
@needs_analytical
class TestGoldenAnalytical:
    """PR7: one tiny golden per analytical frontend.

    Golden-C: single-instance 1-dim cluster → congestion-aware engine.
    Golden-D: multi-instance N-dim cluster → congestion-unaware engine
    (the fallback, now machine-readable). Both prove the serving loop's
    interactive protocol works against each frontend's main.cc and that
    retirement + fabric evidence + engine identity land in the result.
    """

    def test_single_instance_aware_golden(self, tmp_path, monkeypatch):
        monkeypatch.setattr("veritx_dse.core.runs.VERITX_RUNS_DIR",
                            tmp_path / "runs")
        d = _spec_dict(network_backend="analytical")
        d["serving"]["cycle_accurate"] = False
        run = run_serving_experiment(d, repo=tmp_path)
        assert run.state == "SUCCEEDED", \
            _result(run).get("error") if run.state == "FAILED" else run.root
        res = _result(run)
        assert res["metrics"]["requests_retired"]["value"] == 1
        assert res["provenance"]["network_mode"] == "REAL_SIMULATION"
        assert res["provenance"]["fidelity"] == "ANALYTICAL_ESTIMATE"
        assert res["provenance"]["semantic_losses"] == []
        assert res["network_engine"] == "congestion_aware"
        assert res["fabric"]["coll_completes"] >= 1
        assert res["backend_binaries"][0]["sha256"] is not None

    def test_multi_instance_unaware_golden(self, tmp_path, monkeypatch):
        import csv as _csv
        monkeypatch.setattr("veritx_dse.core.runs.VERITX_RUNS_DIR",
                            tmp_path / "runs")
        d = _spec_dict(network_backend="analytical", cluster="multi_dp_tp",
                       num_reqs=2, request_routing_policy="RR")
        d["serving"]["cycle_accurate"] = False
        d["simulation"] = {"mode": "serving", "timeout_s": 1200}
        run = run_serving_experiment(d, repo=tmp_path)
        assert run.state == "SUCCEEDED", \
            _result(run).get("error") if run.state == "FAILED" else run.root
        res = _result(run)
        assert res["metrics"]["requests_retired"]["value"] == 2
        assert res["network_engine"] == "congestion_unaware"
        csv_path = run.root / "artifacts" / "requests.csv"
        with open(csv_path, newline="") as f:
            seen = {r["instance id"] for r in _csv.DictReader(f)}
        # RR over 2 requests: both instances must serve — proves the
        # unaware frontend's bare-path reload reaches every rank.
        assert seen == {"0", "1"}, f"ownership broken: {seen}"
        assert res["fabric"]["coll_completes"] >= 1
        assert res["provenance"]["network_mode"] == "REAL_SIMULATION"

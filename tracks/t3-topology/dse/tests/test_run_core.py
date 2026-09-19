"""PR 2 seam tests: spec -> resolved -> hash -> run dir -> manifest.

These test the redesign's immutable-run invariants at their public seam
(core.spec, core.runs) — observable behavior, not internals:

  * strict boundary: unknown fields rejected, never normalized
  * identity: canonical hash stable, non-scientific fields excluded,
    scientific changes fork the hash
  * lifecycle: only legal transitions, results immutable after terminal
  * provenance: automatic, allowlisted env (no accidental secret dump)
"""
import json
import subprocess
from pathlib import Path

import pytest

from veritx_dse.core.spec import (
    SpecError, parse, resolve, canonical_json, experiment_hash, plan,
)
from veritx_dse.core.runs import Run, RunError, new_run_id


def _spec_dict(**over):
    d = {
        "schema_version": 1,
        "name": "qwen3_decode_n64",
        "workload": {"id": "qwen3_decode_64", "trace": "archive/inputs/traces/chakra_converted.trace"},
        "system": {"nodes": 64, "tp_size": 1, "instances_per_node": 2},
        # Study-integrity P0 #10: routing omitted — the named preset owns
        # its routing (mesh_8x8 → min_adapt). Explicit-native is also
        # legal; anything else is rejected at the boundary.
        "network": {"topology": "mesh_8x8"},
        "simulation": {"mode": "latency", "network_simulator": "booksim", "timeout_s": 60},
        "replication": {"mode": "deterministic", "seeds": [42]},
    }
    d.update(over)
    return d


# ── Level 1: strict boundary ─────────────────────────────────────────────────

class TestStrictBoundary:
    def test_unknown_field_rejected(self):
        bad = _spec_dict(totally_made_up=1)
        with pytest.raises(SpecError, match="totally_made_up"):
            parse(bad)

    def test_nested_unknown_field_rejected(self):
        d = _spec_dict()
        d["system"]["overclock"] = 11
        with pytest.raises(SpecError, match="overclock"):
            parse(d)

    def test_bad_type_rejected_not_coerced(self):
        with pytest.raises(SpecError):
            parse(_spec_dict(system={"nodes": "64"}))  # str -> int coercion forbidden

    def test_unknown_topology_id_accepted_at_boundary(self):
        # The boundary checks *shape*; registered-ID existence is the join
        # point with trusted config (ADR 0005) and is checked at plan time.
        d = _spec_dict()
        d["network"]["topology"] = "not_a_registered_topo"
        parse(d)  # parses; registration check lives in the plan/execute seam


# ── Level 1: resolution + identity ──────────────────────────────────────────

class TestIdentity:
    def test_resolve_is_explicit(self):
        r = resolve(parse(_spec_dict()))
        assert r["system"]["nodes"] == 64
        assert r["replication"]["seeds"] == [42]
        # every default materialized — nothing implicit left
        assert r["simulation"]["timeout_s"] == 60
        # Study-integrity P0 #10: the preset's NATIVE routing is
        # materialized (mesh_8x8 owns min_adapt); None never resolves.
        assert r["network"]["routing"] == "min_adapt"

    def test_preset_routing_omitted_equals_explicit_native(self):
        # The resolver materializes the preset's routing, so an omitted
        # routing and the explicit native value are the SAME scientific
        # intent — one experiment_hash.
        omitted = resolve(parse(_spec_dict()))
        explicit = _spec_dict()
        explicit["network"]["routing"] = "min_adapt"
        native = resolve(parse(explicit))
        assert (experiment_hash(omitted)
                == experiment_hash(native))

    def test_preset_routing_mutation_rejected_before_run(self, tmp_path):
        # mesh_8x8 owns min_adapt; dim_order is a foreign default — the
        # same silent-preset-mutation defect class as the Dragonfly k=8
        # disaster. Rejected at the boundary; nothing is created.
        from veritx_dse.core.experiment import run_experiment

        d = _spec_dict()
        d["network"]["routing"] = "dim_order"
        with pytest.raises(SpecError, match="owns routing"):
            run_experiment(d, repo=tmp_path)
        assert not (tmp_path / "runs").exists()

    def test_torus_omitted_routing_resolves_native(self):
        d = _spec_dict()
        d["network"] = {"topology": "torus_8x8"}
        r = resolve(parse(d))
        assert r["network"]["routing"] == "dim_order"
        explicit = _spec_dict()
        explicit["network"] = {"topology": "torus_8x8",
                               "routing": "dim_order"}
        assert (experiment_hash(r)
                == experiment_hash(resolve(parse(explicit))))

    def test_hash_stable_across_key_order(self):
        d1 = _spec_dict()
        d2 = dict(reversed(list(_spec_dict().items())))
        h1 = experiment_hash(resolve(parse(d1)))
        h2 = experiment_hash(resolve(parse(d2)))
        assert h1 == h2

    def test_notes_do_not_fork_identity(self):
        r1 = resolve(parse(_spec_dict(name="x", notes="v1")))
        r2 = resolve(parse(_spec_dict(name="x", notes="v2 — retitled")))
        assert experiment_hash(r1) == experiment_hash(r2)

    def test_science_change_forks_hash(self):
        # Valid 64-node preset pair — a real network-science change, not a
        # preset mutation (study-integrity P0 #10).
        d1, d2 = _spec_dict(), _spec_dict()
        d2["network"] = {"topology": "torus_8x8"}
        assert experiment_hash(resolve(parse(d1))) != experiment_hash(resolve(parse(d2)))

    def test_seed_change_forks_hash(self):
        d1, d2 = _spec_dict(), _spec_dict()
        d2["replication"]["seeds"] = [43]
        assert experiment_hash(resolve(parse(d1))) != experiment_hash(resolve(parse(d2)))

    def test_stochastic_one_seed_rejected(self):
        d = _spec_dict()
        d["replication"] = {"mode": "stochastic", "seeds": [101]}
        with pytest.raises(SpecError, match="one-seed"):
            resolve(parse(d))

    def test_stochastic_seeds_sorted_deduped(self):
        d = _spec_dict()
        d["replication"] = {"mode": "stochastic", "seeds": [103, 101, 103, 102]}
        r = resolve(parse(d))
        assert r["replication"]["seeds"] == [101, 102, 103]

    def test_plan_shape_and_hash_binding(self):
        r = resolve(parse(_spec_dict()))
        p = plan(r)
        assert p["experiment_hash"] == experiment_hash(r)
        assert [t["task_id"] for t in p["tasks"]] == ["eval-seed42"]

    def test_canonical_json_is_tight_and_sorted(self):
        r = resolve(parse(_spec_dict()))
        c = canonical_json(r)
        assert ": " not in c and ", " not in c
        assert c == json.dumps(r, sort_keys=True, separators=(",", ":"))


# ── Run directory lifecycle (ADR 0001/0003) ─────────────────────────────────

class TestRunLifecycle:
    @pytest.fixture()
    def run(self, tmp_path, monkeypatch):
        monkeypatch.setattr("veritx_dse.core.runs.VERITX_RUNS_DIR", tmp_path / "runs")
        resolved = resolve(parse(_spec_dict()))
        return Run.create(repo=tmp_path, resolved_spec=resolved, argv=["veritx", "test"])

    def test_run_id_sortable_unique(self):
        import time as _t
        ids = {new_run_id() for _ in range(50)}
        assert len(ids) == 50
        # uuid7 embeds the timestamp: an id generated later sorts after one
        # generated earlier (sleep crosses a millisecond boundary).
        _t.sleep(0.003)
        assert new_run_id() > min(ids)

    def test_create_writes_frozen_files(self, run):
        assert (run.root / "spec.resolved.json").is_file()
        assert (run.root / "provenance.json").is_file()
        m = json.loads((run.root / "manifest.json").read_text())
        assert m["run_id"] == run.run_id
        assert m["experiment_hash"] == experiment_hash(
            json.loads((run.root / "spec.resolved.json").read_text()))
        assert m["status"] == "CREATED"
        assert run.state == "CREATED"

    def test_happy_path_transitions(self, run):
        run.transition("VALIDATED")
        run.transition("PLANNED")
        run.transition("RUNNING")
        run.add_result("eval-seed42", {"latency": 35.05})
        run.finalize("SUCCEEDED")
        assert run.state == "SUCCEEDED"
        m = json.loads((run.root / "manifest.json").read_text())
        assert m["results"][0]["latency"] == 35.05

    def test_illegal_transition_refused(self, run):
        with pytest.raises(RunError, match="CREATED -> RUNNING"):
            run.transition("RUNNING")

    def test_success_requires_results(self, run):
        run.transition("VALIDATED")
        run.transition("PLANNED")
        run.transition("RUNNING")
        with pytest.raises(RunError, match="zero recorded results"):
            run.finalize("SUCCEEDED")

    def test_results_frozen_after_terminal(self, run):
        run.transition("VALIDATED")
        run.transition("PLANNED")
        run.transition("RUNNING")
        run.add_result("eval-seed42", {"latency": 35.05})
        run.finalize("SUCCEEDED")
        with pytest.raises(RunError, match="immutable"):
            run.add_result("eval-seed42", {"latency": 1.0})

    def test_spec_frozen_on_disk_matches_hash(self, run):
        # Rewriting spec.resolved.json is the mutation ADR 0001 forbids;
        # here we assert at least that what was frozen is what was hashed.
        frozen = json.loads((run.root / "spec.resolved.json").read_text())
        m = json.loads((run.root / "manifest.json").read_text())
        assert m["experiment_hash"] == experiment_hash(frozen)


# ── Provenance (ADR 0006) ────────────────────────────────────────────────────

class TestProvenance:
    def test_automatic_capture(self, tmp_path, monkeypatch):
        monkeypatch.setattr("veritx_dse.core.runs.VERITX_RUNS_DIR", tmp_path / "runs")
        run = Run.create(repo=tmp_path, resolved_spec=resolve(parse(_spec_dict())),
                         argv=["veritx", "test"])
        prov = json.loads((run.root / "provenance.json").read_text())
        assert prov["argv"] == ["veritx", "test"]
        assert prov["python"]
        assert prov["captured_at"]

    def test_env_allowlist_no_secret_dump(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "leak-me")
        monkeypatch.setenv("PATH", "/usr/bin")
        from veritx_dse.core.runs import capture_provenance
        prov = capture_provenance(tmp_path, argv=[])
        assert "AWS_SECRET_ACCESS_KEY" not in prov["env"]
        assert prov["env"]["PATH"] == "/usr/bin"

    def test_git_identity_tolerates_non_repo(self, tmp_path):
        from veritx_dse.core.runs import _git_identity
        ident = _git_identity(tmp_path)  # tmp_path is not a git repo
        assert ident["commit"] is None and ident["dirty"] is None


class TestStandaloneExperiment:
    @pytest.fixture()
    def experiment(self, tmp_path, monkeypatch):
        monkeypatch.setattr("veritx_dse.core.runs.VERITX_RUNS_DIR", tmp_path / "runs")
        monkeypatch.setattr(
            "veritx_dse.simulation.booksim.find_booksim_bin",
            lambda repo: Path("booksim"),
        )
        trace = tmp_path / "tiny.trace"
        trace.write_text("0 0 0 1 1\n10 1 0 0 1\n")
        return _spec_dict(
            workload={"id": "tiny", "trace": str(trace)},
            system={"nodes": 64},
        )

    @pytest.mark.parametrize("section,field,value", [
        ("simulation", "mode", "serving"),
        ("simulation", "mode", "throughput"),
        ("simulation", "network_simulator", "analytical"),
        ("system", "nodes", 72),
        ("system", "tp_size", 2),
        ("system", "instances_per_node", 2),
        ("network", "routing", "dim_order; seed = 9"),
        ("replication", "mode", "unknown"),
        ("replication", "seeds", []),
        ("replication", "seeds", [42, 43]),
        ("replication", "seeds", [-1]),
    ])
    def test_unsupported_intent_rejected_before_run(self, experiment, tmp_path,
                                                    section, field, value):
        from veritx_dse.core.experiment import run_experiment

        experiment[section][field] = value
        with pytest.raises(SpecError, match=field):
            run_experiment(experiment, repo=tmp_path)
        assert not (tmp_path / "runs").exists()

    def test_trace_node_outside_topology_is_rejected(self, experiment, tmp_path):
        from veritx_dse.core.experiment import run_experiment

        Path(experiment["workload"]["trace"]).write_text("0 0 0 64 1\n")
        run = run_experiment(experiment, repo=tmp_path)
        assert run.state == "CANCELLED"
        manifest = json.loads((run.root / "manifest.json").read_text())
        assert "node" in manifest["results"][0]["error"]

    def test_routing_and_seed_reach_config_and_result(self, experiment, tmp_path):
        from veritx_dse.core.experiment import run_experiment

        # Routing rides the PRESET (mesh_8x8 → min_adapt; study-integrity
        # P0 #10): what reaches the BookSim config is the resolved native
        # routing, never a spec-supplied override.
        experiment["replication"]["seeds"] = [101]
        configs = []

        def runner(cmd, cwd, timeout):
            configs.append(Path(cmd[1]).read_text())
            assert timeout == 60
            return subprocess.CompletedProcess(
                cmd, 0, "Packet latency average = 35.05 (1 samples)\n", "",
            )

        run = run_experiment(experiment, repo=tmp_path, runner=runner)
        assert run.root.parent == tmp_path / "runs"
        assert run.state == "SUCCEEDED"
        assert len(configs) == 1
        assert "routing_function = min_adapt;" in configs[0]
        assert "seed = 101;" in configs[0]
        assert "sim_type = latency;" in configs[0]
        manifest = json.loads((run.root / "manifest.json").read_text())
        result = manifest["results"][0]
        assert result["routing"] == "min_adapt"
        assert result["nodes"] == experiment["system"]["nodes"]
        assert result["seed"] == 101


# ── Phase 7: shared run-lifecycle mechanics (extraction) ────────────────

class TestRunLifecycleHelpers:
    """Plan persistence + rejection-evidence live on Run — the run-
    lifecycle owner — because two real slices repeat them verbatim.
    Behavior contracts unchanged; the slices delegate to these."""

    def test_record_plan_persists_and_transitions(self, tmp_path, monkeypatch):
        monkeypatch.setattr("veritx_dse.core.runs.VERITX_RUNS_DIR",
                            tmp_path / "runs")
        run = Run.create(repo=tmp_path,
                         resolved_spec=resolve(parse(_spec_dict())))
        # VALIDATED is slice-owned (carries slice-specific evidence);
        # record_plan owns plan persistence + PLANNED -> RUNNING.
        run.transition("VALIDATED", note="validation evidence here")
        plan = {"schema_version": 1, "tasks": [{"task_id": "t1"}]}
        run.record_plan(plan)
        on_disk = json.loads((run.root / "plan.json").read_text())
        assert on_disk == plan
        assert run.state == "RUNNING"

    def test_cancel_records_evidence_and_closes(self, tmp_path, monkeypatch):
        monkeypatch.setattr("veritx_dse.core.runs.VERITX_RUNS_DIR",
                            tmp_path / "runs")
        run = Run.create(repo=tmp_path,
                         resolved_spec=resolve(parse(_spec_dict())))
        run.cancel("trace invalid: garbage")
        assert run.state == "CANCELLED"
        manifest = json.loads((run.root / "manifest.json").read_text())
        assert "trace invalid: garbage" in manifest["results"][0]["error"]

"""Wave-E product integration tests — SrotaControlPlane only (§68/§70).

No second control plane, no parallel executor: the temporal workload is
declared on the intent, bound into the plan, executed through the
sealed Wave-B/D path, and verified on load exactly like every other
result block. The network window is bound to REAL certified BookSim
evidence; no timing number is transcribed by hand.
"""
from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_wave_d_seal import (  # noqa: E402
    METRICS, _collective, _p2p,
)

from veritx_dse.application.requests import resolve_intent  # noqa: E402
from veritx_dse.application.results import load_verified_result  # noqa: E402
from veritx_dse.application.wave_e_resources import (  # noqa: E402
    load_verified_wave_e_workload,
)
from veritx_dse.wavee.model import (  # noqa: E402
    ClockDef, ResourceDef, WaveEPerformanceModel,
)
from veritx_dse.wavee.scheduler import schedule_workload  # noqa: E402
from veritx_dse.wavee.time import QTime  # noqa: E402
from veritx_dse.wavee.workload import (  # noqa: E402
    EVENT_NETWORK_OPERATION_REF, WaveETemporalEvent,
    WaveETemporalWorkload,
)

REPO = DSE.parents[2]


def _wave_e_workload(compute_ms: int = 1, *, clock_hz: int = 10 ** 9
                     ) -> WaveETemporalWorkload:
    """One network window + an explicit compute tail on gpu.compute.

    The NETWORK_OPERATION_REF cites the Wave-D collective operation
    id (provenance is constructor-validated); its duration comes only
    from the evidence seam at evaluation time.
    """
    model = WaveEPerformanceModel(
        clocks=(ClockDef("net", clock_hz),),
        resources=(ResourceDef("gpu.compute", "EXCLUSIVE", capacity=1),),
        network_clock="net")
    return WaveETemporalWorkload(
        performance_model=model,
        events=(
            WaveETemporalEvent(
                "NET", EVENT_NETWORK_OPERATION_REF, QTime(0),
                wave_d_operation_id="c0", phase="DECODE", rank=0),
            WaveETemporalEvent(
                "TAIL", "COMPUTE", QTime(compute_ms, 1000), "gpu.compute",
                deps=("NET",), phase="DECODE", rank=0),
        ),
        wave_d_operation_ids=("c0",))


def _intent(*, name="wave-e-e2e", wave_e=None, seed=7, preset="mesh4",
            tp=1, pp=1, ep=1, dp=4, phase="DECODE"):
    doc = {
        "schema_version": 1, "name": name, "fabric_preset": preset,
        "fabric_overrides": {"workload.tp": tp, "workload.pp": pp,
                             "workload.ep": ep, "workload.dp": dp},
        "workload": {"wave_d": {
            "parallelism": {"tp": tp, "pp": pp, "ep": ep, "dp": dp},
            "semantics": {"phase": phase},
            "operations": [
                {**_collective(participants=tuple(range(dp))),
                 "phase": phase},
                {**_p2p(dst=min(2, dp - 1), deps=("c0",)),
                 "phase": phase},
            ],
        }},
        "backend_target": "BOOKSIM_STANDALONE", "seed": seed,
        "metrics": list(METRICS), "timeout_s": 120,
    }
    if wave_e is not None:
        doc["workload"]["wave_e"] = wave_e.to_dict()
    return doc


@pytest.fixture()
def cp(tmp_path):
    from veritx_dse.application.service import SrotaControlPlane
    return SrotaControlPlane(store_root=tmp_path / "store",
                             repo_root=REPO)


class TestIntentAndPlan:
    def test_wave_e_requires_wave_d(self):
        """A temporal overlay without Wave-D semantics refuses (§8)."""
        doc = _intent()
        doc["workload"]["wave_e"] = _wave_e_workload().to_dict()
        doc["workload"].pop("wave_d")
        with pytest.raises(Exception, match="requires.*wave_d|wave_d"):
            resolve_intent(doc)

    def test_wave_e_enters_intent_identity(self, cp):
        """Same Wave-D workload + different timing model = different
        intent/plan identity (§69: timing models never share a plan)."""
        intent_a, _, _ = resolve_intent(_intent(wave_e=_wave_e_workload(1)))
        intent_b, _, _ = resolve_intent(_intent(wave_e=_wave_e_workload(2)))
        assert intent_a.intent_id() != intent_b.intent_id()

    def test_plan_binds_wave_e_parents(self, cp):
        planned = cp.plan(_intent(wave_e=_wave_e_workload()))
        plan = planned["plan"]
        we = _wave_e_workload()
        assert plan["wave_e"]["temporal_workload_id"] \
            == we.temporal_workload_id()
        assert plan["wave_e"]["performance_model_id"] \
            == we.performance_model.performance_model_id()
        # a Wave-D-only plan has no wave_e block (schema-omitted,
        # same as wave_d on a legacy plan)
        planned_d = cp.plan(_intent(name="d-only"))
        assert planned_d["plan"].get("wave_e") is None


class TestProductEvaluation:
    def test_evaluate_with_wave_e_derives_verified_block(self, cp):
        """Full §70 chain over REAL BookSim execution."""
        we = _wave_e_workload()
        result = cp.evaluate(_intent(wave_e=we))
        assert result["status"] == "SUCCEEDED"
        block = result["wave_e"]
        assert block is not None
        assert block["temporal_workload_id"] == we.temporal_workload_id()
        assert block["performance_model_id"] \
            == we.performance_model.performance_model_id()
        # Wave-D provenance rides along (§71)
        assert block["wave_d_chain"]["physical_traffic_id"] \
            == result["wave_d"]["physical_traffic_id"]
        # network window bound to real evidence with a real clock
        binding = block["network_binding"]
        assert binding["evidence_sha256"]
        assert binding["network_clock_hz"] == {"num": 10 ** 9, "den": 1}
        window = binding["duration"]
        assert window["numerator"] > 0
        # makespan = window + 1 ms compute tail, in exact rationals
        makespan = block["makespan"]
        expected = Fraction(window["numerator"], window["denominator"]) \
            + Fraction(1, 1000)
        assert Fraction(makespan["numerator"], makespan["denominator"]) \
            == expected
        assert "UNCALIBRATED" in block["metrics_warning"]
        # verified load re-derives everything (§74)
        loaded = load_verified_result(cp.store, result["resource_id"])
        assert loaded["wave_e"]["makespan"] == block["makespan"]

    def test_reuse_keeps_wave_e_block(self, cp):
        """Reuse replays the SAME verified timing block, not a new one."""
        we = _wave_e_workload()
        first = cp.evaluate(_intent(name="we-reuse-a", wave_e=we))
        second = cp.evaluate(_intent(name="we-reuse-b", wave_e=we))
        assert second["reused"] is True
        assert second["wave_e"]["makespan"] == first["wave_e"]["makespan"]
        assert second["wave_e"]["network_binding"]["evidence_sha256"] \
            == first["wave_e"]["network_binding"]["evidence_sha256"]

    def test_different_timing_model_no_shared_reuse(self, cp):
        """1 ms and 2 ms compute tails are DIFFERENT experiments (§57)."""
        first = cp.evaluate(_intent(name="we-model-a",
                                    wave_e=_wave_e_workload(1)))
        second = cp.evaluate(_intent(name="we-model-b",
                                     wave_e=_wave_e_workload(2)))
        assert second["reused"] is False
        assert Fraction(second["wave_e"]["makespan"]["numerator"],
                        second["wave_e"]["makespan"]["denominator"]) \
            == Fraction(first["wave_e"]["makespan"]["numerator"],
                        first["wave_e"]["makespan"]["denominator"]) \
            + Fraction(1, 1000)

    def test_wave_e_result_survives_persistence(self, cp, tmp_path):
        """Store roundtrip: workload + persisted binding re-derive it."""
        from veritx_dse.wavee.network import NetworkWindowBinding
        from veritx_dse.wavee.result import WaveEEventGraph
        we = _wave_e_workload()
        result = cp.evaluate(_intent(name="we-persist", wave_e=we))
        wid = result["wave_e"]["temporal_workload_id"]
        loaded = load_verified_wave_e_workload(cp.store, wid)
        assert loaded.temporal_workload_id() == wid
        # the network duration comes ONLY from the persisted evidence
        # binding; re-running the schedule over both must reproduce it
        binding = NetworkWindowBinding.from_dict(
            result["wave_e"]["network_binding"])
        graph = WaveEEventGraph(
            workload=loaded, network_binding=binding,
            wave_d_chain=result["wave_e"]["wave_d_chain"])
        s = schedule_workload(
            loaded, network_durations=graph.network_durations())
        assert s.makespan().q == Fraction(
            result["wave_e"]["makespan"]["numerator"],
            result["wave_e"]["makespan"]["denominator"])


class TestWaveETamperMatrix:
    """§80–§84: valid-object transplants, not just corrupt hashes."""

    def test_workload_id_transplant_detected(self, cp, tmp_path):
        """Pointing a result at ANOTHER waveeworkload resource refuses."""
        result = cp.evaluate(_intent(name="we-tamper",
                                     wave_e=_wave_e_workload(1)))
        other = _wave_e_workload(2)
        from veritx_dse.core.spec import canonical_json
        from veritx_dse.application.wave_e_resources import (
            wave_e_workload_record,
        )
        cp.store.put("waveeworkload", other.temporal_workload_id(),
                     wave_e_workload_record(other))
        # tamper the persisted result to cite the OTHER workload
        rpath = cp.store.root / "result" / f"{result['resource_id']}.json"
        doc = __import__("json").loads(rpath.read_text())
        doc["wave_e"]["temporal_workload_id"] = other.temporal_workload_id()
        rpath.write_text(canonical_json(doc))
        with pytest.raises(Exception):
            load_verified_result(cp.store, result["resource_id"])

    def test_missing_evidence_sha_in_binding_refuses(self, cp):
        result = cp.evaluate(_intent(name="we-nobind",
                                     wave_e=_wave_e_workload()))
        from veritx_dse.core.spec import canonical_json
        rpath = cp.store.root / "result" / f"{result['resource_id']}.json"
        doc = __import__("json").loads(rpath.read_text())
        doc["wave_e"]["network_binding"]["evidence_sha256"] = ""
        rpath.write_text(canonical_json(doc))
        with pytest.raises(Exception, match="evidence_sha256|§42"):
            load_verified_result(cp.store, result["resource_id"])

    def test_unknown_wave_e_field_refuses(self, cp):
        result = cp.evaluate(_intent(name="we-field",
                                     wave_e=_wave_e_workload()))
        from veritx_dse.core.spec import canonical_json
        rpath = cp.store.root / "result" / f"{result['resource_id']}.json"
        doc = __import__("json").loads(rpath.read_text())
        doc["wave_e"]["invented_latency_gains"] = "47%"
        rpath.write_text(canonical_json(doc))
        with pytest.raises(Exception, match="field set|unknown"):
            load_verified_result(cp.store, result["resource_id"])


class TestWaveEProvenanceBinding:
    """§73/§74/§75/§131: the persisted block is re-derived, not trusted.

    Every attack here feeds a VALID or plausible object into the real
    product verifier. The class exists because the first version of this
    verifier proved "the block is internally coherent", which is a
    different question from "this block is THIS experiment's timing".
    """

    @staticmethod
    def _tamper(cp, result_id, mutate):
        from veritx_dse.core.spec import canonical_json
        path = cp.store.root / "result" / f"{result_id}.json"
        doc = json.loads(path.read_text())
        mutate(doc)
        path.write_text(canonical_json(doc))

    def _refuses(self, cp, result_id, match=None):
        with pytest.raises(Exception) as exc:
            load_verified_result(cp.store, result_id)
        if match is not None:
            assert match in str(exc.value), str(exc.value)
        return exc.value

    def test_makespan_summary_is_rederived(self, cp):
        """A copied makespan that disagrees with the schedule refuses."""
        result = cp.evaluate(_intent(name="we-prov-makespan",
                                     wave_e=_wave_e_workload()))
        self._tamper(cp, result["resource_id"],
                     lambda d: d["wave_e"].__setitem__(
                         "makespan", {"numerator": 999, "denominator": 1}))
        self._refuses(cp, result["resource_id"], "makespan")

    def test_network_window_is_bound_to_the_binding(self, cp):
        result = cp.evaluate(_intent(name="we-prov-window",
                                     wave_e=_wave_e_workload()))
        self._tamper(cp, result["resource_id"],
                     lambda d: d["wave_e"].__setitem__(
                         "network_window", {"numerator": 1,
                                            "denominator": 7}))
        self._refuses(cp, result["resource_id"], "network_window")

    def test_forged_fidelity_warning_refuses(self, cp):
        """A forged accuracy claim cannot ride along (§64)."""
        result = cp.evaluate(_intent(name="we-prov-warning",
                                     wave_e=_wave_e_workload()))
        self._tamper(cp, result["resource_id"],
                     lambda d: d["wave_e"].__setitem__(
                         "metrics_warning",
                         "VALIDATED against NVIDIA H100"))
        self._refuses(cp, result["resource_id"], "metrics_warning")

    def test_valid_wave_d_chain_transplant_refuses(self, cp):
        """A DIFFERENT fully valid chain in the timing block refuses."""
        # Same traffic shape, different PHASE: the two chains are both
        # valid and render byte-identical BookSim traffic, so only the
        # provenance binding can tell them apart.
        a = cp.evaluate(_intent(name="we-prov-a", wave_e=_wave_e_workload(1),
                                phase="DECODE"))
        b = cp.evaluate(_intent(name="we-prov-b", wave_e=_wave_e_workload(2),
                                phase="PREFILL"))
        other = json.loads(json.dumps(b["wave_e"]["wave_d_chain"]))
        assert other != a["wave_e"]["wave_d_chain"]
        self._tamper(cp, a["resource_id"],
                     lambda d: d["wave_e"].__setitem__("wave_d_chain", other))
        self._refuses(cp, a["resource_id"], "wave_d_chain")

    def test_valid_network_binding_transplant_refuses(self, cp):
        """Another run's valid binding is not this run's timing (§42)."""
        a = cp.evaluate(_intent(name="we-prov-c", wave_e=_wave_e_workload(1)))
        b = cp.evaluate(_intent(name="we-prov-d", wave_e=_wave_e_workload(2)))
        other = json.loads(json.dumps(b["wave_e"]["network_binding"]))
        self._tamper(cp, a["resource_id"],
                     lambda d: d["wave_e"].__setitem__(
                         "network_binding", other))
        self._refuses(cp, a["resource_id"], "evidence_sha256")

    def test_evidence_digest_tamper_refuses(self, cp):
        result = cp.evaluate(_intent(name="we-prov-e",
                                     wave_e=_wave_e_workload()))
        def mutate(d):
            b = dict(d["wave_e"]["network_binding"])
            b["evidence_sha256"] = "f" * 64
            d["wave_e"]["network_binding"] = b
        self._tamper(cp, result["resource_id"], mutate)
        self._refuses(cp, result["resource_id"], "evidence_sha256")

    def test_stats_digest_tamper_refuses(self, cp):
        result = cp.evaluate(_intent(name="we-prov-f",
                                     wave_e=_wave_e_workload()))
        def mutate(d):
            b = dict(d["wave_e"]["network_binding"])
            b["stats_sha256"] = "e" * 64
            d["wave_e"]["network_binding"] = b
        self._tamper(cp, result["resource_id"], mutate)
        self._refuses(cp, result["resource_id"], "stats_sha256")

    def test_network_clock_tamper_refuses(self, cp):
        result = cp.evaluate(_intent(name="we-prov-g",
                                     wave_e=_wave_e_workload()))
        def mutate(d):
            b = dict(d["wave_e"]["network_binding"])
            b["network_clock_hz"] = {"num": 2 * 10 ** 9, "den": 1}
            d["wave_e"]["network_binding"] = b
        self._tamper(cp, result["resource_id"], mutate)
        self._refuses(cp, result["resource_id"], "network_clock_hz")

    def test_backend_input_hash_transplant_refuses(self, cp):
        result = cp.evaluate(_intent(name="we-prov-h",
                                     wave_e=_wave_e_workload()))
        def mutate(d):
            b = dict(d["wave_e"]["network_binding"])
            b["backend_input_hash"] = "d" * 64
            d["wave_e"]["network_binding"] = b
        self._tamper(cp, result["resource_id"], mutate)
        self._refuses(cp, result["resource_id"], "backend_input_hash")

    def test_orphaned_wave_e_block_refuses(self, cp):
        """Timing without communication provenance refuses (§71)."""
        result = cp.evaluate(_intent(name="we-prov-i",
                                     wave_e=_wave_e_workload()))
        self._tamper(cp, result["resource_id"],
                     lambda d: d["wave_e"].__setitem__("wave_d_chain", None))
        self._refuses(cp, result["resource_id"], "wave_d_chain")

    def test_plan_citing_unknown_temporal_workload_refuses(self, cp):
        """A plan binding a non-existent overlay is not a valid plan."""
        from veritx_dse.application.resources import _content_id
        from veritx_dse.application.results import load_verified_plan
        planned = cp.plan(_intent(name="we-prov-plan",
                                  wave_e=_wave_e_workload()))
        plan = cp.store.get("plan", planned["plan"]["resource_id"])
        forged = dict(plan)
        forged["wave_e"] = {**plan["wave_e"],
                            "temporal_workload_id": "sha256:" + "0" * 64}
        body = {k: forged[k] for k in (
            "design_hash", "mapping_hash", "fabric_hash", "workload_hash",
            "backend_target", "backend_profile", "backend_semantics_version",
            "lowerer_version", "execution_mode", "seed", "seed_policy",
            "metric_ids", "metric_schema_version", "wave_d", "wave_e")}
        forged["resource_id"] = _content_id("srota-plan/v1", body)
        cp.store.put("plan", forged["resource_id"], forged)
        with pytest.raises(Exception, match="waveeworkload|missing"):
            load_verified_plan(cp.store, forged["resource_id"])

    def test_overlay_citing_foreign_operation_refuses(self, cp):
        """An overlay may only schedule communication this workload does."""
        from veritx_dse.wavee.workload import (
            EVENT_NETWORK_OPERATION_REF, WaveETemporalEvent,
            WaveETemporalWorkload,
        )
        we = _wave_e_workload()
        foreign = WaveETemporalWorkload(
            performance_model=we.performance_model,
            events=(WaveETemporalEvent(
                "NET", EVENT_NETWORK_OPERATION_REF, QTime(0),
                wave_d_operation_id="not-an-op", phase="DECODE", rank=0),),
            wave_d_operation_ids=("not-an-op",))
        with pytest.raises(Exception, match="not in the compiled"):
            cp.compile(_intent(name="we-prov-foreign", wave_e=foreign))


class TestWaveENavigation:
    """Every persisted Wave-E resource must be inspectable and linked."""

    def test_overlay_is_inspectable_and_linked(self, cp):
        r = cp.evaluate(_intent(name="nav-overlay",
                                wave_e=_wave_e_workload(1)))
        wid = r["wave_e"]["temporal_workload_id"]
        view = cp.inspect(wid)
        assert view["kind"] == "waveeworkload"
        assert view["integrity"]["state"] == "VERIFIED"
        assert r["resource_id"] in view["related"]["results"]

    def test_result_surfaces_its_chain_and_overlay(self, cp):
        r = cp.evaluate(_intent(name="nav-result",
                                wave_e=_wave_e_workload(1)))
        related = cp.inspect(r["resource_id"])["related"]
        assert "wave_e.temporal_workload_id" in related
        for key in ("waved_workload_id", "operation_graph_id",
                    "message_artifact_id", "physical_traffic_id"):
            assert f"wave_d.{key}" in related

    def test_tampered_overlay_is_invalid_in_inspect(self, cp):
        import json as _json
        from veritx_dse.core.spec import canonical_json
        r = cp.evaluate(_intent(name="nav-tamper",
                                wave_e=_wave_e_workload(1)))
        wid = r["wave_e"]["temporal_workload_id"]
        path = cp.store.root / "waveeworkload" / f"{wid}.json"
        doc = _json.loads(path.read_text())
        doc["artifact"]["events"][1]["duration"] = {"numerator": 9,
                                                    "denominator": 1000}
        path.write_text(canonical_json(doc))
        view = cp.inspect(wid)
        assert view["integrity"]["state"] == "INVALID"


class TestWaveEComparisonCompatibility:
    """§119/§120: two latency numbers are not automatically comparable.

    The subject is the timing-model compatibility dimension, not the
    sealed clean-tree producer policy (which comparison also enforces);
    ``_clean`` neutralises that policy so the dimension is actually
    reached, exactly as a committed tree would.
    """

    METRICS = ["sim.latency.avg_cycles"]

    @pytest.fixture(autouse=True)
    def _clean(self, monkeypatch):
        monkeypatch.setattr(
            "veritx_dse.application.service."
            "SrotaControlPlane._verify_comparison_evidence",
            lambda self, result: None)

    def _contract(self, allowed=()):
        return {"comparison_kind": "EXACT_REPLAY",
                "metric_ids": self.METRICS,
                "allowed_variations": list(allowed)}

    def test_different_timing_models_refuse_comparison(self, cp):
        """A different CLOCK is a different performance model (§119)."""
        from veritx_dse.application.errors import ControlPlaneError
        a = cp.evaluate(_intent(name="cmp-a", wave_e=_wave_e_workload(1)))
        b = cp.evaluate(_intent(name="cmp-b", wave_e=_wave_e_workload(
            1, clock_hz=2 * 10 ** 9)))
        with pytest.raises(ControlPlaneError) as exc:
            cp.compare({"candidate_ids": [a["resource_id"],
                                          b["resource_id"]],
                        "contract": self._contract()})
        assert "timing_model" in exc.value.message

    def test_same_model_different_durations_compares(self, cp):
        """Durations are WORKLOAD semantics: comparing them is the point."""
        a = cp.evaluate(_intent(name="cmp-c", wave_e=_wave_e_workload(1)))
        b = cp.evaluate(_intent(name="cmp-d", wave_e=_wave_e_workload(2)))
        out = cp.compare({"candidate_ids": [a["resource_id"],
                                            b["resource_id"]],
                          "contract": self._contract()})
        assert out["metrics"]
        varied = [d for d in out["compatibility"]["dimensions"]
                  if d["outcome"] == "varied-allowed"]
        assert not any(d["dimension"] == "timing_model" for d in varied)

    def test_timing_variation_requires_explicit_contract(self, cp):
        """The escape hatch exists, but only when DECLARED (§119)."""
        a = cp.evaluate(_intent(name="cmp-e", wave_e=_wave_e_workload(1)))
        b = cp.evaluate(_intent(name="cmp-f", wave_e=_wave_e_workload(
            1, clock_hz=2 * 10 ** 9)))
        out = cp.compare({"candidate_ids": [a["resource_id"],
                                            b["resource_id"]],
                          "contract": self._contract(
                              allowed=("timing_model",))})
        assert out["compatibility"]["dimensions"]
        varied = [d for d in out["compatibility"]["dimensions"]
                  if d["outcome"] == "varied-allowed"]
        assert any(d["dimension"] == "timing_model" for d in varied)

    def test_wave_e_result_vs_untimed_result_refuses(self, cp):
        """A timed result and an untimed one measure different things."""
        from veritx_dse.application.errors import ControlPlaneError
        timed = cp.evaluate(_intent(name="cmp-g", wave_e=_wave_e_workload(1)))
        plain = cp.evaluate(_intent(name="cmp-h"))
        with pytest.raises(ControlPlaneError) as exc:
            cp.compare({"candidate_ids": [timed["resource_id"],
                                          plain["resource_id"]],
                        "contract": self._contract()})
        assert "timing_model" in exc.value.message

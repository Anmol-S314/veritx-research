"""Cache wiring tests: hit skips execution, transplants re-execute.

Doubles only — no backend spawn. The adapter prepare seam, producer
introspection, binary discovery and the verified reader are stubbed at
their origin modules; FabricEvaluator.evaluate is counted.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application import federated_evaluator as fe  # noqa: E402
from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.backend.adapter import BackendReadiness  # noqa: E402
from veritx_dse.backend.evidence import BackendEvidenceError  # noqa: E402

MESH_PROFILE = "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1"


def _digests(marker: str) -> dict[str, str]:
    h = lambda s: hashlib.sha256(f"{marker}:{s}".encode()).hexdigest()
    return {
        "prepared_id": h("prepared"),
        "config": h("config"),
        "trace": h("trace"),
        "message": h("message"),
        "traffic": h("traffic"),
    }


@pytest.fixture()
def lane(tmp_path, monkeypatch):
    """A fully scripted network leg. Returns (ctx_factory, calls)."""
    calls = {"evaluate": 0, "reads": 0}
    state = {"tamper": False, "refuse_prepare": False,
             "refuse_eval": False, "marker": "base"}

    import veritx_dse.backend.booksim_adapter as ba
    import veritx_dse.backend.booksim_projection as bp
    import veritx_dse.backend.evidence as ev
    import veritx_dse.backend.producer as prod
    import veritx_dse.simulation.booksim as bsim

    semver = bp.MESH_DOR_PROFILE.semantics_version

    class StubPrepared:
        def __init__(self, native):
            self.native_prepared = native

    def fake_prepare(*args, **kwargs):
        if state["refuse_prepare"]:
            raise ba.BookSimProjectionRefusal("nope")
        d = _digests(state["marker"])
        native = SimpleNamespace(
            prepared=SimpleNamespace(
                prepared_id=lambda: d["prepared_id"],
                identity_dict=lambda: {
                    "trace_sha256": d["trace"],
                    "topology_sha256": d["config"],
                },
            ),
            profile_id=bp.MESH_DOR_PROFILE.profile_id,
            config_hash=d["config"],
            input_hash=d["config"],
            physical_traffic_id=d["traffic"],
            message_artifact_id=d["message"],
            realization_digest=d["config"],
        )
        return StubPrepared(native)

    monkeypatch.setattr(ba.BookSimAdapter, "prepare", fake_prepare)
    monkeypatch.setattr(
        bsim, "find_booksim_bin",
        lambda repo_root: Path(state["binary"]))
    monkeypatch.setattr(
        prod, "resolve_producer_identity",
        lambda bin_path, **kw: SimpleNamespace(
            binary_sha256=hashlib.sha256(
                Path(bin_path).read_bytes()).hexdigest(),
            binary_size=Path(bin_path).stat().st_size,
            source_revision="rev-1",
            dirty=False,
            build_manifest_sha256="m" * 64,
            build_recipe_version="booksim2-fork/v2"))

    ev_file = tmp_path / "backend-evidence.json"
    ev_file.write_bytes(b'{"evidence": "run1"}')
    ev_digest = hashlib.sha256(b'{"evidence": "run1"}').hexdigest()

    def fake_reader(ref, **conds):
        calls["reads"] += 1
        if state["tamper"]:
            raise BackendEvidenceError("tampered")
        assert conds["prepared_id"] == _digests(state["marker"])["prepared_id"]
        return SimpleNamespace(
            evidence_id="ev-" + state["marker"],
            route_observation="EXECUTED_ROUTE_OBSERVED",
            route_dump_sha256="r" * 64)

    monkeypatch.setattr(ev, "read_reusable_record", fake_reader)
    from veritx_dse.backend.evidence_cache import EvidenceCache
    monkeypatch.setattr(
        fe, "_EVIDENCE_REUSE_CACHE", EvidenceCache(_read=fake_reader),
        raising=False)

    def fake_normalize(context, outcome):
        return SimpleNamespace(
            model_fidelity="net-fidelity",
            qualification="QUALIFIED",
            native_evidence_id="ev-" + state["marker"])

    monkeypatch.setattr(ba, "normalize_booksim_outcome", fake_normalize)

    from veritx_dse.application.fabric_evaluator import (
        EvaluationOutcome as RealOutcome,
    )

    def fake_evaluate(_self, compilation, workload, options):
        calls["evaluate"] += 1
        if state["refuse_eval"]:
            return RealOutcome(
                status="UNSUPPORTED", reason="nope",
                design_hash="d", resolved_fabric_hash="f",
                workload_id="w")
        return RealOutcome(
            status="EVALUATED", design_hash="d",
            resolved_fabric_hash="f", workload_id="w",
            backend_profile=MESH_PROFILE,
            producer_identity="prod-1",
            backend_config_hash="c" * 64,
            backend_input_hash="i" * 64,
            evidence_id="ev-" + state["marker"],
            raw_evidence_digest=ev_digest,
            stats_digest="s" * 64,
            performance_result_id="pr-1",
            performance_result={"x": 1},
            metrics={"completion_cycles": 100},
            evidence_path=str(ev_file),
            realization_digest="r" * 64,
            message_artifact_id="m", physical_traffic_id="t",
            backend="BOOKSIM_STANDALONE")

    monkeypatch.setattr(fe.FabricEvaluator, "evaluate", fake_evaluate)

    real_sem = bp.MESH_DOR_PROFILE.semantics_version
    assert semver == real_sem

    def make_ctx(marker="base"):
        state["marker"] = marker
        bundle = SimpleNamespace(
            resolved_fabric=SimpleNamespace(resolved_fabric_hash="f" * 64),
            topology=SimpleNamespace(topology_hash=lambda: "t" * 64))
        return SimpleNamespace(
            design_hash="d" * 64, workload_id="w-" + marker,
            unified_traffic_class="DEFAULT", bundle=bundle,
            workload=SimpleNamespace())

    from veritx_dse.application.federated_evaluator import (
        BookSimRunOptions,
    )
    binary = tmp_path / "booksim.bin"
    binary.write_bytes(b"fake-binary-1")
    state["binary"] = str(binary)

    def options(**over):
        kw = {"seed": 0, "network_clock_hz": 1_000_000_000,
              "binary": str(binary), "repo_root": str(tmp_path)}
        kw.update(over)
        return BookSimRunOptions(**kw)

    row = SimpleNamespace(
        question=EvaluationQuestion.NETWORK_COMPLETION,
        backend_id="BOOKSIM_STANDALONE",
        readiness=BackendReadiness.READY, reason=None)

    fe.reset_network_reuse()
    fe._OUTCOME_REUSE.clear()
    return SimpleNamespace(
        make_ctx=make_ctx, options=options, row=row, calls=calls,
        state=state, tmp=tmp_path, binary=binary)


def _run(fe, lane, marker="base", **optover):
    ctx = lane.make_ctx(marker)
    d = lane.tmp / f"run-{marker}-{len(list(lane.tmp.glob('run-*')))}"
    d.mkdir(exist_ok=True)
    return fe._evaluate_network(
        SimpleNamespace(), ctx, lane.row,
        lane.options(**optover), d)


def test_identical_rerun_hits_without_reexecution(lane):
    evaluated, analysis = _run(fe, lane)
    assert evaluated is not None and lane.calls["evaluate"] == 1
    assert analysis.reused_evidence_id is None
    evaluated2, analysis2 = _run(fe, lane)
    assert lane.calls["evaluate"] == 1
    assert analysis2.reused_evidence_id == "ev-base"
    assert analysis2.reuse_matching["question"] == "NETWORK_COMPLETION"
    assert analysis2.reuse_matching["network_clock_hz"] == 1_000_000_000
    assert len(analysis2.reuse_matching) == len(fe._REUSE_PRE_FIELDS)
    assert evaluated2.metrics == {"completion_cycles": 100}


def test_producer_swap_reexecutes(lane):
    _run(fe, lane)
    other = lane.tmp / "other.bin"
    other.write_bytes(b"fake-binary-2")
    _, analysis2 = _run(fe, lane, binary=str(other))
    assert lane.calls["evaluate"] == 2
    assert analysis2.reused_evidence_id is None


def test_clock_swap_reexecutes(lane):
    _run(fe, lane)
    _, analysis2 = _run(fe, lane, network_clock_hz=2_000_000_000)
    assert lane.calls["evaluate"] == 2
    assert analysis2.reused_evidence_id is None


def test_workload_swap_reexecutes(lane):
    _run(fe, lane)
    _, analysis2 = _run(fe, lane, marker="other-workload")
    assert lane.calls["evaluate"] == 2
    assert analysis2.reused_evidence_id is None


def test_tampered_bytes_reexecute(lane):
    _run(fe, lane)
    lane.state["tamper"] = True
    _, analysis2 = _run(fe, lane)
    assert lane.calls["evaluate"] == 2
    assert analysis2.reused_evidence_id is None


def test_prepare_refusal_never_caches(lane):
    lane.state["refuse_prepare"] = True
    lane.state["refuse_eval"] = True
    evaluated, analysis = _run(fe, lane)
    assert evaluated is None and analysis.status == "UNSUPPORTED"
    assert lane.calls["evaluate"] == 1

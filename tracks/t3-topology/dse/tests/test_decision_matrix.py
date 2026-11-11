"""Pure-logic tests for the decision-accuracy matrix harness.

No simulator is invoked.  The evaluator in every test is a dict lookup or a
deliberately broken callable.
"""
from __future__ import annotations

import json

import pytest

from veritx_dse.analysis.decision_matrix import (
    DecisionMatrixError,
    MatrixCase,
    MatrixResult,
    from_dict,
    main,
    rankings,
    run_matrix,
    stability,
    to_dict,
)
from veritx_dse.core.errors import SemanticError


def make_case(case_id: str, topology: str, *, trace: str = "t1",
              config: str = "c1", metadata: dict | None = None) -> MatrixCase:
    return MatrixCase(
        case_id=case_id,
        topology=topology,
        trace=trace,
        config=config,
        metadata={} if metadata is None else metadata,
    )


def make_result(case_id: str, topology: str, *, trace: str = "t1",
                config: str = "c1", cycles: float | None = None,
                status: str = "EVALUATED", reason: str | None = None,
                metadata: dict | None = None) -> MatrixResult:
    return MatrixResult(
        case_id=case_id,
        topology=topology,
        trace=trace,
        config=config,
        status=status,
        completion_cycles=cycles,
        reason=reason,
        metadata={} if metadata is None else metadata,
    )


def evaluated_payload(cycles: float) -> dict:
    return {"status": "EVALUATED", "completion_cycles": cycles}


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def test_evaluated_results_rank_with_top_tie_sorted_by_topology():
    cases = [
        make_case("a", "mesh"),
        make_case("b", "torus"),
        make_case("c", "ring"),
    ]
    payloads = {
        "a": evaluated_payload(100),
        "b": evaluated_payload(120),
        "c": evaluated_payload(100),
    }

    results = run_matrix(cases, lambda case: payloads[case.case_id])
    rows = rankings(results)

    assert len(rows) == 1
    row = rows[0]
    assert (row.trace, row.config) == ("t1", "c1")
    assert row.order == ("mesh", "ring", "torus")
    assert row.winner is None
    assert row.tie is True
    assert row.missing == ()
    assert row.reason == "tie at rank 1: mesh, ring"


def test_unique_winner_and_missing_are_reported_not_ranked():
    cases = [
        make_case("a", "mesh"),
        make_case("b", "torus"),
        make_case("c", "dragonfly"),
        make_case("d", "fat_tree"),
    ]

    def evaluator(case):
        if case.case_id == "a":
            return evaluated_payload(100)
        if case.case_id == "b":
            return evaluated_payload(120)
        if case.case_id == "c":
            return {"status": "UNSUPPORTED", "reason": "no dragonfly model"}
        return {"status": "FAILED", "reason": "simulator exploded"}

    row = rankings(run_matrix(cases, evaluator))[0]

    assert row.order == ("mesh", "torus")
    assert row.winner == "mesh"
    assert row.tie is False
    assert row.missing == ("dragonfly", "fat_tree")
    assert row.reason == (
        "missing: dragonfly (UNSUPPORTED: no dragonfly model); "
        "fat_tree (FAILED: simulator exploded)")
    assert "dragonfly" not in row.order
    assert "fat_tree" not in row.order


def test_tolerance_turns_a_sub_resolution_gap_into_a_tie():
    """A 10-cycle gap on an 8,000-cycle run is not a decisive winner."""
    results = [
        make_result("a", "mesh", cycles=8170),
        make_result("b", "torus", cycles=8160),
    ]
    strict = rankings(results)[0]
    assert strict.winner == "torus"
    assert strict.tie is False

    banded = rankings(results, tolerance=20)[0]
    assert banded.winner is None
    assert banded.tie is True
    assert banded.order == ("torus", "mesh")
    assert "within 20 cycles" in banded.reason


def test_stability_tolerance_prevents_a_noise_flip():
    results = [
        make_result("a", "mesh", trace="t1", cycles=8170),
        make_result("b", "torus", trace="t1", cycles=8160),
        make_result("c", "mesh", trace="t2", cycles=9461),
        make_result("d", "torus", trace="t2", cycles=9710),
    ]
    strict = stability(results)
    assert strict["flips"]
    assert strict["tolerance"] == 0.0

    banded = stability(results, tolerance=20)
    assert banded["flips"] == ()
    assert banded["ties"]
    assert banded["tolerance"] == 20.0


def test_relative_tolerance_scales_with_the_best_result():
    """1.5% of 8,160 is 122 cycles; 1.5% of 32,086 is 481 cycles."""
    small = [
        make_result("a", "mesh", trace="small", cycles=8170),
        make_result("b", "torus", trace="small", cycles=8160),
    ]
    assert rankings(small, relative_tolerance=0.015)[0].tie is True

    large = [
        make_result("c", "mesh", trace="large", cycles=32202),
        make_result("d", "torus", trace="large", cycles=32086),
    ]
    assert rankings(large, relative_tolerance=0.015)[0].tie is True

    decisive = [
        make_result("e", "mesh", trace="read", cycles=9461),
        make_result("f", "torus", trace="read", cycles=9710),
    ]
    row = rankings(decisive, relative_tolerance=0.015)[0]
    assert row.tie is False
    assert row.winner == "mesh"


def test_negative_or_non_finite_tolerance_refuses():
    results = [make_result("a", "mesh", cycles=100)]
    with pytest.raises(DecisionMatrixError, match="tolerance"):
        rankings(results, tolerance=-1)
    with pytest.raises(DecisionMatrixError, match="tolerance"):
        stability(results, tolerance=float("inf"))


def test_ties_at_top_are_sorted_by_topology_name():
    results = [
        make_result("a", "zeta", cycles=100),
        make_result("b", "alpha", cycles=100),
        make_result("c", "beta", cycles=120),
    ]

    row = rankings(results)[0]

    assert row.order == ("alpha", "zeta", "beta")
    assert row.tie is True
    assert row.winner is None


def test_group_with_no_evaluated_results_has_no_winner():
    results = [
        make_result("a", "mesh", status="UNSUPPORTED", reason="no model"),
        make_result("b", "torus", status="FAILED", reason="boom"),
    ]

    row = rankings(results)[0]

    assert row.order == ()
    assert row.winner is None
    assert row.tie is False
    assert row.missing == ("mesh", "torus")
    assert row.reason == (
        "no evaluated results; missing: mesh (UNSUPPORTED: no model); "
        "torus (FAILED: boom)")


def test_duplicate_topology_in_one_group_is_refused():
    results = [
        make_result("a", "mesh", cycles=100),
        make_result("b", "mesh", cycles=120),
    ]

    with pytest.raises(DecisionMatrixError, match="duplicate topology"):
        rankings(results)


# ---------------------------------------------------------------------------
# Stability
# ---------------------------------------------------------------------------

def test_same_winner_across_traces_is_stable():
    results = [
        make_result("t1-mesh", "mesh", trace="t1", cycles=100),
        make_result("t1-torus", "torus", trace="t1", cycles=120),
        make_result("t2-mesh", "mesh", trace="t2", cycles=110),
        make_result("t2-torus", "torus", trace="t2", cycles=130),
    ]

    report = stability(results)

    assert report["stable"] is True
    assert report["winner_by_trace"] == {
        "c1": {"t1": "mesh", "t2": "mesh"},
    }
    assert report["flips"] == ()
    assert report["ties"] == ()
    assert report["incomplete"] == ()


def test_winner_change_is_a_flip():
    results = [
        make_result("t1-mesh", "mesh", trace="t1", cycles=100),
        make_result("t1-torus", "torus", trace="t1", cycles=120),
        make_result("t2-mesh", "mesh", trace="t2", cycles=130),
        make_result("t2-torus", "torus", trace="t2", cycles=110),
    ]

    report = stability(results)

    assert report["stable"] is False
    assert report["flips"] == ({
        "config": "c1",
        "from_trace": "t1",
        "to_trace": "t2",
        "from_winner": "mesh",
        "to_winner": "torus",
    },)
    assert report["ties"] == ()
    assert report["incomplete"] == ()
    assert report["winner_by_trace"] == {
        "c1": {"t1": "mesh", "t2": "torus"},
    }


def test_top_tie_is_reported_but_is_not_a_flip():
    results = [
        make_result("t1-mesh", "mesh", trace="t1", cycles=100),
        make_result("t1-torus", "torus", trace="t1", cycles=120),
        make_result("t2-mesh", "mesh", trace="t2", cycles=100),
        make_result("t2-torus", "torus", trace="t2", cycles=100),
    ]

    report = stability(results)

    assert report["stable"] is False
    assert report["flips"] == ()
    assert len(report["ties"]) == 1
    tie = report["ties"][0]
    assert tie["config"] == "c1"
    assert tie["trace"] == "t2"
    assert tie["topologies"] == ["mesh", "torus"]
    assert report["winner_by_trace"]["c1"]["t2"] is None


def test_incomplete_trace_is_reported_and_blocks_stability():
    results = [
        make_result("t1-mesh", "mesh", trace="t1", cycles=100),
        make_result("t1-torus", "torus", trace="t1", cycles=120),
        make_result("t2-mesh", "mesh", trace="t2", cycles=100),
        make_result("t2-torus", "torus", trace="t2",
                    status="UNSUPPORTED", reason="no torus model"),
    ]

    report = stability(results)

    assert report["stable"] is False
    assert report["flips"] == ()
    assert report["ties"] == ()
    assert len(report["incomplete"]) == 1
    incomplete = report["incomplete"][0]
    assert incomplete["config"] == "c1"
    assert incomplete["trace"] == "t2"
    assert incomplete["missing"] == ["torus"]
    assert report["winner_by_trace"]["c1"]["t2"] == "mesh"


def test_trace_with_no_evaluated_results_is_incomplete():
    results = [
        make_result("t1-mesh", "mesh", trace="t1", cycles=100),
        make_result("t2-mesh", "mesh", trace="t2",
                    status="FAILED", reason="backend down"),
        make_result("t2-torus", "torus", trace="t2",
                    status="UNSUPPORTED", reason="no model"),
    ]

    report = stability(results)

    assert report["stable"] is False
    assert report["winner_by_trace"]["c1"]["t2"] is None
    assert len(report["incomplete"]) == 1
    assert report["incomplete"][0]["missing"] == ["mesh", "torus"]


def test_tie_between_decisive_traces_does_not_hide_a_flip():
    results = [
        make_result("t1-mesh", "mesh", trace="t1", cycles=100),
        make_result("t1-torus", "torus", trace="t1", cycles=120),
        make_result("t2-mesh", "mesh", trace="t2", cycles=100),
        make_result("t2-torus", "torus", trace="t2", cycles=100),
        make_result("t3-mesh", "mesh", trace="t3", cycles=130),
        make_result("t3-torus", "torus", trace="t3", cycles=110),
    ]

    report = stability(results)

    assert len(report["ties"]) == 1
    assert len(report["flips"]) == 1
    flip = report["flips"][0]
    assert (flip["from_trace"], flip["to_trace"]) == ("t1", "t3")
    assert (flip["from_winner"], flip["to_winner"]) == ("mesh", "torus")


def test_stability_keeps_configs_separate():
    results = [
        # c1 flips from mesh to torus.
        make_result("c1-t1-mesh", "mesh", trace="t1", config="c1",
                    cycles=100),
        make_result("c1-t1-torus", "torus", trace="t1", config="c1",
                    cycles=120),
        make_result("c1-t2-mesh", "mesh", trace="t2", config="c1",
                    cycles=130),
        make_result("c1-t2-torus", "torus", trace="t2", config="c1",
                    cycles=110),
        # c2 keeps mesh on both traces.
        make_result("c2-t1-mesh", "mesh", trace="t1", config="c2",
                    cycles=100),
        make_result("c2-t1-torus", "torus", trace="t1", config="c2",
                    cycles=120),
        make_result("c2-t2-mesh", "mesh", trace="t2", config="c2",
                    cycles=100),
        make_result("c2-t2-torus", "torus", trace="t2", config="c2",
                    cycles=130),
    ]

    report = stability(results)

    assert report["stable"] is False
    assert report["winner_by_trace"] == {
        "c1": {"t1": "mesh", "t2": "torus"},
        "c2": {"t1": "mesh", "t2": "mesh"},
    }
    assert len(report["flips"]) == 1
    assert report["flips"][0]["config"] == "c1"
    assert report["ties"] == ()
    assert report["incomplete"] == ()


def test_stability_of_empty_results_does_not_claim_stability():
    assert stability(()) == {
        "stable": False,
        "winner_by_trace": {},
        "flips": (),
        "ties": (),
        "incomplete": (),
        "tolerance": 0.0,
        "relative_tolerance": 0.0,
    }


# ---------------------------------------------------------------------------
# Evaluator contract
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    None,
    [],
    {"completion_cycles": 10.0},
    {"status": "EVALUATED"},
    {"status": "EVALUATED", "completion_cycles": None},
    {"status": "EVALUATED", "completion_cycles": 10.0, "reason": "why"},
    {"status": "FAILED"},
    {"status": "FAILED", "reason": ""},
    {"status": "UNSUPPORTED", "reason": "   "},
    {"status": "BOGUS", "completion_cycles": 10.0},
    {"status": "EVALUATED", "completion_cycles": "10"},
    {"status": "EVALUATED", "completion_cycles": -1.0},
    {"status": "EVALUATED", "completion_cycles": 10.0, "p50": float("inf")},
    {"status": "EVALUATED", "completion_cycles": 10.0,
     "metadata": {"bad": {1, 2}}},
    {"status": "EVALUATED", "completion_cycles": 10.0,
     "metadata": {"bad": float("nan")}},
    {"status": "EVALUATED", "completion_cycles": 10.0,
     "metadata": {1: "non-string key"}},
    {"status": "EVALUATED", "completion_cycles": 10.0, "metadata": []},
    {"status": "EVALUATED", "completion_cycles": 10.0, "unknown": 1},
])
def test_evaluator_result_validation_refuses_bad_shapes(payload):
    case = make_case("c1", "mesh")

    with pytest.raises(DecisionMatrixError):
        run_matrix([case], lambda _case: payload)


def test_evaluator_exception_becomes_failed_not_a_crash():
    cases = [make_case("ok", "mesh"), make_case("bad", "torus")]

    def evaluator(case):
        if case.case_id == "bad":
            raise RuntimeError("simulator exploded")
        return evaluated_payload(100)

    results = run_matrix(cases, evaluator)

    assert [result.status for result in results] == ["EVALUATED", "FAILED"]
    failed = results[1]
    assert failed.case_id == "bad"
    assert failed.topology == "torus"
    assert failed.completion_cycles is None
    assert failed.reason == "RuntimeError: simulator exploded"
    assert failed.metadata == {"error_type": "RuntimeError"}


def test_evaluator_exception_without_message_uses_type_name():
    def evaluator(_case):
        raise RuntimeError()

    failed = run_matrix([make_case("bad", "mesh")], evaluator)[0]

    assert failed.status == "FAILED"
    assert failed.reason == "RuntimeError"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _mixed_results() -> tuple[MatrixResult, ...]:
    cases = [
        make_case("a", "mesh", metadata={"source": "legacy"}),
        make_case("b", "torus"),
        make_case("c", "dragonfly"),
    ]

    def evaluator(case):
        if case.case_id == "a":
            return {
                "status": "EVALUATED",
                "completion_cycles": 100,
                "p50": 90,
                "p95": 110,
                "p99": 120,
                "metadata": {"nested": (1, 2)},
            }
        if case.case_id == "b":
            return {"status": "FAILED", "reason": "backend down"}
        return {"status": "UNSUPPORTED", "reason": "no model"}

    return run_matrix(cases, evaluator)


def test_json_roundtrip_is_exact_and_json_safe():
    results = _mixed_results()

    document = to_dict(results)
    assert document["schema_version"] == 1
    assert [item["case_id"] for item in document["results"]] == [
        "a", "b", "c"]
    assert document["results"][0]["metadata"] == {"nested": [1, 2]}

    encoded = json.dumps(document, allow_nan=False)
    decoded = from_dict(json.loads(encoded))

    assert decoded == results
    assert to_dict(decoded) == document


def test_from_dict_refuses_unknown_document_key():
    document = to_dict(_mixed_results())
    document["extra"] = True

    with pytest.raises(DecisionMatrixError, match="unknown keys"):
        from_dict(document)


def test_from_dict_refuses_unknown_result_key():
    document = to_dict(_mixed_results())
    document["results"][0]["extra"] = True

    with pytest.raises(DecisionMatrixError, match="unknown keys"):
        from_dict(document)


def test_from_dict_refuses_missing_or_wrong_schema_version():
    document = to_dict(_mixed_results())

    with pytest.raises(DecisionMatrixError, match="schema_version"):
        from_dict({"results": document["results"]})

    document["schema_version"] = 2
    with pytest.raises(DecisionMatrixError, match="schema_version"):
        from_dict(document)

    document["schema_version"] = 1.0
    with pytest.raises(DecisionMatrixError, match="schema_version"):
        from_dict(document)


def test_from_dict_refuses_missing_required_result_key():
    document = to_dict(_mixed_results())
    del document["results"][0]["status"]

    with pytest.raises(DecisionMatrixError, match="missing keys"):
        from_dict(document)


def test_case_and_result_from_dict_refuse_unknown_keys():
    with pytest.raises(DecisionMatrixError, match="unknown keys"):
        MatrixCase.from_dict({
            "case_id": "c1", "topology": "mesh", "trace": "t1",
            "extra": 1,
        })

    with pytest.raises(DecisionMatrixError, match="unknown keys"):
        MatrixResult.from_dict({
            "case_id": "c1", "topology": "mesh", "trace": "t1",
            "status": "EVALUATED", "completion_cycles": 1.0,
            "extra": 1,
        })


# ---------------------------------------------------------------------------
# Determinism and value validation
# ---------------------------------------------------------------------------

def test_run_matrix_preserves_input_order_and_rankings_sort_groups():
    cases = [
        make_case("c3", "mesh", trace="t2", config="c1"),
        make_case("c1", "torus", trace="t1", config="c2"),
        make_case("c2", "ring", trace="t1", config="c1"),
    ]
    cycles = {"c3": 300, "c1": 100, "c2": 200}

    results = run_matrix(
        cases,
        lambda case: evaluated_payload(cycles[case.case_id]))

    assert [result.case_id for result in results] == ["c3", "c1", "c2"]
    rows = rankings(results)
    assert [(row.trace, row.config) for row in rows] == [
        ("t1", "c1"), ("t1", "c2"), ("t2", "c1")]
    assert [row.winner for row in rows] == ["ring", "torus", "mesh"]
    assert [result.case_id for result in from_dict(to_dict(results))] == [
        "c3", "c1", "c2"]


@pytest.mark.parametrize("kwargs", [
    {"case_id": "", "topology": "mesh", "trace": "t1"},
    {"case_id": "c1", "topology": "", "trace": "t1"},
    {"case_id": "c1", "topology": "mesh", "trace": "   "},
])
def test_case_identity_must_be_non_empty(kwargs):
    with pytest.raises(DecisionMatrixError):
        MatrixCase(**kwargs)


def test_config_may_be_empty_and_metadata_is_copied():
    metadata = {"nested": (1, 2), "flag": True}
    case = MatrixCase(
        case_id="c1", topology="mesh", trace="t1", metadata=metadata)

    assert case.config == ""
    assert case.metadata == {"nested": [1, 2], "flag": True}

    metadata["nested"] = "mutated"
    assert case.metadata == {"nested": [1, 2], "flag": True}


def test_duplicate_case_id_is_refused_before_evaluation():
    cases = [make_case("same", "mesh"), make_case("same", "torus")]
    calls = []

    def evaluator(case):
        calls.append(case.case_id)
        return evaluated_payload(100)

    with pytest.raises(DecisionMatrixError, match="duplicate case_id"):
        run_matrix(cases, evaluator)
    assert calls == []


@pytest.mark.parametrize("kwargs", [
    {"status": "NOPE", "completion_cycles": 1.0},
    {"status": "EVALUATED"},
    {"status": "EVALUATED", "completion_cycles": 1.0, "reason": "why"},
    {"status": "UNSUPPORTED"},
    {"status": "FAILED", "reason": "   "},
    {"status": "EVALUATED", "completion_cycles": -1.0},
    {"status": "EVALUATED", "completion_cycles": float("nan")},
    {"status": "EVALUATED", "completion_cycles": 1.0,
     "p95": float("inf")},
])
def test_matrix_result_validation(kwargs):
    base = {
        "case_id": "c1",
        "topology": "mesh",
        "trace": "t1",
        "config": "c1",
    }
    base.update(kwargs)

    with pytest.raises(DecisionMatrixError):
        MatrixResult(**base)


def test_decision_matrix_error_is_both_value_error_and_semantic_error():
    assert issubclass(DecisionMatrixError, ValueError)
    assert issubclass(DecisionMatrixError, SemanticError)

    with pytest.raises(ValueError):
        raise DecisionMatrixError("bad")
    with pytest.raises(SemanticError):
        raise DecisionMatrixError("bad")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_reads_precomputed_document(tmp_path, capsys):
    cases = [make_case("a", "mesh"), make_case("b", "torus")]
    document = {
        "cases": [case.to_dict() for case in cases],
        "results": [
            make_result("a", "mesh", cycles=100).to_dict(),
            make_result("b", "torus", cycles=120).to_dict(),
        ],
    }
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    assert main([str(path)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["rankings"][0]["winner"] == "mesh"
    assert payload["stability"]["stable"] is True


def test_cli_refuses_a_case_without_a_result(tmp_path, capsys):
    document = {
        "cases": [
            make_case("a", "mesh").to_dict(),
            make_case("b", "torus").to_dict(),
        ],
        "results": [make_result("a", "mesh", cycles=100).to_dict()],
    }
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    assert main([str(path)]) == 2

    error = json.loads(capsys.readouterr().err)
    assert "no result" in error["error"]


def test_cli_refuses_a_result_that_does_not_match_its_case(tmp_path,
                                                           capsys):
    document = {
        "cases": [make_case("a", "mesh").to_dict()],
        "results": [make_result("a", "torus", cycles=100).to_dict()],
    }
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    assert main([str(path)]) == 2

    error = json.loads(capsys.readouterr().err)
    assert "does not match" in error["error"]

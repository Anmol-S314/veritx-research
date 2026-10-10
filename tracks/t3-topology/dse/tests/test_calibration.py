from __future__ import annotations

import hashlib
import shutil
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from veritx_dse.performance.calibration import (
    CalibrationError,
    Observation,
    calibration_report,
    evaluate_holdout,
    fit_profile,
    grouped_split,
    import_profiler_observations,
)

ROOT = Path(__file__).resolve().parents[4]
DATA = (ROOT / "third_party/llmservingsim/profiler/perf/RTXPRO6000/Qwen"
        / "Qwen3-30B-A3B-Instruct-2507/bf16")
CSV = DATA / "tp1/attention.csv"
META = DATA / "meta.yaml"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path = CSV, meta: Path = META, *, tp: int = 1):
    return import_profiler_observations(path, meta,
                                        expected_csv_sha256=_digest(path),
                                        expected_metadata_sha256=_digest(meta), tp=tp, ep=1,
                                        replicate_semantics="aggregate_semantics_unreported")


def test_actual_profiler_source_imports_identity_and_holdout_report():
    dataset = _load()
    assert dataset.source_type == "profiler_measurement"
    assert dataset.model == "Qwen/Qwen3-30B-A3B-Instruct-2507"
    assert dataset.hardware == "RTXPRO6000" and dataset.variant == "bf16"
    assert dataset.measurement_iterations == 3
    assert dataset.observations[0].value == Decimal("7.69067")
    assert dataset.observations[0].duration_ns == Fraction(769067, 100)
    train, test = grouped_split(dataset)
    assert len(train) + len(test) == 19364
    assert {x.kv_decode for x in train}.isdisjoint({x.kv_decode for x in test})
    fit = fit_profile(dataset, train)
    report = calibration_report(dataset)
    assert fit["value_ns"] == report["fit"]["value_ns"]
    assert fit["schema"] == "CONSTANT_MEAN_DURATION_BASELINE_V1"
    assert report["execution_identity"]["tp"] == 1
    assert len(report["evaluation"]["holdout_row_ids"]) == len(test)
    assert report["evaluation"]["claim_limit"].startswith("profiler compute baseline")
    assert report["evaluation"]["status"] == "NEEDS_ACCEPTANCE/PROVENANCE"
    assert report["evaluation"]["mae_ns"] >= 0


def test_holdout_values_do_not_change_fitted_parameters():
    dataset = _load()
    train, test = grouped_split(dataset)
    fitted = fit_profile(dataset, train)
    changed = tuple(replace(row, value=row.value * 2,
                            duration_ns=row.duration_ns * 2) for row in test)
    assert fit_profile(dataset, train)["value_ns"] == fitted["value_ns"]
    assert evaluate_holdout(dataset, fitted, changed, train=train)["mae_ns"] != 0


def test_mixed_scale_synthetic_fixture_keeps_unmasked_row_errors():
    base = _load()
    rows = tuple(Observation(f"synthetic-{i}", 0, 0, 1, i + 1,
                             Decimal(str(v)), "us", Fraction(v * 1000))
                 for i, v in enumerate((1, 1, 10000, 10000)))
    # Same coordinate, distinct replicate identity; its entire kv_decode group
    # remains on the training side of the split.
    rows += (Observation("synthetic-replicate", 0, 0, 1, 1,
                         Decimal("1"), "us", Fraction(1000)),)
    fixture = replace(base, source_type="synthetic_fixture", observations=rows)
    train, holdout = grouped_split(fixture, holdout_group_count=1)
    fitted = fit_profile(fixture, train, holdout_group_count=1)
    assert fitted["source_type"] == "synthetic_fixture"
    # Training includes an adversarial 10,000us value; arithmetic mean is exact,
    # while the row-level holdout record still exposes its full residual.
    assert fitted["value_ns"] == {"numerator": 2500750, "denominator": 1}
    scored = evaluate_holdout(fixture, fitted, holdout, train=train)
    assert scored["residuals"][0]["absolute_error_ns"] > 7_000_000
    assert scored["status"] == "NEEDS_ACCEPTANCE/PROVENANCE"


def test_import_rejects_tampered_digest_and_unstated_unit(tmp_path):
    copy = tmp_path / "tp1" / "attention.csv"
    copy.parent.mkdir()
    shutil.copyfile(CSV, copy)
    with copy.open("a") as fh:
        fh.write("\n")
    with pytest.raises(CalibrationError, match="digest"):
        import_profiler_observations(copy, META, expected_csv_sha256=_digest(CSV),
                                     expected_metadata_sha256=_digest(META), tp=1, ep=1,
                                     replicate_semantics="aggregate_semantics_unreported")
    with pytest.raises(CalibrationError, match="unit"):
        import_profiler_observations(CSV, META, expected_csv_sha256=_digest(CSV),
                                     expected_metadata_sha256=_digest(META), tp=1, ep=1,
                                     replicate_semantics="aggregate_semantics_unreported",
                                     unit="ns")


def test_import_requires_unknown_replicate_semantics_to_remain_explicit():
    with pytest.raises(CalibrationError, match="replicate_semantics"):
        import_profiler_observations(CSV, META, expected_csv_sha256=_digest(CSV),
                                     expected_metadata_sha256=_digest(META), tp=1, ep=1)


def test_import_rejects_tp_mismatch_and_wrong_metadata_identity(tmp_path):
    with pytest.raises(CalibrationError, match="not declared"):
        _load(tp=3)
    meta = tmp_path / "meta.yaml"
    meta.write_text(META.read_text().replace("hardware: RTXPRO6000", "hardware: ''"))
    with pytest.raises(CalibrationError, match="metadata.hardware"):
        import_profiler_observations(CSV, meta, expected_csv_sha256=_digest(CSV),
                                     expected_metadata_sha256=_digest(meta), tp=1, ep=1,
                                     replicate_semantics="aggregate_semantics_unreported")


def test_fit_and_evaluation_fail_closed_for_unsupported_parameters_or_leakage():
    dataset = _load()
    train, test = grouped_split(dataset)
    with pytest.raises(CalibrationError, match="parameter is supported"):
        fit_profile(dataset, train, declared_parameters=("nonsense",))
    fit = fit_profile(dataset, train)
    with pytest.raises(CalibrationError, match="leakage"):
        evaluate_holdout(dataset, fit, test[:1], train=train + (test[0],))
    forged = dict(fit, tp=2)
    with pytest.raises(CalibrationError, match="identity"):
        evaluate_holdout(dataset, forged, test, train=train)
    forged_value = dict(fit, value_ns={"numerator": 0, "denominator": 1})
    with pytest.raises(CalibrationError, match="does not recompute"):
        evaluate_holdout(dataset, forged_value, test, train=train)
    relabeled = replace(dataset, source_type="simulator_output")
    with pytest.raises(CalibrationError, match="identity"):
        evaluate_holdout(relabeled, fit, test, train=train)


def test_empty_holdout_is_rejected():
    dataset = _load()
    with pytest.raises(CalibrationError, match="requires at least one train"):
        grouped_split(dataset, holdout_group_count=99)
    with pytest.raises(CalibrationError, match="non-empty train and holdout"):
        evaluate_holdout(dataset, {}, (), train=dataset.observations[:1])

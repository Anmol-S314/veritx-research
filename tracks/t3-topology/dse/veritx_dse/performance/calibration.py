"""Identity-bound profiler observations and holdout-only baseline evaluation.

CONSTANT_MEAN_DURATION_BASELINE_V1 is an opt-in mean-duration baseline over
one exact profiler slice. It is not NoC, memory-system, or hardware calibration.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any

import yaml


class CalibrationError(ValueError):
    """Observation provenance, identity, split, or fit is invalid."""


_COORDINATES = ("prefill_chunk", "kv_prefill", "n_decode", "kv_decode")
_FIT_PARAMETERS = frozenset({"duration_ns arithmetic mean"})
_MAX_SOURCE_BYTES = 50 * 1024 * 1024
_MAX_OBSERVATIONS = 50_000
_METADATA_FIELDS = frozenset({
    "profiler_version", "vllm_version", "cuda_version", "gpu", "hardware",
    "profiled_at", "model", "variant", "measurement_iterations",
    "engine_effective",
})


@dataclass(frozen=True)
class Observation:
    row_id: str
    prefill_chunk: int
    kv_prefill: int
    n_decode: int
    kv_decode: int
    value: Decimal
    unit: str
    duration_ns: Fraction


@dataclass(frozen=True)
class ObservationSet:
    source_path: str
    source_sha256: str
    metadata_path: str
    metadata_sha256: str
    source_type: str
    model: str
    hardware: str
    variant: str
    tp: int
    ep: int
    component: str
    metric: str
    clock: str
    unit: str
    measurement_iterations: int
    replicate_semantics: str
    profiler_version: str
    vllm_version: str
    cuda_version: str
    gpu: str
    profiled_at: str
    engine_effective_sha256: str
    observations: tuple[Observation, ...]

    @property
    def identity(self) -> str:
        body = asdict(self)
        body.pop("observations")
        body["observations"] = [{
            "row_id": x.row_id,
            "coordinates": [getattr(x, k) for k in _COORDINATES],
            "value": str(x.value), "unit": x.unit,
            "duration_ns": [x.duration_ns.numerator, x.duration_ns.denominator],
        } for x in self.observations]
        return hashlib.sha256(json.dumps(body, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _positive_int(v: Any, name: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise CalibrationError(f"{name} must be a positive integer")
    return v


def import_profiler_observations(csv_path: str | Path, metadata_path: str | Path,
                                 *, expected_csv_sha256: str,
                                 expected_metadata_sha256: str,
                                 tp: int, ep: int, component: str = "attention",
                                 metric: str = "time_us", unit: str = "us",
                                 clock: str = "profiler-reported elapsed time",
                                 replicate_semantics: str = "") -> ObservationSet:
    """Import caller-pinned profiler bytes with explicit execution identity."""
    source, meta_path = Path(csv_path), Path(metadata_path)
    if unit != "us":
        raise CalibrationError("only explicit profiler CSV unit 'us' is supported")
    if not isinstance(clock, str) or not clock.strip():
        raise CalibrationError("clock must name the measurement clock")
    if replicate_semantics != "aggregate_semantics_unreported":
        raise CalibrationError("replicate_semantics must explicitly state aggregate_semantics_unreported")
    if component != "attention" or metric != "time_us":
        raise CalibrationError("only attention component metric time_us is supported")
    tp, ep = _positive_int(tp, "tp"), _positive_int(ep, "ep")
    for p in (source, meta_path):
        if not p.is_file():
            raise CalibrationError(f"source file not found: {p}")
        if p.stat().st_size > _MAX_SOURCE_BYTES:
            raise CalibrationError(f"source exceeds {_MAX_SOURCE_BYTES} byte bound: {p}")
    csv_hash, meta_hash = _sha256(source), _sha256(meta_path)
    if csv_hash != expected_csv_sha256 or meta_hash != expected_metadata_sha256:
        raise CalibrationError("source digest does not match pinned identity")
    try:
        meta = yaml.safe_load(meta_path.read_text())
    except Exception as exc:
        raise CalibrationError(f"invalid profiler metadata: {exc}") from exc
    if not isinstance(meta, dict) or not _METADATA_FIELDS <= set(meta):
        missing = sorted(_METADATA_FIELDS - set(meta or {}))
        raise CalibrationError(f"metadata missing required provenance: {missing}")
    for key in ("profiler_version", "vllm_version", "cuda_version", "gpu",
                "hardware", "profiled_at", "model", "variant"):
        if not isinstance(meta[key], str) or not meta[key].strip():
            raise CalibrationError(f"metadata.{key} must be non-empty text")
    _positive_int(meta["measurement_iterations"], "measurement_iterations")
    degrees = meta.get("tp_degrees")
    if not isinstance(degrees, list) or tp not in degrees:
        raise CalibrationError(f"tp{tp} is not declared in metadata.tp_degrees")
    effective = meta["engine_effective"]
    if not isinstance(effective, dict) or not effective:
        raise CalibrationError("metadata.engine_effective must be a non-empty object")
    if effective.get("tensor_parallel_size") != tp:
        raise CalibrationError("metadata engine tensor_parallel_size does not match tp identity")
    if source.as_posix().split("/")[-2:] != [f"tp{tp}", "attention.csv"]:
        raise CalibrationError("only explicitly identified tp<N>/attention.csv is supported")
    rows: list[Observation] = []
    try:
        with source.open(newline="") as fh:
            reader = csv.DictReader(fh)
            if tuple(reader.fieldnames or ()) != (*_COORDINATES, metric):
                raise CalibrationError("CSV axes/metric must exactly match declared attention schema")
            for row_no, row in enumerate(reader, start=2):
                try:
                    coords = tuple(int(row[k]) for k in _COORDINATES)
                    value = Decimal(row[metric])
                except (TypeError, ValueError, InvalidOperation) as exc:
                    raise CalibrationError(f"invalid numeric value at CSV row {row_no}") from exc
                if any(x < 0 for x in coords) or not value.is_finite() or value <= 0:
                    raise CalibrationError(f"invalid coordinate/duration at CSV row {row_no}")
                if row_no - 1 > _MAX_OBSERVATIONS:
                    raise CalibrationError(f"observation count exceeds {_MAX_OBSERVATIONS}")
                row_identity = f"{csv_hash}:{row_no}:{coords}:{value}"
                rid = hashlib.sha256(row_identity.encode()).hexdigest()
                rows.append(Observation(rid, *coords, value, unit, Fraction(value) * 1000))
    except OSError as exc:
        raise CalibrationError(f"cannot read observations: {exc}") from exc
    if not rows:
        raise CalibrationError("observation CSV is empty")
    return ObservationSet(
        source_path=source.as_posix(), source_sha256=csv_hash,
        metadata_path=meta_path.as_posix(), metadata_sha256=meta_hash,
        source_type="profiler_measurement", model=meta["model"],
        hardware=meta["hardware"], variant=meta["variant"], tp=tp, ep=ep,
        component=component, metric=metric, clock=clock, unit=unit,
        measurement_iterations=meta["measurement_iterations"],
        replicate_semantics=replicate_semantics,
        profiler_version=meta["profiler_version"], vllm_version=meta["vllm_version"],
        cuda_version=meta["cuda_version"], gpu=meta["gpu"],
        profiled_at=meta["profiled_at"],
        engine_effective_sha256=hashlib.sha256(json.dumps(
            effective, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        observations=tuple(rows))


def grouped_split(dataset: ObservationSet, *, holdout_group_count: int = 2
                  ) -> tuple[tuple[Observation, ...], tuple[Observation, ...]]:
    """Deterministically hold out whole largest kv_decode coordinate groups."""
    count = _positive_int(holdout_group_count, "holdout_group_count")
    groups = sorted({o.kv_decode for o in dataset.observations})
    if len(groups) <= count:
        raise CalibrationError("grouped split requires at least one train and holdout group")
    held_groups = set(groups[-count:])
    train = tuple(o for o in dataset.observations if o.kv_decode not in held_groups)
    holdout = tuple(o for o in dataset.observations if o.kv_decode in held_groups)
    if not train or not holdout or {o.kv_decode for o in train} & {o.kv_decode for o in holdout}:
        raise CalibrationError("train/holdout group leakage or empty partition")
    return train, holdout


def fit_profile(dataset: ObservationSet, train: tuple[Observation, ...], *,
                holdout_group_count: int = 2,
                declared_parameters: tuple[str, ...] = ("duration_ns arithmetic mean",)
                ) -> dict[str, Any]:
    """Fit CONSTANT_MEAN_DURATION_BASELINE_V1 using training observations only."""
    if not train:
        raise CalibrationError("fit requires non-empty training rows")
    if declared_parameters != ("duration_ns arithmetic mean",):
        raise CalibrationError("only the exact duration_ns arithmetic mean parameter is supported")
    expected_train, expected_holdout = grouped_split(
        dataset, holdout_group_count=holdout_group_count)
    train_ids = sorted(o.row_id for o in train)
    if train_ids != sorted(o.row_id for o in expected_train):
        raise CalibrationError("training rows do not match deterministic split configuration")
    holdout_ids = sorted(o.row_id for o in expected_holdout)
    split_id = hashlib.sha256(json.dumps(
        {"holdout_group_count": holdout_group_count, "train": train_ids,
         "holdout": holdout_ids}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    # Exact decimal-to-Fraction conversion avoids rounding during fitting.
    value = sum((o.duration_ns for o in train), Fraction(0)) / len(train)
    return {"schema": "CONSTANT_MEAN_DURATION_BASELINE_V1", "source_identity": dataset.identity,
            "source_type": dataset.source_type, "model": dataset.model,
            "hardware": dataset.hardware, "variant": dataset.variant,
            "tp": dataset.tp, "ep": dataset.ep, "component": dataset.component,
            "metric": dataset.metric, "unit": "ns",
            "fit_parameter": "duration_ns arithmetic mean",
            "value_ns": {"numerator": value.numerator, "denominator": value.denominator},
            "training_row_ids": train_ids, "holdout_row_ids": holdout_ids,
            "holdout_group_count": holdout_group_count, "split_identity": split_id,
            "fit_scope": "profiler duration baseline over sampled coordinate domain",
            "provenance_status": "NEEDS_PROVENANCE"}


def evaluate_holdout(dataset: ObservationSet, fit: dict[str, Any],
                     holdout: tuple[Observation, ...], *,
                     train: tuple[Observation, ...]) -> dict[str, Any]:
    """Score a held-out group set; refuses changed identity or leakage."""
    if not holdout or not train:
        raise CalibrationError("evaluation requires non-empty train and holdout")
    expected_identity = {"source_identity": dataset.identity, "source_type": dataset.source_type,
                         "model": dataset.model, "hardware": dataset.hardware,
                         "variant": dataset.variant, "tp": dataset.tp, "ep": dataset.ep,
                         "component": dataset.component, "metric": dataset.metric,
                         "unit": "ns", "schema": "CONSTANT_MEAN_DURATION_BASELINE_V1"}
    if any(fit.get(key) != value for key, value in expected_identity.items()):
        raise CalibrationError("fit provenance/identity does not match observations")
    if fit.get("fit_parameter") not in _FIT_PARAMETERS:
        raise CalibrationError("fit parameter is unsupported")
    train_ids, test_ids = {o.row_id for o in train}, {o.row_id for o in holdout}
    known = {o.row_id for o in dataset.observations}
    if train_ids & test_ids or (train_ids | test_ids) - known:
        raise CalibrationError("train/test row leakage or foreign rows")
    if sorted(test_ids) != fit.get("holdout_row_ids"):
        raise CalibrationError("holdout rows do not match fitted split configuration")
    if sorted(train_ids) != fit.get("training_row_ids"):
        raise CalibrationError("training rows do not match fitted parameter provenance")
    expected_split_id = hashlib.sha256(json.dumps(
        {"holdout_group_count": fit.get("holdout_group_count"),
         "train": sorted(train_ids), "holdout": sorted(test_ids)},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if fit.get("split_identity") != expected_split_id:
        raise CalibrationError("split identity does not match fitted partitions")
    expected_fit = sum((o.duration_ns for o in train), Fraction(0)) / len(train)
    encoded = {"numerator": expected_fit.numerator, "denominator": expected_fit.denominator}
    if fit.get("value_ns") != encoded:
        raise CalibrationError("fit value does not recompute from declared training rows")
    train_groups = {o.kv_decode for o in train}
    test_groups = {o.kv_decode for o in holdout}
    if train_groups & test_groups:
        raise CalibrationError("train/test group leakage")
    pred = expected_fit
    residuals = [{"row_id": o.row_id,
                  "coordinates": {k: getattr(o, k) for k in _COORDINATES},
                  "observed_ns": float(o.duration_ns), "predicted_ns": float(pred),
                  "signed_error_ns": float(pred - o.duration_ns),
                  "absolute_error_ns": float(abs(pred - o.duration_ns)),
                  "relative_error": float(abs(pred - o.duration_ns) / o.duration_ns)}
                 for o in holdout]
    errors = [abs(pred - o.duration_ns) for o in holdout]
    train_ranges = {k: (min(getattr(o, k) for o in train), max(getattr(o, k) for o in train))
                    for k in _COORDINATES}
    outside = {k: any(getattr(o, k) < lo or getattr(o, k) > hi for o in holdout)
                for k, (lo, hi) in train_ranges.items()}
    split_identity = hashlib.sha256(json.dumps(
        {"train": sorted(train_ids), "holdout": sorted(test_ids)},
        separators=(",", ":")).encode()).hexdigest()
    return {"schema": "veritx.calibration-evaluation/1",
            "source_identity": dataset.identity, "source_type": dataset.source_type,
            "fit_parameter": fit["fit_parameter"], "train_row_ids": sorted(train_ids),
            "holdout_row_ids": sorted(test_ids), "split_identity": split_identity,
            "holdout_groups_kv_decode": sorted(test_groups), "residuals": residuals,
            "workload_coverage": {"train_rows": len(train), "holdout_rows": len(holdout),
                                  "train_coordinate_ranges": {k: list(v) for k, v in train_ranges.items()},
                                  "holdout_outside_training_axis": outside,
                                  "extrapolation_evaluation_only": any(outside.values()),
                                  "train_distinct_duration_count": len({o.duration_ns for o in train}),
                                  "train_duration_variation": "varied" if len({o.duration_ns for o in train}) > 1 else "no_variation"},
            "mae_ns": float(sum(errors, Fraction(0)) / len(errors)),
            "rmse_ns": math.sqrt(sum(float(x*x) for x in errors) / len(errors)),
            "max_absolute_error_ns": float(max(errors)),
            "status": "NEEDS_ACCEPTANCE/PROVENANCE",
            "provenance_status": "NEEDS_PROVENANCE",
            "claim_limit": "profiler compute baseline only; not validated accelerator timing, NoC/cache/DRAM calibration, or qualified hardware"}


def calibration_report(dataset: ObservationSet, *, holdout_group_count: int = 2
                       ) -> dict[str, Any]:
    train, holdout = grouped_split(dataset, holdout_group_count=holdout_group_count)
    fit = fit_profile(dataset, train, holdout_group_count=holdout_group_count)
    return {"observation_identity": dataset.identity,
            "source": {"path": dataset.source_path, "sha256": dataset.source_sha256,
                       "metadata_path": dataset.metadata_path,
                       "metadata_sha256": dataset.metadata_sha256,
                       "source_type": dataset.source_type, "model": dataset.model,
                       "hardware": dataset.hardware, "variant": dataset.variant,
                       "tp": dataset.tp, "ep": dataset.ep, "component": dataset.component,
                       "metric": dataset.metric, "clock": dataset.clock, "unit": dataset.unit,
                       "measurement_iterations": dataset.measurement_iterations,
                       "replicate_semantics": dataset.replicate_semantics},
            "execution_identity": {"model": dataset.model, "hardware": dataset.hardware,
                                   "variant": dataset.variant, "tp": dataset.tp,
                                   "ep": dataset.ep, "component": dataset.component,
                                   "metric": dataset.metric, "unit": dataset.unit,
                                   "engine_effective_sha256": dataset.engine_effective_sha256},
            "fit": fit, "evaluation": evaluate_holdout(dataset, fit, holdout, train=train)}


def main(argv: list[str] | None = None) -> int:
    """Emit a deterministic fit/evaluation JSON report for pinned profiler bytes."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("metadata", type=Path)
    parser.add_argument("--csv-sha256", required=True)
    parser.add_argument("--metadata-sha256", required=True)
    parser.add_argument("--tp", required=True, type=int)
    parser.add_argument("--ep", required=True, type=int)
    parser.add_argument("--replicate-semantics", required=True,
                        choices=("aggregate_semantics_unreported",))
    parser.add_argument("--holdout-groups", type=int, default=2)
    args = parser.parse_args(argv)
    dataset = import_profiler_observations(
        args.csv, args.metadata, expected_csv_sha256=args.csv_sha256,
        expected_metadata_sha256=args.metadata_sha256, tp=args.tp, ep=args.ep,
        replicate_semantics=args.replicate_semantics)
    print(json.dumps(calibration_report(dataset, holdout_group_count=args.holdout_groups),
                     sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["CalibrationError", "Observation", "ObservationSet",
           "import_profiler_observations", "grouped_split", "fit_profile",
           "evaluate_holdout", "calibration_report"]

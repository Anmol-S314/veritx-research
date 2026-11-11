"""VLA-Perf roofline reader — MODELED numbers, never measurements.

VLA-Perf (https://github.com/NVlabs/vla-perf) is an analytical performance
model. Its perf-results CSVs report **modeled** roofline latencies for VLA
inference (compute versus memory limits), not timings observed on hardware.
This module vendors a small, attributed subset under
``tracks/t3-topology/data/vla-perf/`` and parses it with the standard library.
The one validation CSV in that subset also carries a ``real_ms`` comparison
column from prior real-time-VLA work; it is not a compute source here.

No stage value used by this module or the ``pi0_thor_modeled-v4`` template is
measured, benchmarked, or traced. The template ``_comment`` says the same.

Pinned upstream commit: ``1e2b9a7ef9d4188c7e1e2befbdc758222c60d760``.
"""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

VLA_PERF_UPSTREAM = "https://github.com/NVlabs/vla-perf"
VLA_PERF_COMMIT = "1e2b9a7ef9d4188c7e1e2befbdc758222c60d760"
VLA_PERF_COMMIT_DATE = "2026-02-26T16:52:55Z"
VLA_PERF_RETRIEVED = "2026-11-05"
VLA_PERF_LICENSE = "MIT (vla-perf/LICENSE); repository root Apache-2.0"
VLA_PERF_DATA_REL = "tracks/t3-topology/data/vla-perf"
PI0_THOR_WORKLOAD_ID = "pi0-thor-modeled"

_PI0_E2E_FILE = "pi0_family_e2e_perf.csv"
_IMAGE_NETWORK_FILE = "network_latency_images.csv"
_KV_CACHE_FILE = "network_latency_bidirectional_kvcache.csv"
_README_FILE = "README.md"

_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "vla-perf"


class VlaPerfError(ValueError):
    """Base class for deterministic VLA-Perf data errors."""


class VlaPerfSchemaError(VlaPerfError):
    """A vendored CSV is malformed or does not carry the expected schema."""


class VlaPerfMissingColumn(VlaPerfSchemaError):
    """A required CSV column is absent."""


class VlaPerfMissingRow(VlaPerfError):
    """The requested row (hardware, resolution, sequence length, ...) is absent."""


_PI0_COLUMNS = (
    "model.name",
    "model.stage",
    "model.seq_len_inference_prefill",
    "hardware.name",
    "hardware.num_chips",
    "batch_size",
    "vision_time_ms",
    "vlm_time_ms",
    "action_time_ms",
    "e2e_time_ms",
    "vision_boundness",
    "vlm_boundness",
    "action_boundness",
    "vision_op_intensity",
    "vlm_op_intensity",
    "action_op_intensity",
)
_PI0_TEXT_COLUMNS = (
    "model.name",
    "model.stage",
    "hardware.name",
    "vision_boundness",
    "vlm_boundness",
    "action_boundness",
)
_PI0_INT_COLUMNS = (
    "model.seq_len_inference_prefill",
    "hardware.num_chips",
    "batch_size",
)
_PI0_FLOAT_COLUMNS = (
    "vision_time_ms",
    "vlm_time_ms",
    "action_time_ms",
    "e2e_time_ms",
    "vision_op_intensity",
    "vlm_op_intensity",
    "action_op_intensity",
)

_IMAGE_COLUMNS = (
    "network",
    "network_bandwidth_mbps_upload",
    "network_bandwidth_mbps_download",
    "network_base_latency_ms",
    "image_config",
    "image_resolution",
    "image_size_bytes",
    "image_size_mb",
    "effective_size_bytes",
    "transfer_time_ms",
    "total_latency_ms",
    "max_frequency_sync_hz",
    "max_frequency_async_hz",
)
_IMAGE_INT_COLUMNS = ("image_resolution", "image_size_bytes")

_KV_COLUMNS = (
    "network",
    "network_bandwidth_mbps_upload",
    "network_bandwidth_mbps_download",
    "image_config",
    "image_size_bytes",
    "return_data_type",
    "return_data_config",
    "return_size_bytes",
    "upload_latency_ms",
    "download_latency_ms",
    "round_trip_latency_ms",
    "round_trip_transfer_ms",
    "max_frequency_sync_hz",
    "max_frequency_async_hz",
)
_KV_INT_COLUMNS = ("image_size_bytes", "return_size_bytes")
_KV_CONFIG_RE = re.compile(r"\(seq=(\d+),\s*([A-Za-z0-9_.+-]+)\)\s*$")
_COMMIT_RE = re.compile(r"\b[0-9a-f]{40}\b")

_STAGE_COLUMNS = (
    "vision_time_ms",
    "vlm_time_ms",
    "action_time_ms",
    "e2e_time_ms",
    "vision_boundness",
    "vlm_boundness",
    "action_boundness",
    "vision_op_intensity",
    "vlm_op_intensity",
    "action_op_intensity",
)


def _data_dir(data_dir: str | Path | None) -> Path:
    path = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    if not path.is_dir():
        raise VlaPerfError(f"VLA-Perf data directory is missing: {path}")
    return path


def _repo_data_dir(repo_root: str | Path) -> Path:
    path = Path(repo_root) / VLA_PERF_DATA_REL
    if not path.is_dir():
        raise VlaPerfError(
            f"VLA-Perf data directory is missing: {path} "
            f"(expected the vendored subset under {VLA_PERF_DATA_REL})")
    return path


def _as_text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VlaPerfSchemaError(f"{where} must be a non-empty string, got {value!r}")
    return value.strip()


def _as_float(value: Any, where: str) -> float:
    if isinstance(value, bool) or value is None:
        raise VlaPerfSchemaError(f"{where} must be a number, got {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise VlaPerfSchemaError(
            f"{where} must be a number, got {value!r}") from exc
    if not math.isfinite(number):
        raise VlaPerfSchemaError(f"{where} must be finite, got {value!r}")
    return number


def _as_int(value: Any, where: str) -> int:
    if isinstance(value, bool) or value is None:
        raise VlaPerfSchemaError(f"{where} must be an integer, got {value!r}")
    text = value.strip() if isinstance(value, str) else value
    try:
        number = int(text)
    except (TypeError, ValueError) as exc:
        raise VlaPerfSchemaError(
            f"{where} must be an integer, got {value!r}") from exc
    if number < 0:
        raise VlaPerfSchemaError(f"{where} must be >= 0, got {value!r}")
    return number


def _read_rows(
    path: str | Path,
    required: Sequence[str],
) -> list[tuple[int, dict[str, str]]]:
    """Read a CSV, refusing missing columns, ragged rows, and empty files."""
    csv_path = Path(path)
    if not csv_path.is_file():
        raise VlaPerfError(f"VLA-Perf CSV is missing: {csv_path}")
    try:
        handle = csv_path.open("r", encoding="utf-8", newline="")
    except OSError as exc:
        raise VlaPerfError(f"VLA-Perf CSV cannot be read: {csv_path}") from exc
    with handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        if fieldnames is None:
            raise VlaPerfSchemaError(f"{csv_path}: empty CSV has no header")
        missing = sorted(set(required) - set(fieldnames))
        if missing:
            raise VlaPerfMissingColumn(
                f"{csv_path}: missing column(s) {', '.join(missing)}")
        rows: list[tuple[int, dict[str, str]]] = []
        try:
            for line_number, raw in enumerate(reader, start=2):
                if raw is None:
                    continue
                if None in raw:
                    raise VlaPerfSchemaError(
                        f"{csv_path}:{line_number}: row has more fields than "
                        f"the {len(fieldnames)}-column header")
                rows.append((line_number, raw))
        except csv.Error as exc:
            raise VlaPerfSchemaError(
                f"{csv_path}: malformed CSV: {exc}") from exc
    if not rows:
        raise VlaPerfMissingRow(f"{csv_path}: no data rows")
    return rows


def _coerce_row(
    raw: Mapping[str, Any],
    *,
    where: str,
    text_columns: Sequence[str],
    int_columns: Sequence[str],
    float_columns: Sequence[str],
) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for column in text_columns:
        row[column] = _as_text(raw.get(column), f"{where}.{column}")
    for column in int_columns:
        row[column] = _as_int(raw.get(column), f"{where}.{column}")
    for column in float_columns:
        row[column] = _as_float(raw.get(column), f"{where}.{column}")
    return row


def load_pi0_rows(path: str | Path) -> list[dict[str, Any]]:
    """Load ``pi0_family_e2e_perf.csv`` into typed dict rows.

    Numeric columns become ``int``/``float``; identity and boundness columns
    stay strings. Raises :class:`VlaPerfMissingColumn` if the pinned schema
    changed and :class:`VlaPerfSchemaError` if a value is malformed.
    """
    csv_path = Path(path)
    parsed: list[dict[str, Any]] = []
    for line_number, raw in _read_rows(csv_path, _PI0_COLUMNS):
        parsed.append(_coerce_row(
            raw,
            where=f"{csv_path}:{line_number}",
            text_columns=_PI0_TEXT_COLUMNS,
            int_columns=_PI0_INT_COLUMNS,
            float_columns=_PI0_FLOAT_COLUMNS,
        ))
    return parsed


def thor_rows(
    rows: Sequence[Mapping[str, Any]],
    hardware: str = "Thor",
) -> list[Mapping[str, Any]]:
    """Select π0 rows whose ``hardware.name`` contains ``hardware``.

    The vendored file spells the device ``Jetson_AGX_Thor``; the default
    substring ``"Thor"`` matches it. A missing match is a refusal, never an
    empty result that a caller could mistake for "no data required".
    """
    needle = _as_text(hardware, "hardware").casefold()
    selected = [
        row for row in rows
        if needle in _as_text(
            row.get("hardware.name"), "row.hardware.name").casefold()
    ]
    if not selected:
        available = sorted({
            str(row.get("hardware.name"))
            for row in rows if row.get("hardware.name")
        })
        raise VlaPerfMissingRow(
            f"no pi0 row for hardware matching {hardware!r}; "
            f"available: {', '.join(available) or '(none)'}")
    return selected


def stage_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return the modeled stage breakdown for one π0 row.

    The returned numbers are VLA-Perf roofline estimates in milliseconds.
    ``boundness`` and ``intensity`` are per-stage mappings.
    """
    if not isinstance(row, Mapping):
        raise VlaPerfSchemaError(
            f"pi0 row must be a mapping, got {type(row).__name__}")
    missing = sorted(set(_STAGE_COLUMNS) - set(row))
    if missing:
        raise VlaPerfMissingColumn(
            f"pi0 row is missing column(s) {', '.join(missing)}")

    def number(column: str) -> float:
        return _as_float(row[column], f"pi0 row.{column}")

    return {
        "vision_ms": number("vision_time_ms"),
        "vlm_ms": number("vlm_time_ms"),
        "action_ms": number("action_time_ms"),
        "e2e_ms": number("e2e_time_ms"),
        "boundness": {
            "vision": _as_text(row["vision_boundness"], "pi0 row.vision_boundness"),
            "vlm": _as_text(row["vlm_boundness"], "pi0 row.vlm_boundness"),
            "action": _as_text(row["action_boundness"], "pi0 row.action_boundness"),
        },
        "intensity": {
            "vision": number("vision_op_intensity"),
            "vlm": number("vlm_op_intensity"),
            "action": number("action_op_intensity"),
        },
    }


def _is_compressed(image_config: str) -> bool:
    return "(comp 0.1x)" in image_config


def network_image_row(
    resolution: int,
    *,
    network: str | None = None,
    compressed: bool = False,
    data_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return image-upload rows for one resolution from the network CSV.

    ``network_latency_images.csv`` is keyed by network AND resolution AND
    compression, so this returns every matching per-network row in file order.
    Pass ``network`` to select one profile exactly; pass ``compressed=True``
    for the ``(comp 0.1x)`` variant. A missing combination refuses with
    :class:`VlaPerfMissingRow`.
    """
    wanted = _as_int(resolution, "resolution")
    wanted_network = None if network is None else _as_text(network, "network")
    csv_path = _data_dir(data_dir) / _IMAGE_NETWORK_FILE
    image_rows: list[dict[str, Any]] = []
    for line_number, raw in _read_rows(csv_path, _IMAGE_COLUMNS):
        row = _coerce_row(
            raw,
            where=f"{csv_path}:{line_number}",
            text_columns=("network", "image_config"),
            int_columns=_IMAGE_INT_COLUMNS,
            float_columns=tuple(
                column for column in _IMAGE_COLUMNS
                if column not in {"network", "image_config",
                                  *_IMAGE_INT_COLUMNS}),
        )
        if row["image_resolution"] != wanted:
            continue
        if _is_compressed(row["image_config"]) != bool(compressed):
            continue
        if wanted_network is not None and row["network"] != wanted_network:
            continue
        image_rows.append(row)
    if not image_rows:
        raise VlaPerfMissingRow(
            f"no image row for resolution={resolution}, "
            f"compressed={bool(compressed)}, network={network!r}")
    return image_rows


def _kv_config(return_data_config: str, where: str) -> tuple[int, str]:
    match = _KV_CONFIG_RE.search(return_data_config)
    if match is None:
        raise VlaPerfSchemaError(
            f"{where}.return_data_config does not end with "
            f"'<name> (seq=<n>, <dtype>)': {return_data_config!r}")
    return int(match.group(1)), match.group(2).casefold()


def kv_cache_row(
    seq_len: int,
    dtype: str,
    *,
    network: str | None = None,
    image_compressed: bool | None = None,
    data_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return bidirectional image + KV-cache rows for one sequence/dtype.

    Sequence length and dtype are embedded in the upstream
    ``return_data_config`` text (for example ``Pi0 (Gemma 2B) (seq=256,
    fp16)``); this function parses them instead of inventing columns. The
    vendored table only contains seq=256 and fp16, so any other request
    refuses with :class:`VlaPerfMissingRow`. ``image_compressed`` filters the
    upload side (``None`` keeps both raw and 0.1x rows).
    """
    wanted_seq = _as_int(seq_len, "seq_len")
    wanted_dtype = _as_text(dtype, "dtype").casefold()
    wanted_network = None if network is None else _as_text(network, "network")
    csv_path = _data_dir(data_dir) / _KV_CACHE_FILE
    kv_rows: list[dict[str, Any]] = []
    for line_number, raw in _read_rows(csv_path, _KV_COLUMNS):
        where = f"{csv_path}:{line_number}"
        row = _coerce_row(
            raw,
            where=where,
            text_columns=("network", "image_config", "return_data_type",
                          "return_data_config"),
            int_columns=_KV_INT_COLUMNS,
            float_columns=tuple(
                column for column in _KV_COLUMNS
                if column not in {"network", "image_config", "return_data_type",
                                  "return_data_config", *_KV_INT_COLUMNS}),
        )
        row_seq, row_dtype = _kv_config(row["return_data_config"], where)
        row["seq_len"] = row_seq
        row["dtype"] = row_dtype
        row["image_compressed"] = _is_compressed(row["image_config"])
        if row_seq != wanted_seq or row_dtype != wanted_dtype:
            continue
        if wanted_network is not None and row["network"] != wanted_network:
            continue
        if image_compressed is not None \
                and row["image_compressed"] != bool(image_compressed):
            continue
        kv_rows.append(row)
    if not kv_rows:
        raise VlaPerfMissingRow(
            f"no KV-cache row for seq_len={seq_len}, dtype={dtype!r}, "
            f"network={network!r}, image_compressed={image_compressed!r}")
    return kv_rows


def _readme_commit(data_dir: Path) -> str:
    readme = data_dir / _README_FILE
    if not readme.is_file():
        raise VlaPerfError(f"VLA-Perf provenance README is missing: {readme}")
    text = readme.read_text(encoding="utf-8")
    commits = sorted(set(_COMMIT_RE.findall(text)))
    if len(commits) != 1:
        raise VlaPerfSchemaError(
            f"{readme}: expected exactly one 40-hex pinned commit, "
            f"found {len(commits)}")
    return commits[0]


def summarize(repo_root: str | Path) -> dict[str, Any]:
    """Return a JSON-ready summary of the modeled Thor π0 rows.

    The summary carries provenance (pinned commit, retrieval date, license)
    and every Thor row with its stage breakdown. It is modeled data; the
    returned ``measured`` flag is always ``False``.
    """
    data_dir = _repo_data_dir(repo_root)
    readme_commit = _readme_commit(data_dir)
    if readme_commit != VLA_PERF_COMMIT:
        raise VlaPerfSchemaError(
            f"README pins {readme_commit}, module pins {VLA_PERF_COMMIT}")
    rows = thor_rows(load_pi0_rows(data_dir / _PI0_E2E_FILE))
    summaries = [
        {
            "batch_size": row["batch_size"],
            "seq_len": row["model.seq_len_inference_prefill"],
            "num_chips": row["hardware.num_chips"],
            "stages": stage_summary(row),
        }
        for row in sorted(
            rows,
            key=lambda item: (
                item["batch_size"],
                item["model.seq_len_inference_prefill"],
                item["hardware.num_chips"],
            ))
    ]
    summary = {
        "workload_id": PI0_THOR_WORKLOAD_ID,
        "display_name": "π0 · modeled Thor roofline",
        "kind": "modeled-roofline",
        "measured": False,
        "model": {
            "name": "pi0",
            "parameters_b": 3.3,
            "denoising_steps": 10,
            "action_horizon": 50,
            "action_dim": 32,
            "image_shape": [224, 224],
        },
        "hardware": {
            "name": "Jetson AGX Thor",
            "source_name": "Jetson_AGX_Thor",
            "chips": 1,
        },
        "provenance": {
            "upstream": VLA_PERF_UPSTREAM,
            "commit": VLA_PERF_COMMIT,
            "commit_date": VLA_PERF_COMMIT_DATE,
            "retrieved": VLA_PERF_RETRIEVED,
            "license": VLA_PERF_LICENSE,
            "source_file": "vla-perf/perf_results/" + _PI0_E2E_FILE,
            "modeling": "VLA-Perf analytical roofline (GenZ)",
            "disclaimer": (
                "Modeled roofline estimates, not measurements. Fabric shape "
                "and traffic profiles in the template are authored."),
        },
        "rows": summaries,
    }
    # Round-trip through JSON so callers cannot receive NaN or tuples.
    return json.loads(json.dumps(summary, allow_nan=False))


__all__ = [
    "PI0_THOR_WORKLOAD_ID",
    "VLA_PERF_COMMIT",
    "VLA_PERF_COMMIT_DATE",
    "VLA_PERF_DATA_REL",
    "VLA_PERF_LICENSE",
    "VLA_PERF_RETRIEVED",
    "VLA_PERF_UPSTREAM",
    "VlaPerfError",
    "VlaPerfMissingColumn",
    "VlaPerfMissingRow",
    "VlaPerfSchemaError",
    "kv_cache_row",
    "load_pi0_rows",
    "network_image_row",
    "stage_summary",
    "summarize",
    "thor_rows",
]

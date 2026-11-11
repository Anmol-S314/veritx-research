"""Deployment builder catalogs and in-memory intent preview.

Rationale: docs/design/reviews/deployment-builder.md.

The builder is a thin layer over ``deployment_intent``. It lists the tracked
model configs and hardware facts a user may choose, then maps one chosen
deployment to a schema-4 request without writing temporary files, inventing
hardware facts or accepting a trace path outside the tracked serving catalog.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from veritx_dse.application.deployment_intent import (
    SCHEMA,
    MappingIssue,
    describe_model,
    map_deployment_document,
)
from veritx_dse.application.hardware_profiles import hardware_profile_catalog
from veritx_dse.core.paths import REPO

CONTRACT_VERSION = 1

MODEL_CONFIG_DIR = Path("third_party/llmservingsim/configs/model")
TRACKED_MODEL_DIR = Path("tracks/t3-topology/data/models")
MODEL_CONFIG_DIRS = (MODEL_CONFIG_DIR, TRACKED_MODEL_DIR)
HARDWARE_DATA_DIR = Path("tracks/t3-topology/data/hardware")
PROFILER_DIR = Path("third_party/llmservingsim/profiler/perf")
SERVING_TRACE_DIR = Path("third_party/llmservingsim/workloads")

_TIMING_MEASURED = "MEASURED"
_TIMING_DATASHEET = "DATASHEET"
_TIMING_UNKNOWN = "UNKNOWN"
_TIMING_PRIORITY = {
    _TIMING_MEASURED: 2,
    _TIMING_DATASHEET: 1,
    _TIMING_UNKNOWN: 0,
}

def _root(repo_root: str | Path | None) -> Path:
    return Path(repo_root) if repo_root is not None else Path(REPO)

def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()

def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def _provenance_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "; ".join(str(part) for part in value)
    return ""

def _bundle_exists(root: Path, hardware_id: str) -> bool:
    return (root / PROFILER_DIR / hardware_id).is_dir()

def deployment_model_catalog(
        repo_root: str | Path | None = None) -> dict[str, Any]:
    """Tracked LLMServingSim and overlay model configs, deterministically sorted.

    Both ``third_party/llmservingsim/configs/model`` and the track-local
    ``tracks/t3-topology/data/models`` overlay are scanned. ``model_name`` is
    the path under its model base without ``.json``; identical resolved files
    are listed once. Configs whose geometry cannot be derived are skipped:
    they cannot produce an intent, so listing them would offer a dead choice.
    """
    root = _root(repo_root)
    models: list[dict[str, Any]] = []

    seen: set[Path] = set()
    for relative_base in MODEL_CONFIG_DIRS:
        base = root / relative_base
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.json")):
            if path.name.lower().startswith("readme"):
                continue
            # The tracked tree uses symlinks as convenience aliases (for
            # example Qwen3-30B-A3B-Instruct-2507.json -> Qwen/...); one
            # resolved config must not appear twice in the picker.
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                data = path.read_bytes()
                document = json.loads(data.decode("utf-8"))
                view = describe_model(document)
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            models.append({
                "model_name": (
                    path.relative_to(base).with_suffix("").as_posix()),
                "source": path.relative_to(root).as_posix(),
                "digest": _digest(data),
                **view,
            })

    models.sort(key=lambda entry: (entry["model_name"], entry["source"]))
    return {"contract_version": CONTRACT_VERSION, "models": models}

def _profile_hardware_entry(
        profile: Mapping[str, Any], root: Path) -> dict[str, Any]:
    hardware_id = str(profile.get("hardware_id") or "")
    measured = _bundle_exists(root, hardware_id)
    return {
        "hardware_id": hardware_id,
        "display_name": str(
            profile.get("display_name") or profile.get("vendor_model")
            or hardware_id),
        "memory_bytes": profile.get("memory_capacity_bytes"),
        "memory_bandwidth_bytes_per_s": profile.get(
            "memory_bandwidth_bytes_per_s"),
        "link_bandwidth_bytes_per_s": profile.get(
            "link_bandwidth_bytes_per_s"),
        "provenance": _provenance_text(profile.get("provenance")),
        "timing": _TIMING_MEASURED if measured else _TIMING_UNKNOWN,
        "serving_profile": True,
    }

def _declared_hardware_entry(
        document: Mapping[str, Any], root: Path) -> dict[str, Any] | None:
    hardware_id = document.get("hardware_id")
    if not isinstance(hardware_id, str) or not hardware_id.strip():
        return None
    timing = document.get("timing")
    if not isinstance(timing, str) or timing.upper() not in _TIMING_PRIORITY:
        timing = _TIMING_UNKNOWN
    else:
        timing = timing.upper()
    # A declared entry may claim MEASURED only when a profiler bundle exists.
    if timing == _TIMING_MEASURED and not _bundle_exists(root, hardware_id):
        timing = _TIMING_UNKNOWN
    return {
        "hardware_id": hardware_id,
        "display_name": str(
            document.get("display_name") or hardware_id),
        "memory_bytes": document.get("memory_bytes"),
        "memory_bandwidth_bytes_per_s": document.get(
            "memory_bandwidth_bytes_per_s"),
        "link_bandwidth_bytes_per_s": document.get(
            "link_bandwidth_bytes_per_s"),
        "provenance": _provenance_text(document.get("provenance")),
        "timing": timing,
        "serving_profile": bool(document.get("serving_profile", False)),
    }

def _declared_hardware(root: Path) -> list[dict[str, Any]]:
    base = root / HARDWARE_DATA_DIR
    entries: list[dict[str, Any]] = []
    if not base.is_dir():
        return entries
    for path in sorted(base.glob("*.json")):
        try:
            document = _read_json(path)
        except (OSError, ValueError):
            continue
        documents = document if isinstance(document, list) else [document]
        for item in documents:
            if not isinstance(item, Mapping):
                continue
            entry = _declared_hardware_entry(item, root)
            if entry is not None:
                entries.append(entry)
    return entries

def _merge_hardware(
        entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate by hardware_id; a MEASURED claim wins over declared facts."""
    best: dict[str, dict[str, Any]] = {}
    for entry in entries:
        hardware_id = entry["hardware_id"]
        current = best.get(hardware_id)
        if current is None or (
                _TIMING_PRIORITY[entry["timing"]]
                > _TIMING_PRIORITY[current["timing"]]):
            best[hardware_id] = entry
    return sorted(best.values(), key=lambda entry: entry["hardware_id"])

def deployment_hardware_catalog(
        repo_root: str | Path | None = None) -> dict[str, Any]:
    """Tracked serving hardware profiles plus declared datasheet entries.

    ``timing`` is MEASURED only when a profiler bundle directory exists.
    ``serving_profile`` records whether the tracked serving profile catalog
    knows the hardware (B200 is declared, not profiled).
    """
    root = _root(repo_root)
    profiles = [
        _profile_hardware_entry(profile, root)
        for profile in hardware_profile_catalog().get("profiles", ())
        if isinstance(profile, Mapping) and profile.get("hardware_id")
    ]
    entries = _merge_hardware([*profiles, *_declared_hardware(root)])
    return {"contract_version": CONTRACT_VERSION, "hardware": entries}

def _issue(code: str, message: str,
           path: str | None = None) -> dict[str, Any]:
    return asdict(MappingIssue(code=code, message=message, path=path))

def _refusal_report(
    issues: list[dict[str, Any]],
    *,
    cluster_source: str,
    model_source: str | None,
    trace_source: str | None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "REFUSED",
        "sources": {
            "cluster": {"path": cluster_source, "sha256": None},
            "model": {"path": model_source, "sha256": None},
            "trace": {"path": trace_source, "sha256": None},
        },
        "deployment": None,
        "model": None,
        "request": None,
        "derived": None,
        "assumptions": [],
        "issues": issues,
    }

def _refused(
    issues: list[dict[str, Any]],
    *,
    cluster_source: str,
    model_source: str | None,
    trace_source: str | None,
) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "REFUSED",
        "issues": issues,
        "report": _refusal_report(
            issues, cluster_source=cluster_source,
            model_source=model_source, trace_source=trace_source),
        "request": None,
        "compile": None,
    }

def _trace_rows(path: Path) -> tuple[list[dict[str, Any]] | None, str | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"trace cannot be read: {path}: {exc}"
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            return None, (
                f"trace row {line_number} is not valid JSON: {exc}")
        if not isinstance(row, dict):
            return None, f"trace row {line_number} must be a JSON object"
        rows.append(row)
    return rows, None

def _trace_catalog(
        trace_entries: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    catalog: dict[str, Mapping[str, Any]] = {}
    for entry in trace_entries:
        if not isinstance(entry, Mapping):
            continue
        source = entry.get("source") or entry.get("trace_source")
        if isinstance(source, str) and source:
            catalog.setdefault(source, entry)
    return catalog

def _build_cluster(body: Mapping[str, Any]) -> dict[str, Any]:
    """The LLMServingSim cluster document the preview maps, in memory."""
    instance: dict[str, Any] = {
        "model_name": body["model_name"],
        "hardware": body["hardware"],
        "tp_size": int(body["tp_size"]),
        "pp_size": int(body.get("pp_size", 1)),
        "pd_type": None,
    }
    for key in ("ep_size", "max_num_seqs", "max_num_batched_tokens"):
        if body.get(key) is not None:
            instance[key] = int(body[key])
    dp_instances = int(body.get("dp_instances", 1))
    instances = [dict(instance) for _ in range(dp_instances)]
    if dp_instances > 1:
        for replica in instances:
            replica["dp_group"] = "builder-dp"
    return {
        "num_nodes": 1,
        "nodes": [{
            "num_instances": dp_instances,
            "instances": instances,
        }],
    }

def preview_deployment_intent(
    *,
    body: Mapping[str, Any],
    repo_root: str | Path | None = None,
    trace_entries: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Resolve catalog selections, map the deployment, and compile the intent.

    ``trace_entries`` are the tracked serving trace catalog entries (from
    ``ProductService.serving_config_catalog`` or
    ``serving_experiment_catalog``); a trace string not present there is
    refused, never read from an arbitrary path.
    """
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.product.service import parse_request_doc

    root = _root(repo_root)
    cluster_source = "in-memory:deployment-intent/preview"
    model_name = body.get("model_name")
    hardware_id = body.get("hardware")
    trace_source = body.get("trace")

    models = {
        entry["model_name"]: entry
        for entry in deployment_model_catalog(root)["models"]}
    hardware = {
        entry["hardware_id"]: entry
        for entry in deployment_hardware_catalog(root)["hardware"]}
    traces = _trace_catalog(trace_entries)

    if model_name not in models:
        return _refused(
            [_issue("MODEL_UNKNOWN",
                    f"model {model_name!r} is not in the deployment model "
                    "catalog")],
            cluster_source=cluster_source, model_source=model_name,
            trace_source=trace_source)
    model_entry = models[model_name]

    if hardware_id not in hardware:
        return _refused(
            [_issue("HARDWARE_UNKNOWN",
                    f"hardware {hardware_id!r} is not in the deployment "
                    "hardware catalog")],
            cluster_source=cluster_source, model_source=model_entry["source"],
            trace_source=trace_source)

    if trace_source not in traces:
        return _refused(
            [_issue("TRACE_UNKNOWN",
                    f"trace {trace_source!r} is not in the tracked serving "
                    "trace catalog; arbitrary paths are not accepted")],
            cluster_source=cluster_source, model_source=model_entry["source"],
            trace_source=trace_source)

    model_path = (root / model_entry["source"]).resolve()
    model_bases = [
        (root / relative_base).resolve()
        for relative_base in MODEL_CONFIG_DIRS]
    if not any(model_path.is_relative_to(base) for base in model_bases):
        return _refused(
            [_issue("MODEL_UNKNOWN",
                    f"model source {model_entry['source']!r} escapes the "
                    "tracked model config directories")],
            cluster_source=cluster_source, model_source=model_entry["source"],
            trace_source=trace_source)
    try:
        model_bytes = model_path.read_bytes()
        model_doc = json.loads(model_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return _refused(
            [_issue("MODEL_INVALID",
                    f"model config cannot be read: {model_entry['source']}: "
                    f"{exc}", model_entry["source"])],
            cluster_source=cluster_source, model_source=model_entry["source"],
            trace_source=trace_source)

    trace_path = (root / trace_source).resolve()
    trace_base = (root / SERVING_TRACE_DIR).resolve()
    if not trace_path.is_relative_to(trace_base):
        return _refused(
            [_issue("TRACE_UNKNOWN",
                    f"trace {trace_source!r} escapes the tracked serving "
                    "trace directory")],
            cluster_source=cluster_source, model_source=model_entry["source"],
            trace_source=trace_source)
    rows, trace_error = _trace_rows(trace_path)
    if trace_error is not None or rows is None:
        return _refused(
            [_issue("TRACE_INVALID", trace_error or "trace is unreadable",
                    trace_source)],
            cluster_source=cluster_source, model_source=model_entry["source"],
            trace_source=trace_source)

    try:
        trace_bytes = trace_path.read_bytes()
        model_digest = hashlib.sha256(model_bytes).hexdigest()
        trace_digest = hashlib.sha256(trace_bytes).hexdigest()
    except OSError as exc:
        return _refused(
            [_issue("TRACE_INVALID",
                    f"trace cannot be read: {trace_source}: {exc}",
                    trace_source)],
            cluster_source=cluster_source, model_source=model_entry["source"],
            trace_source=trace_source)

    cluster = _build_cluster(body)
    cluster_digest = hashlib.sha256(
        json.dumps(cluster, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")).hexdigest()
    mapping = map_deployment_document(
        cluster=cluster,
        model=model_doc,
        trace_rows=rows,
        cluster_source=cluster_source,
        model_source=model_entry["source"],
        trace_source=trace_source,
        num_reqs=body.get("num_reqs"),
        dtype_bytes=model_entry["geometry"]["dtype_bytes"],
        link_width_bits=int(body.get("link_width_bits", 128)),
        hbm_controllers_per_rank=int(
            body.get("hbm_controllers_per_rank", 0)),
        model_name=model_name,
        source_digests={
            "cluster": cluster_digest,
            "model": model_digest,
            "trace": trace_digest,
        },
    )
    if mapping.status != "OK":
        return {
            "contract_version": CONTRACT_VERSION,
            "status": "REFUSED",
            "issues": list(mapping.report.get("issues") or ()),
            "report": mapping.report,
            "request": None,
            "compile": None,
        }

    topology = body.get("topology")
    if not isinstance(topology, dict):
        issues = [_issue("REQUEST_INVALID",
                         "topology must be a supplied JSON object")]
        report = dict(mapping.report)
        report["status"] = "REFUSED"
        report["issues"] = issues
        return {
            "contract_version": CONTRACT_VERSION,
            "status": "REFUSED",
            "issues": issues,
            "report": report,
            "request": None,
            "compile": None,
        }

    request_doc = mapping.to_request(topology=topology)
    try:
        request = parse_request_doc(request_doc)
    except Exception as exc:  # noqa: BLE001 - typed refusal below
        issues = [_issue("REQUEST_INVALID", str(exc))]
        report = dict(mapping.report)
        report["status"] = "REFUSED"
        report["issues"] = issues
        return {
            "contract_version": CONTRACT_VERSION,
            "status": "REFUSED",
            "issues": issues,
            "report": report,
            "request": None,
            "compile": None,
        }

    try:
        compilation = FabricCompiler().compile(request)
        compile_view = {
            "status": compilation.status,
            "error": compilation.error,
        }
    except Exception as exc:  # noqa: BLE001 - compile verdict, not a crash
        compile_view = {"status": "ERROR", "error": str(exc)}

    return {
        "contract_version": CONTRACT_VERSION,
        "status": mapping.status,
        "issues": list(mapping.report.get("issues") or ()),
        "report": mapping.report,
        "request": request_doc,
        "compile": compile_view,
    }

__all__ = [
    "CONTRACT_VERSION",
    "deployment_hardware_catalog",
    "deployment_model_catalog",
    "preview_deployment_intent",
]

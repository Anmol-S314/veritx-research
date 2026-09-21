"""serve.py — run-level canonicalization (Phase 9 §14/§17).

Bridges live serving runs and the canonical artifact: after a run, every
saved trace under the run-owned inputs root is canonicalized into
``<run>/workload/<name>.workload.json`` plus a deterministic
``workload/index.json``. The index carries the canonical
``artifact_hash`` per workload; comparison fingerprints consume it
(workload_certified=True) instead of hashing fixture identity.

Trace layout (production: LLMServingSim graph_generator):
    <inputs_root>/trace/<hardware>/<model>/instance<i>_batch<b>.txt
Trace file shape (trace_generator._write_trace):
    line 1  header:  "<TYPE>\t\tmodel_parallel_NPU_group: <n>[ extra]"
    line 2  count:   <number of rows>
    lines 3+ rows:   11-field layer rows / 1-field marker rows

Fail-closed: an unparseable trace is a WorkloadError naming the file —
never a warn-and-skip (a workload whose semantics cannot even be read
must not silently produce an index without it).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .canonical import (
    Parallelism,
    WorkloadError,
    WorkloadArtifact,
    artifact_from_trace_rows,
)


def _parse_trace_text(text: str, *, source: str) -> tuple[str, list]:
    """Parse a saved trace file into (header_line, rows).

    Handles both on-disk shapes seen in production (verified against
    real saved traces from prior serving runs):
      * the convert_rows materialization: header, count, ``# layer
        table`` comment, rows
      * the _write_trace format: header, count, column-name row
        (``Layername ...``), rows

    Layer names carry their row index on disk (``embedding_0``); the
    index is positional and stripped here, mirroring the in-memory rows
    the converter consumes. Marker rows (EXPERT/PIM) arrive as their
    token sequence and are re-joined into the single-field tuple shape
    artifact_from_trace_rows parses.
    """
    lines = text.splitlines()
    if len(lines) < 2:
        raise WorkloadError(
            f"{source}: trace file too short — expected header + count "
            "+ rows")
    header_line = lines[0]
    try:
        count = int(lines[1].strip())
    except ValueError:
        raise WorkloadError(
            f"{source}: row-count line {lines[1]!r} is not an integer")
    raw = []
    for ln in lines[2:]:
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        toks = s.split()
        if toks[0] == "Layername":
            continue  # column-name row written by _write_trace
        raw.append(toks)
    if len(raw) != count:
        raise WorkloadError(
            f"{source}: header declares {count} rows, file has {len(raw)} "
            "— refusing to canonicalize a partial/unknown trace")
    norm = []
    for toks in raw:
        if len(toks) == _LAYER_FIELDS:
            name = toks[0].rsplit("_", 1)[0] if "_" in toks[0] else toks[0]
            norm.append((name, *toks[1:]))
        elif toks[0] in ("EXPERT", "PIM"):
            norm.append((" ".join(toks),))
        else:
            raise WorkloadError(
                f"{source}: row has {len(toks)} fields; expected 11 "
                f"(layer) or an EXPERT/PIM marker: {' '.join(toks)!r}")
    return header_line, norm


_LAYER_FIELDS = 11


def _parallelism_from_cluster(cluster: dict[str, Any], *,
                              source: str) -> Parallelism:
    """Derive the artifact's parallelism block from the cluster config.

    Uses the first instance's model-parallel degrees (tp/ep/pp; dp from
    the enclosing node's instance count). The audit records that these
    are exactly the values the generator consumes (tp_size, ep_size,
    pp_size); dp grouping rides instance placement, not a separate
    degree field.
    """
    nodes = cluster.get("nodes") or []
    first = None
    for nd in nodes:
        for inst in (nd.get("instances") or []):
            first = inst
            break
        if first is not None:
            break
    if first is None:
        raise WorkloadError(
            f"{source}: cluster config declares no instances — parallelism "
            "cannot be derived (fail-closed)")
    n_instances = sum(len(nd.get("instances") or []) for nd in nodes)

    def _int(inst_key: str, default: int) -> int:
        v = first.get(inst_key, default)
        try:
            return int(v)
        except (TypeError, ValueError):
            raise WorkloadError(
                f"{source}: cluster field {inst_key}={v!r} is not an int")

    return Parallelism(
        tp=_int("tp_size", 1),
        ep=_int("ep_size", 1),
        pp=_int("pp_size", 1),
        dp=max(n_instances, 1),
    )


def canonicalize_run_workload(run_root: Path,
                              cluster_path: Path) -> dict[str, Any]:
    """Canonicalize every saved trace of a run into workload artifacts.

    Writes <run_root>/workload/<name>.workload.json (one per trace) and
    <run_root>/workload/index.json. Returns the index. Deterministic:
    identical inputs produce byte-identical files (sorted keys, no
    timestamps).

    M3: every trace ALSO yields <name>.workloadgraph.json — the
    canonical WorkloadGraph built directly from the parsed rows (never
    via the legacy authority), with its workload_id in the index. New
    consumers read the graph; the legacy artifact files stay byte-
    identical for audit continuity.
    """
    from veritx_dse.model.parallelism import ParallelismArtifact
    from veritx_dse.workload.migration import workload_graph_from_trace_rows
    run_root = Path(run_root)
    trace_root = run_root / "inputs" / "trace"
    if not trace_root.is_dir():
        raise WorkloadError(
            f"no trace directory under {run_root} — the run must save "
            "trace text (--save-trace-text) for workload canonicalization")
    traces = sorted(p for p in trace_root.rglob("*.txt")
                    if p.name != "event_handler.txt")
    if not traces:
        raise WorkloadError(
            f"no trace files under {trace_root} (event_handler excluded) "
            "— nothing to canonicalize")
    try:
        cluster = json.loads(Path(cluster_path).read_text())
    except (OSError, ValueError) as e:
        raise WorkloadError(
            f"cluster config {cluster_path} unreadable: {e}")
    parallelism = _parallelism_from_cluster(
        cluster, source=str(cluster_path))
    # participant count: per-instance NPUs (num_npus) of the first
    # instance — the rank space the trace's collectives address
    num_participants = _int_from_cluster(cluster, "num_npus")

    entries = []
    workdir = run_root / "workload"
    workdir.mkdir(parents=True, exist_ok=True)
    for tp in traces:
        rel = tp.relative_to(trace_root)
        name = "_".join(rel.with_suffix("").parts)
        header_line, rows = _parse_trace_text(
            tp.read_text(), source=str(rel))
        if "pp_stage_boundaries" in header_line:
            # keep the ruling visible at run level too
            raise WorkloadError(
                f"{rel}: pp_stage_boundaries present — PP-partitioned "
                "traces cannot be canonicalized without semantic loss "
                "(Phase 1 T2, fail-closed)")
        art = artifact_from_trace_rows(
            rows, workload_id=name, parallelism=parallelism,
            num_participants=num_participants)
        path = workdir / f"{name}.workload.json"
        path.write_text(json.dumps(art.serialize(), indent=2,
                                   sort_keys=True) + "\n")
        graph = workload_graph_from_trace_rows(
            rows,
            parallelism=ParallelismArtifact(
                tp=parallelism.tp, pp=parallelism.pp, ep=parallelism.ep,
                dp=parallelism.dp),
            participant_count=num_participants,
            provenance={"source_format": "llmservingsim-trace-rows-v1",
                        "trace": str(rel)})
        graph_path = workdir / f"{name}.workloadgraph.json"
        graph_path.write_text(json.dumps(graph.to_dict(), indent=2,
                                         sort_keys=True) + "\n")
        entries.append({
            "name": name,
            "trace": str(rel),
            "artifact_hash": art.artifact_hash,
            "file": f"{name}.workload.json",
            "workload_graph_id": graph.workload_id(),
            "workloadgraph_file": f"{name}.workloadgraph.json",
            "parallelism": parallelism.to_dict(),
            "num_participants": num_participants,
            "comm_bytes_total": art.comm_bytes_total(),
            "op_count": len(art.ops),
        })
    index = {
        "schema_version": 1,
        "source_kind": "llmservingsim",
        "cluster_sha256": hashlib.sha256(
            Path(cluster_path).read_bytes()).hexdigest(),
        "artifacts": entries,
    }
    (workdir / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n")
    return index


def workload_identity(index: dict[str, Any]) -> str:
    """The run's workload identity from its canonical index.

    One artifact: its content hash IS the identity. Several: a digest
    over the sorted hash set (composite identity). Shared by the
    serving slice (run provenance) and the comparison fingerprint —
    one implementation, so the two can never drift.
    """
    hashes = sorted(a["artifact_hash"] for a in index.get("artifacts", []))
    if not hashes:
        raise WorkloadError(
            "workload index lists no artifacts — identity undefined "
            "(fail-closed)")
    if len(hashes) == 1:
        return hashes[0]
    return "sha256:" + hashlib.sha256(
        json.dumps(hashes, sort_keys=True).encode()).hexdigest()


def workload_graph_identity(index: dict[str, Any]) -> str:
    """The run's canonical-graph identity (M3).

    Same composition rule as workload_identity, over the per-trace
    workload_graph_id values. Lets comparison fingerprints consume
    graph identity without re-deriving it per trace.
    """
    hashes = sorted(a["workload_graph_id"]
                    for a in index.get("artifacts", []))
    if not hashes:
        raise WorkloadError(
            "workload index lists no workload graphs — identity "
            "undefined (fail-closed)")
    if len(hashes) == 1:
        return hashes[0]
    return "sha256:" + hashlib.sha256(
        json.dumps(hashes, sort_keys=True).encode()).hexdigest()


def _int_from_cluster(cluster: dict[str, Any], key: str) -> int:
    for nd in cluster.get("nodes") or []:
        for inst in (nd.get("instances") or []):
            if key in inst:
                v = inst[key]
                try:
                    return int(v)
                except (TypeError, ValueError):
                    break
    raise WorkloadError(
        f"cluster config lacks {key!r} on every instance — participant "
        "count cannot be derived (fail-closed)")

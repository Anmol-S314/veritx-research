"""Evidence-backed inventory and safe read-only access for research RTL.

Research artifacts are independent of the product's generated preview. Catalog
reads inspect bounded metadata only; source contents are opened only for a
named download. Historical report facts are retained as unverified snapshots.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any, Iterator

# These twelve IDs are the required evaluation set. DragonflyNew is optional;
# KNCube is a separately reported non-target.
_ROWS = (
    ("mesh8x8", "Mesh 8x8", "mesh", "CandidateNoCTop.v"),
    ("torus8x8", "Torus 8x8", "torus", "CandidateNoCTop.v"),
    ("cmesh", "Concentrated mesh", "concentrated_mesh", "CandidateNoCTop.v"),
    ("ring", "Ring", "ring_native", "CandidateNoCTop.v"),
    ("gec_mecs", "GEC MECS", "gec_mecs", "CandidateNoCTop.v"),
    ("fly64", "Fly64", "fly_native", "CandidateNoCTop.v"),
    ("qtree", "QTree", "qtree_native", "CandidateNoCTop.v"),
    ("tree4", "Tree4", "tree4_native", "CandidateNoCTop.v"),
    ("flatfly", "Flatfly", "flatfly", "CandidateNoCTop.v"),
    ("srota8x8", "SROTA 8x8", "srota", "CandidateNoCTop.v"),
    ("gec_hybrid", "GEC Hybrid", "gec_hybrid", "CandidateNoCTop.v"),
    ("fattree", "Fattree", "fat_tree", "CandidateNoCTop.v"),
    ("dragonflynew", "DragonflyNew", "dragonfly", "CandidateNoCTop.v"),
    ("kncube", "KNCube", None, None),
)
_REQUIRED = frozenset(row[0] for row in _ROWS[:12])
_FAMILY_TO_ID = {
    "mesh": "mesh8x8", "torus": "torus8x8", "concentrated_mesh": "cmesh",
    "ring_native": "ring", "ring": "ring", "gec_mecs": "gec_mecs",
    "gec_multidrop": "gec_mecs", "fly_native": "fly64", "fly": "fly64",
    "dragonfly": "dragonflynew", "dragonflynew": "dragonflynew",
    "qtree_native": "qtree", "qtree": "qtree", "tree4_native": "tree4",
    "tree4": "tree4", "flatfly": "flatfly", "flattened_butterfly": "flatfly",
    "srota": "srota8x8", "gec_hybrid": "gec_hybrid", "fat_tree": "fattree",
    "fattree": "fattree", "kncube": "kncube",
}
# Artifact names and paths are server-defined; never accept a client path.
_ARTIFACTS: dict[str, tuple[tuple[str, str], ...]] = {
    row[0]: ((row[3], f"{row[0]}/{row[3]}"),) if row[3] else () for row in _ROWS
}
for _id in ("mesh8x8", "torus8x8", "cmesh", "ring", "gec_mecs", "fly64", "qtree", "tree4", "flatfly", "srota8x8", "gec_hybrid", "fattree", "dragonflynew"):
    _ARTIFACTS[_id] += tuple((name, f"{_id}/{name}") for name in ("firrtl_black_box_resource_files.f", "plusarg_reader.v", "router_edges.tsv", "terminal_map.tsv"))
_ARTIFACTS["catalog"] = (("manifest.tsv", "manifest.tsv"), ("verification.json", "verification.json"))

# Actual local workspace is a known deployment root. Additional roots must be
# explicitly configured by the operator; browser input cannot modify roots.
_DEFAULT_ROOT = Path("/home/datavex/.cache/veritx-noc-lab/vla-native-execution/experiments/constellation_topology_rtl/generated")
_ID = re.compile(r"^[a-z0-9_]+$")


def _roots() -> tuple[Path, ...]:
    configured = os.environ.get("VERITX_RTL_RESEARCH_ROOTS", "")
    roots = [Path(value).expanduser() for value in configured.split(os.pathsep) if value]
    if not roots:
        roots.append(_DEFAULT_ROOT)
    valid = []
    for root in roots:
        try:
            resolved = root.resolve(strict=True)
            if resolved.is_dir() and resolved not in valid:
                valid.append(resolved)
        except OSError:
            continue
    return tuple(valid)


def _candidate(root: Path, relative: str) -> Path | None:
    # Relative paths are constants from _ARTIFACTS, still validate their shape.
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    candidate = root / rel
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        info = candidate.lstat()
        if not stat.S_ISREG(info.st_mode) or not resolved.is_file():
            return None
        return resolved
    except (OSError, ValueError):
        return None


def _version(info: os.stat_result) -> str:
    identity = f"{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}:{info.st_ctime_ns}"
    return hashlib.sha256(identity.encode("ascii")).hexdigest()


def _file_inventory(topology_id: str) -> list[dict[str, Any]]:
    files = []
    for name, relative in _ARTIFACTS[topology_id]:
        for root in _roots():
            path = _candidate(root, relative)
            if path is not None:
                try:
                    info = path.stat()
                except OSError:
                    continue
                version = _version(info)
                files.append({"artifact_id": topology_id, "name": name, "size_bytes": info.st_size,
                              "version": version,
                              "download_url": f"/catalog/rtl-prototypes/{topology_id}/artifacts/{name}?version={version}"})
                break
    return files


def list_prototypes() -> list[dict[str, Any]]:
    rows = []
    for topology_id, label, family, top_name in _ROWS:
        files = _file_inventory(topology_id)
        present = any(item["name"] == top_name for item in files) if top_name else False
        rows.append({
            "topology_id": topology_id, "label": label, "catalog_family": family,
            "scope": "RESEARCH_VERILOG", "final_implementation": False,
            "required": topology_id in _REQUIRED,
            "verilog_status": "PRESENT" if present else "MISSING",
            "verilog_file": top_name if present else None,
            "file_presence": "PRESENT" if present else "UNKNOWN",
            "generation_completeness": "UNKNOWN", "proof_status": "UNVERIFIED",
            "lint_status": "NOT_RUN", "simulation_status": "NOT_RUN",
            "source_reproduction_status": "UNKNOWN", "qualification_status": "NOT_QUALIFIED",
            "historical_snapshot": {"reported_proof": "PASS (historical report; not verified against current source)"
                                    if topology_id not in ("kncube",) else "No historical sealed proof reported",
                                    "reported_verilog": "Previously reported emitted; current filesystem presence is checked independently"},
            "lineage": "UNKNOWN", "artifacts": files,
            "detail": "Current file presence is not evidence of complete generation, proof, lint, simulation, reproduction, or qualification.",
        })
    return rows


def catalog_artifacts() -> list[dict[str, Any]]:
    """Bounded identity inventory for generated evidence files."""
    return _file_inventory("catalog")


def prototype_for_family(family: str | None, kind: str | None = None) -> dict[str, Any] | None:
    key = (kind or family or "").strip().lower()
    if key == "gec":
        key = (family or "").strip().lower()
    topology_id = _FAMILY_TO_ID.get(key) or _FAMILY_TO_ID.get((family or "").strip().lower())
    return next((row for row in list_prototypes() if row["topology_id"] == topology_id), None)


def counts_for_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    required = [row for row in rows if row["required"]]
    return {"required_total": len(_REQUIRED), "required_present": sum(row["file_presence"] == "PRESENT" for row in required),
            "required_missing_or_unknown": sum(row["file_presence"] != "PRESENT" for row in required),
            "optional_total": sum(not row["required"] and row["topology_id"] != "kncube" for row in rows),
            "non_target_total": sum(row["topology_id"] == "kncube" for row in rows)}


def _open_artifact(topology_id: str, name: str, expected_version: str) -> tuple[int, int]:
    if (topology_id != "catalog" and not _ID.fullmatch(topology_id)) or topology_id not in _ARTIFACTS:
        raise KeyError("unknown prototype")
    if not isinstance(name, str) or "/" in name or "\\" in name or name in (".", ".."):
        raise KeyError("unknown artifact")
    relative = next((rel for allowed, rel in _ARTIFACTS[topology_id] if allowed == name), None)
    if relative is None:
        raise KeyError("unknown artifact")
    parts = Path(relative).parts
    for root in _roots():
        current = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=current)
                os.close(current)
                current = child
            fd = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=current)
        except (OSError, ValueError):
            os.close(current)
            continue
        os.close(current)
        info = os.fstat(fd)
        if stat.S_ISREG(info.st_mode) and _version(info) == expected_version:
            return fd, info.st_size
        os.close(fd)
    raise FileNotFoundError("artifact unavailable")


def stream_artifact(topology_id: str, name: str, version: str) -> tuple[Iterator[bytes], int]:
    # Every component is opened relative to a pinned directory descriptor. The
    # streamed descriptor is the one validated; no pathname is reopened.
    if not re.fullmatch(r"[a-f0-9]{64}", version):
        raise FileNotFoundError("artifact identity is missing or stale")
    fd, size = _open_artifact(topology_id, name, version)
    try:
        snapshot = tempfile.TemporaryFile(mode="w+b")
    except BaseException:
        os.close(fd)
        raise
    try:
        with os.fdopen(fd, "rb") as source:
            copied = 0
            while copied < size:
                data = os.read(source.fileno(), min(1024 * 1024, size - copied))
                if not data:
                    break
                snapshot.write(data)
                copied += len(data)
            if copied != size or _version(os.fstat(source.fileno())) != version:
                raise FileNotFoundError("artifact changed while taking download snapshot")
        snapshot.seek(0)
    except BaseException:
        snapshot.close()
        raise

    def chunks() -> Iterator[bytes]:
        with snapshot:
            while True:
                data = snapshot.read(1024 * 1024)
                if not data:
                    break
                yield data
    return chunks(), size

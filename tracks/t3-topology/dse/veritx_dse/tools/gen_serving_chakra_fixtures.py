#!/usr/bin/env python3
"""gen_serving_chakra_fixtures.py — deterministic serving Chakra fixtures (R1).

Rationale: docs/decisions/modules/tools.md
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

GENERATOR_VERSION = "veritx-serving-chakra/v1"

REPO_ROOT = Path(__file__).resolve().parents[5]
CHAKRA_ROOT = REPO_ROOT / "third_party" / "astra-sim" / "extern" / "graph_frontend" / "chakra"
FIXTURE_ROOT = (
    REPO_ROOT / "tracks" / "t3-topology" / "dse" / "tests" / "fixtures" / "serving_chakra"
)

CONVERTER_SOURCES = (
    CHAKRA_ROOT / "src" / "converter" / "llm_converter.py",
    CHAKRA_ROOT / "src" / "third_party" / "utils" / "protolib.py",
    CHAKRA_ROOT / "schema" / "protobuf" / "et_def.proto",
)

_COLUMNS = (
    "Layername",
    "comp_time",
    "input_loc",
    "input_size",
    "weight_loc",
    "weight_size",
    "output_loc",
    "output_size",
    "comm_type",
    "comm_size",
    "misc",
)
_WIDTHS = (30, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15)

def _header() -> str:
    return "".join(f"{c:<{w}}" for c, w in zip(_COLUMNS, _WIDTHS)) + "\n"

def _row(
    name: str,
    comp_ns: int,
    comm_type: str = "NONE",
    comm_size: int = 0,
) -> str:
    """One 11-column layer row. ``comp_ns`` is nanoseconds (converter -> us)."""
    return (
        f"{name:<30}{comp_ns:<15}{'LOCAL':<15}{0:<15}{'LOCAL':<15}{0:<15}"
        f"{'LOCAL':<15}{comm_size:<15}{comm_type:<15}{comm_size:<15}{'NONE':<15}\n"
    )

def _event_trace(alarm_ns: int) -> str:
    return "EVENT\n1\n" + _header() + _row(f"event_{alarm_ns}ns", alarm_ns)

def _colocated_trace(layer_rows: list[str], pp_group: int = 1) -> str:
    return (
        f"COLOCATED\t\tmodel_parallel_NPU_group: {pp_group}\n"
        + f"{len(layer_rows)}\n"
        + _header()
        + "".join(layer_rows)
    )

CASES: dict[str, dict[str, Any]] = {
    "event_handler": {
        "kind": "event",
        "num_npus": 2,
        "alarm_ns": 1000,
    },
    "dense_single": {
        "kind": "colocated",
        "num_npus": 1,
        "pp_group": 1,
        "layers": [
            ("embed", 800, "NONE", 0),
            ("attn", 1000, "NONE", 0),
            ("mlp", 2000, "NONE", 0),
        ],
    },
    "dense_tp2": {
        "kind": "colocated",
        "num_npus": 2,
        "pp_group": 1,
        "layers": [
            ("attn", 1000, "ALLREDUCE:1", 4096),
            ("mlp", 2000, "ALLREDUCE:1", 4096),
        ],
    },
    "dense_tp4": {
        "kind": "colocated",
        "num_npus": 4,
        "pp_group": 1,
        "layers": [
            ("attn", 1000, "ALLREDUCE:1", 4096),
            ("mlp", 2000, "ALLREDUCE:1", 4096),
        ],
    },
    "moe_ep": {
        "kind": "colocated",
        "num_npus": 2,
        "pp_group": 1,
        "layers": [
            ("attn", 1000, "NONE", 0),
            ("EXPERT", "0", "ALLGATHER:1", 4096),
            ("expert", 900, "NONE", 0),
            ("EXPERT", "1", "NONE", 0),
            ("EXPERT", "END", "REDUCESCATTER:1", 8192),
        ],
    },
}

def render_trace(case: dict[str, Any]) -> str:
    if case["kind"] == "event":
        return _event_trace(int(case["alarm_ns"]))
    rows: list[str] = []
    for layer in case["layers"]:
        if layer[0] == "EXPERT":
            rows.append(f"EXPERT {layer[1]} {layer[2]} {layer[3]}\n")
        else:
            name, comp_ns, comm_type, comm_size = layer
            rows.append(_row(name, comp_ns, comm_type, comm_size))
    return _colocated_trace(rows, int(case.get("pp_group", 1)))

def _load_converter():
    if str(CHAKRA_ROOT) not in sys.path:
        sys.path.insert(0, str(CHAKRA_ROOT))
    from chakra.src.converter.llm_converter import LLMConverter  # noqa: E402

    return LLMConverter

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def generate(root: Path = FIXTURE_ROOT) -> dict[str, Any]:
    """Generate every canonical case under ``root``. Returns the manifest."""
    LLMConverter = _load_converter()
    root.mkdir(parents=True, exist_ok=True)
    trace_dir = root / "traces"
    trace_dir.mkdir(exist_ok=True)

    files: dict[str, dict[str, Any]] = {}
    for name, case in sorted(CASES.items()):
        text = render_trace(case)
        trace_path = trace_dir / f"{name}.txt"
        trace_path.write_text(text)
        out_base = root / name / "llm"
        out_base.parent.mkdir(parents=True, exist_ok=True)
        LLMConverter(str(trace_path), str(out_base), int(case["num_npus"])).convert()
        for et in sorted(out_base.parent.glob("llm.*.et")):
            rel = str(et.relative_to(root))
            files[rel] = {"sha256": _sha256(et), "size": et.stat().st_size}

    sources = {
        str(p.relative_to(REPO_ROOT)): _sha256(p)
        for p in CONVERTER_SOURCES
        if p.exists()
    }
    manifest: dict[str, Any] = {
        "generator_version": GENERATOR_VERSION,
        "generator_source_sha256": {
            "veritx_dse/tools/gen_serving_chakra_fixtures.py": _sha256(Path(__file__)),
            **sources,
        },
        "canonical_inputs": {str(k): v for k, v in sorted(CASES.items())},
        "files": files,
    }
    canonical = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    manifest["manifest_id"] = hashlib.sha256(canonical.encode()).hexdigest()
    (root / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest

def main() -> int:
    manifest = generate()
    print(
        f"wrote {len(manifest['files'])} .et files to {FIXTURE_ROOT} "
        f"(manifest_id={manifest['manifest_id'][:16]})"
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

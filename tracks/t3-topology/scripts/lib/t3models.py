#!/usr/bin/env python3
"""t3models.py — model/workload registry for t3.

Extensibility seam for workloads: any sweep that takes MODEL=<key> resolves the
key through this registry, so **new models are data, not code**. Built-in
presets (llama7b …) are seeded on first use; users add their own via
`t3 model-add` (guided or CLI) or by dropping a JSON file here.

JSON schema (workloads/<name>.json):
  {
    "name": "llama7b_h100",            # required, [a-z0-9_]
    "model_name": "LLaMA-7B (H100)",   # display name
    "kind": "model",                   # "model" | "collective" | "external"
    "hidden_size": 4096,               # model kind: these 7 are the spec
    "ffn_size": 11008,
    "num_layers": 32,
    "seq_len": 2048,
    "batch_size": 2,
    "tp_degree": 4,
    "pp_degree": 4,
    "bytes_per_elem": 2,
    "msg_size_mb": 16.0,               # collective kind
    "notes": "optional free text",
    "builtin": false                   # set by the seeder, never user data
  }

kind="model" feeds ChakraTraceGenerator.build_model_trace via resolve_spec;
kind="collective" builds the collective microbenchmarks (all_reduce, …);
kind="external" points at an existing Chakra ET trace directory.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

# scripts/lib/t3models.py -> tracks/t3-topology
ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY_DIR = ROOT / "workloads"
REPO_ROOT = ROOT.parent.parent

# Canonical parallelism math lives in veritx_dse.model.presets
# (parallel_world_size); local fallback keeps standalone use working.
try:
    if str((ROOT / "dse").resolve()) not in sys.path:
        sys.path.insert(0, str(ROOT / "dse"))
    from veritx_dse.model.presets import parallel_world_size as _world_size
except Exception:
    def _world_size(tp, pp=1, ep=1, dp=1):  # type: ignore
        return int(tp) * int(pp) * int(ep) * int(dp)

# Keep in sync with generate_chakra_trace.MODEL_PRESETS (seeded on first use).
_BUILTIN_SEED = {
    "llama7b": {
        "model_name": "LLaMA-7B", "hidden_size": 4096, "ffn_size": 11008,
        "num_layers": 32, "seq_len": 2048, "batch_size": 2,
        "tp_degree": 4, "pp_degree": 4, "bytes_per_elem": 2,
    },
    "llama13b": {
        "model_name": "LLaMA-13B", "hidden_size": 5120, "ffn_size": 13824,
        "num_layers": 40, "seq_len": 2048, "batch_size": 2,
        "tp_degree": 4, "pp_degree": 4, "bytes_per_elem": 2,
    },
    "llama70b": {
        "model_name": "LLaMA-70B", "hidden_size": 8192, "ffn_size": 28672,
        "num_layers": 80, "seq_len": 2048, "batch_size": 2,
        "tp_degree": 8, "pp_degree": 8, "bytes_per_elem": 2,
    },
    "gpt3": {
        "model_name": "GPT-3-175B", "hidden_size": 12288, "ffn_size": 49152,
        "num_layers": 96, "seq_len": 2048, "batch_size": 2,
        "tp_degree": 8, "pp_degree": 8, "bytes_per_elem": 2,
    },
    "resnet50": {
        "model_name": "ResNet-50", "hidden_size": 2048, "ffn_size": 2048,
        "num_layers": 50, "seq_len": 224, "batch_size": 32,
        "tp_degree": 1, "pp_degree": 1, "bytes_per_elem": 4,
    },
}

_COLLECTIVES = ("all_reduce", "all_to_all", "reduce_scatter", "all_gather")

_COLLECTIVE_SEED = {
    name: {
        "model_name": name.upper(), "kind": "collective", "msg_size_mb": 16.0,
    }
    for name in _COLLECTIVES
}

# Full seed = model presets + collective microbenchmarks.
_BUILTIN_SEED.update(_COLLECTIVE_SEED)

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_MODEL_FIELDS = ("hidden_size", "ffn_size", "num_layers", "seq_len",
                 "batch_size", "tp_degree", "pp_degree")


class ModelError(ValueError):
    pass


def _ensure_registry() -> None:
    """Seed built-ins on first use so the registry is never empty."""
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    for name, spec in _BUILTIN_SEED.items():
        p = REGISTRY_DIR / f"{name}.json"
        if p.exists():
            continue
        data = dict(spec)
        data.setdefault("kind", "model")
        data.update({"name": name, "builtin": True})
        p.write_text(json.dumps(data, indent=2) + "\n")


def validate(data: dict, *, for_update: bool = False) -> dict:
    """Validate one registry record; returns normalized copy."""
    if not isinstance(data, dict):
        raise ModelError("registry entry must be a JSON object")
    name = data.get("name")
    if not name or not isinstance(name, str) or not _NAME_RE.match(name):
        raise ModelError(
            f"bad name {name!r}: use [a-z0-9_] lowercase, max 64 chars")
    kind = data.get("kind", "model")
    if kind not in ("model", "collective", "external"):
        raise ModelError(f"bad kind {kind!r}: model | collective | external")
    out = {"name": name, "kind": kind}
    if kind == "model":
        missing = [f for f in _MODEL_FIELDS if f not in data]
        if missing and not for_update:
            raise ModelError(f"model {name!r} missing fields: {', '.join(missing)}")
        bounds = {"hidden_size": 131072, "ffn_size": 524288, "num_layers": 1024,
                  "seq_len": 4194304, "batch_size": 65536,
                  "tp_degree": 4096, "pp_degree": 4096}
        ints = {}
        for f in _MODEL_FIELDS:
            v = data.get(f)
            if v is None:
                continue
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                raise ModelError(f"{f} must be a positive integer, got {v!r}")
            if v > bounds.get(f, 10 ** 9):
                raise ModelError(f"{f}={v} looks like a typo (max {bounds.get(f, 10**9)})")
            ints[f] = v
        out.update(ints)
        if {"num_heads-related"}:  # placeholder no-op keeps schema open
            pass
        if out.get("tp_degree") and out.get("pp_degree") and \
                _world_size(out["tp_degree"], out["pp_degree"],
                            out.get("ep_degree", 1), out.get("dp_degree", 1)) > 4096:
            raise ModelError("tp_degree * pp_degree > 4096 — looks like a typo")
        try:
            out["bytes_per_elem"] = int(data.get("bytes_per_elem", 2))
        except (TypeError, ValueError):
            raise ModelError(f"bytes_per_elem must be an integer, got {data.get('bytes_per_elem')!r}")
        if out["bytes_per_elem"] not in (1, 2, 4, 8):
            raise ModelError(f"bytes_per_elem must be 1/2/4/8, got {out['bytes_per_elem']}")
    elif kind == "collective":
        try:
            msg = float(data.get("msg_size_mb", 16.0))
        except (TypeError, ValueError):
            raise ModelError(f"msg_size_mb must be a number, got {data.get('msg_size_mb')!r}")
        if not (msg > 0) or msg != msg or msg == float("inf"):
            raise ModelError(f"msg_size_mb must be a positive finite number, got {data.get('msg_size_mb')!r}")
        out["msg_size_mb"] = msg
    else:  # external
        p = data.get("trace_dir", "")
        if not p:
            raise ModelError("kind=external requires trace_dir")
        out["trace_dir"] = str(p)
    if data.get("model_name"):
        out["model_name"] = str(data["model_name"])
    if data.get("notes"):
        out["notes"] = str(data["notes"])
    return out


def list_models() -> list[dict]:
    """All registry entries, sorted (builtins first, then by name)."""
    _ensure_registry()
    out = []
    for p in sorted(REGISTRY_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        data.setdefault("name", p.stem)
        out.append(data)
    return sorted(out, key=lambda m: (not m.get("builtin"), m["name"]))


def model_names() -> list[str]:
    return [m["name"] for m in list_models()]


def get_model(name: str) -> dict | None:
    _ensure_registry()  # builtins must resolve even on a fresh clone
    name = name.lower()
    p = REGISTRY_DIR / f"{name}.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    data.setdefault("name", name)
    return data


def save_model(data: dict) -> Path:
    norm = validate(data)
    _ensure_registry()
    p = REGISTRY_DIR / f"{norm['name']}.json"
    existed = p.exists()
    if existed:
        try:
            old = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            old = {}
        if old.get("builtin"):
            raise ModelError(
                f"{norm['name']!r} is a built-in preset — pick another name "
                f"(e.g. {norm['name']}_v2)")
    norm["builtin"] = False
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(norm, indent=2) + "\n")
    tmp.rename(p)
    return p


def delete_model(name: str) -> bool:
    p = REGISTRY_DIR / f"{name.lower()}.json"
    if not p.exists():
        return False
    try:
        old = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        old = {}
    if old.get("builtin"):
        raise ModelError(f"{name!r} is built-in — it can't be deleted")
    p.unlink()
    return True


def to_spec(rec: dict, overrides: dict | None = None) -> dict:
    """Registry record -> workload spec dict in the shape the trace generator
    and astrasim runner consume. CLI --tp/--pp/--hidden-size style overrides
    win over registry values so one registry entry can feed several what-ifs."""
    spec: dict
    kind = rec.get("kind", "model")
    if kind == "collective":
        name = rec.get("model_name") or rec["name"].upper()
        _msg = int(float(rec.get("msg_size_mb", 16.0)) * 1024 * 1024)
        spec = {
            "model_name": name if name.isupper() else name.upper(),
            "is_collective_microbenchmark": True,
            "msg_size_bytes": _msg,
            "msg_size_mb": _msg / (1024 * 1024),
            "num_layers": 1,
            "total_allreduce_calls": 1,
            "total_flops": 1e9,
            "tp_degree": 1,
            "pp_degree": 1,
        }
    elif kind == "external":
        spec = {
            "model_name": rec.get("model_name") or rec["name"],
            "is_external_trace": True,
            "trace_dir": rec.get("trace_dir", ""),
            "tp_degree": 1,
            "pp_degree": 1,
        }
    else:
        spec = {
            "model_name": rec.get("model_name") or rec["name"],
            "hidden_size": rec["hidden_size"],
            "ffn_size": rec["ffn_size"],
            "num_layers": rec["num_layers"],
            "seq_len": rec["seq_len"],
            "batch_size": rec["batch_size"],
            "tp_degree": rec.get("tp_degree", 1),
            "pp_degree": rec.get("pp_degree", 1),
            "bytes_per_elem": rec.get("bytes_per_elem", 2),
        }
        # Derive the same downstream fields resolve_spec() computes, so a
        # registry model is indistinguishable from a preset/CLI model.
        _h, _s, _b = spec["hidden_size"], spec["seq_len"], spec["batch_size"]
        _msg = _b * _s * _h * spec["bytes_per_elem"]
        _attn = 2 * (4 * _h * _h) * _s * _b
        _mlp = 2 * (3 * _h * spec["ffn_size"]) * _s * _b
        spec.update({
            "msg_size_bytes": _msg,
            "msg_size_mb": _msg / (1024 * 1024),
            "attn_flops": _attn,
            "mlp_flops": _mlp,
            "layer_flops": _attn + _mlp,
            "total_flops": (_attn + _mlp) * spec["num_layers"],
            "num_tp_allreduce_per_layer": 2,
            "total_allreduce_calls": spec["num_layers"] * 2,
        })
    for k, v in (overrides or {}).items():
        if v is not None:
            spec[k] = v
    return spec


def export_presets(dest: str | None = None) -> str:
    """Print/dump built-ins as JSON — a starting point for new variants."""
    _ensure_registry()
    items = {n: d for n, d in _BUILTIN_SEED.items()}
    text = json.dumps(items, indent=2)
    if dest:
        Path(dest).write_text(text + "\n")
        return f"wrote {dest}"
    return text


def _cli_add(args) -> None:
    """Guided/CLI add: clone a base (or start fresh) with overrides."""
    _ensure_registry()
    base: dict = {}
    if args.base and args.base != "none":
        rec = get_model(args.base)
        if rec is None:
            print(f"  no base model {args.base!r} — available: {' '.join(model_names())}",
                  file=sys.stderr)
            sys.exit(1)
        base = dict(rec)
        base.pop("name", None)
        base.pop("builtin", None)
    name = args.name.lower()
    data = dict(base)
    data["name"] = name
    if args.display:
        data["model_name"] = args.display
    elif "model_name" not in data:
        data["model_name"] = name
    if args.kind:
        data["kind"] = args.kind
    if args.msg_mb is not None:
        data["msg_size_mb"] = args.msg_mb
        data.setdefault("kind", "collective")
    for flag, field in (("hidden", "hidden_size"), ("ffn", "ffn_size"),
                        ("layers", "num_layers"), ("seq", "seq_len"),
                        ("batch", "batch_size"), ("tp", "tp_degree"),
                        ("pp", "pp_degree")):
        v = getattr(args, flag)
        if v is not None:
            data[field] = int(v)
    if args.notes:
        data["notes"] = args.notes
    try:
        p = save_model(data)   # validates; refuses built-in name clash
    except ModelError as e:
        print(f"  ✗ {e}", file=sys.stderr)
        sys.exit(1)
    kind = data.get("kind", "model")
    if kind == "collective":
        print(f"  saved {p.name}: collective, msg {data.get('msg_size_mb', 16.0):g} MB")
    elif kind == "external":
        print(f"  saved {p.name}: external trace {data.get('trace_dir', '')}")
    else:
        print(f"  saved {p.name}: H={data.get('hidden_size')} "
              f"L={data.get('num_layers')} S={data.get('seq_len')} "
              f"TP={data.get('tp_degree', 1)} PP={data.get('pp_degree', 1)}")
    print("  run it:  MODEL=%s t3 astrasim" % name)


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="t3 model registry")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list", help="list registry entries")
    sub.add_parser("list_names", help="names only (for pickers)")
    p_show = sub.add_parser("show", help="dump one entry")
    p_show.add_argument("name")
    p_add = sub.add_parser("add", help="add a workload (clone base + overrides)")
    p_add.add_argument("name")
    p_add.add_argument("--base", default="llama7b",
                       help="clone defaults from this entry (none = fresh)")
    p_add.add_argument("--display", default="", help="display name")
    p_add.add_argument("--kind", default="", choices=["", "model", "collective", "external"])
    p_add.add_argument("--msg-mb", type=float, default=None)
    p_add.add_argument("--hidden", type=int, default=None)
    p_add.add_argument("--ffn", type=int, default=None)
    p_add.add_argument("--layers", type=int, default=None)
    p_add.add_argument("--seq", type=int, default=None)
    p_add.add_argument("--batch", type=int, default=None)
    p_add.add_argument("--tp", type=int, default=None)
    p_add.add_argument("--pp", type=int, default=None)
    p_add.add_argument("--notes", default="")
    p_prune = sub.add_parser("prune", help="remove non-builtin entries not touched in N days")
    p_prune.add_argument("--days", type=int, default=180)
    args = ap.parse_args()
    _ensure_registry()
    cmd = args.cmd or "list"
    if cmd == "add":
        _cli_add(args)
        return
    if cmd == "list":
        rows = list_models()
        print(f"  {'name':<22} {'kind':<11} spec")
        for m in rows:
            if m.get("kind") == "collective":
                spec = f"msg {m.get('msg_size_mb', 16.0):g} MB"
            elif m.get("kind") == "external":
                spec = m.get("trace_dir", "")
            else:
                spec = (f"H={m.get('hidden_size', '?')} L={m.get('num_layers', '?')} "
                        f"S={m.get('seq_len', '?')} TP={m.get('tp_degree', 1)} "
                        f"PP={m.get('pp_degree', 1)}")
            star = "*" if m.get("builtin") else " "
            print(f" {star}{m['name']:<21} {m.get('kind', 'model'):<11} {spec}")
        print("\n  (* = built-in; add yours: t3 model-add, or drop JSON in workloads/)")
    elif cmd == "list_names":
        print(" ".join(model_names()))
    elif cmd == "show":
        rec = get_model(args.name)
        if not rec:
            print(f"  no model {args.name!r} in registry", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(rec, indent=2))


if __name__ == "__main__":
    main()

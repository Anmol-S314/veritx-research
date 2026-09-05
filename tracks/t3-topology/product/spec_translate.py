#!/usr/bin/env python3
"""spec_translate.py — P1 product front door: typed requirements -> engine inputs.

The customer provides FLOWS (who talks to whom, how much, with what budget).
This module:
  1. validates the spec against req_schema.json,
  2. DERIVES the internal traffic matrix (customer never sees a matrix),
  3. assigns QoS classes from latency budgets (tight => GS),
  4. emits engine config: matrix .mat + synthesizer args + cert/sim plan.

LLM-assisted intake: a natural-language paragraph is turned into this typed
spec by the assistant; the validator + translate step are deterministic and
catch hallucinated fields/units (see examples/).

Usage:
  python3 spec_translate.py --spec examples/moe_serving.json --out /tmp/spec1
"""
import argparse, json, re, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent

def load_schema():
    return json.loads((HERE / "req_schema.json").read_text())

def validate(spec):
    """Minimal self-contained validator (draft-07 subset we rely on).
    Avoids jsonschema dependency while catching real intake errors."""
    errs = []
    schema = load_schema()

    def check_type(v, t, where):
        ok = {"object": dict, "array": list, "string": str,
              "integer": int, "number": (int, float), "boolean": bool}
        if t in ok and not isinstance(v, ok[t]):
            errs.append(f"{where}: expected {t}, got {type(v).__name__}")
            return False
        return True

    def walk(node, sch, where):
        if "type" not in sch:
            return
        if not check_type(node, sch["type"], where):
            return
        if sch.get("required") and isinstance(node, dict):
            for r in sch["required"]:
                if r not in node:
                    errs.append(f"{where}: missing required '{r}'")
        props = sch.get("properties", {})
        if not isinstance(node, dict):
            return
        for k, v in node.items():
            if k in props:
                ps = props[k]
                if "enum" in ps and v not in ps["enum"]:
                    errs.append(f"{where}.{k}: {v!r} not in {ps['enum']}")
                if "minimum" in ps and isinstance(v, (int, float)) and v < ps["minimum"]:
                    errs.append(f"{where}.{k}: {v} < minimum {ps['minimum']}")
                if "exclusiveMinimum" in ps and isinstance(v, (int, float)) and v <= ps["exclusiveMinimum"]:
                    errs.append(f"{where}.{k}: {v} must be > {ps['exclusiveMinimum']}")
                if "$ref" in ps:
                    ref = ps["$ref"].split("/")[-1]
                    walk(v, schema["definitions"][ref], f"{where}.{k}")
                elif isinstance(v, dict) and ps.get("type") == "object":
                    walk(v, ps, f"{where}.{k}")
                elif isinstance(v, list) and isinstance(ps.get("items"), dict):
                    for i, item in enumerate(v):
                        if isinstance(item, dict):
                            walk(item, ps["items"], f"{where}.{k}[{i}]")
                        elif "enum" in ps["items"] and item not in ps["items"]["enum"]:
                            errs.append(f"{where}.{k}[{i}]: {item!r} not in {ps['items']['enum']}")
            elif ps or sch["type"] != "object":
                errs.append(f"{where}.{k}: unknown field")
    walk(spec, schema, "spec")

    # cross-field checks
    n = spec.get("endpoints", {}).get("count", 0)
    lay = spec.get("endpoints", {}).get("layout", "grid")
    rows = spec.get("endpoints", {}).get("rows"); cols = spec.get("endpoints", {}).get("cols")
    if lay == "grid" and rows is None and int(n**0.5 + 0.5)**2 != n:
        errs.append(f"endpoints: grid layout needs count=k^2 (count={n})")
    if lay == "interposer":
        if not rows or not cols or rows*cols != n:
            errs.append(f"endpoints: interposer needs rows*cols==count ({rows}x{cols} vs {n})")
    groups = {g["name"]: set(g["members"]) for g in spec.get("endpoints", {}).get("groups", [])}
    for i, f in enumerate(spec.get("flows", [])):
        for sel_k in ("src", "dst"):
            sel = f[sel_k]
            if sel.startswith("group:") and sel.split(":", 1)[1] not in groups:
                errs.append(f"flows[{i}].{sel_k}: unknown group {sel}")
    return errs

def resolve_selector(sel, n, groups):
    """selector -> list of endpoint indices."""
    if sel == "all":
        return list(range(n))
    if sel.startswith("group:") or sel in groups:
        name = sel.split(":", 1)[1] if sel.startswith("group:") else sel
        return sorted(groups[name])
    m = re.fullmatch(r"index:(\d+)", sel)
    if m:
        i = int(m.group(1))
        assert 0 <= i < n, f"index {i} out of range"
        return [i]
    m = re.fullmatch(r"range:(\d+)-(\d+)", sel)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        assert 0 <= a <= b < n
        return list(range(a, b+1))
    raise ValueError(f"unparseable selector: {sel}")

def derive_matrix(spec):
    """flows -> normalized row-stochastic traffic matrix + per-flow metadata."""
    n = spec["endpoints"]["count"]
    groups = {g["name"]: set(g["members"]) for g in spec.get("endpoints", {}).get("groups", [])}
    clock = spec.get("budgets", {}).get("clock_mhz", 1000.0)*1e6  # Hz
    T = np.zeros((n, n))
    flow_meta = []
    for f in spec["flows"]:
        srcs = resolve_selector(f["src"], n, groups)
        dsts = resolve_selector(f["dst"], n, groups)
        dsts = [d for d in dsts if d not in srcs] or dsts
        # spread flow bandwidth uniformly across (src,dst) pairs; per-cycle weight
        # bw_gbps -> flits/cycle @ clock, pkt_size_b payload
        pkt = f.get("pkt_size_b", 64)
        flit_rate = f["bw_gbps"]*1e9/8.0/pkt/clock          # pkts/cycle aggregate
        per_pair = flit_rate/max(len(srcs)*len(dsts), 1)
        for s in srcs:
            for d in dsts:
                if s != d:
                    T[s][d] += per_pair
        tight = f.get("latency_budget_ns") is not None and \
            f["latency_budget_ns"] < 50.0   # sub-50ns budgets need reservations
        flow_meta.append({
            "name": f["name"], "srcs": srcs, "dsts": dsts,
            "bw_gbps": f["bw_gbps"], "pkt_size_b": pkt,
            "flits_per_cycle_total": round(flit_rate, 6),
            "qos_class": f.get("qos_class") or ("GS" if tight else "BE"),
            "ordering": f.get("ordering", "relaxed"),
            "protocol": f.get("protocol", "AXI4"),
        })
    rs = T.sum(axis=1, keepdims=True)
    Tn = np.where(rs > 0, T/np.maximum(rs, 1e-12), 0.0)
    return Tn, flow_meta

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True, help="output prefix")
    ap.add_argument("--emit-booksim", action="store_true",
                    help="also write BookSim-ready row-normalized matrix + cfg stub")
    args = ap.parse_args()

    spec = json.loads(Path(args.spec).read_text())
    errs = validate(spec)
    if errs:
        print("SPEC INVALID:", file=sys.stderr)
        for e in errs:
            print("  -", e, file=sys.stderr)
        sys.exit(1)
    T, meta = derive_matrix(spec)
    np.savetxt(args.out + ".mat", T, fmt="%.6f")
    plan = {
        "product": spec["product"],
        "engine_inputs": {
            "matrix": args.out + ".mat",
            "layout": spec.get("endpoints", {}).get("layout", "grid"),
            "rows": spec.get("endpoints", {}).get("rows"),
            "cols": spec.get("endpoints", {}).get("cols"),
            "radix_max": spec.get("budgets", {}).get("radix_max", 5),
            "max_len": spec.get("budgets", {}).get("link_len_units", 2.0),
            "jitter": spec.get("physical", {}).get("placement_jitter", 0.08),
        },
        "flows": meta,
        "gs_flows": [m["name"] for m in meta if m["qos_class"] == "GS"],
        "verification_plan": {
            "deadlock_cert": True,           # always enforced (by-construction path)
            "liveness_sim": "hybrid_vcsim",
            "level": spec.get("verification_intent", {}).get("level", "sim"),
        },
        "reliability": spec.get("reliability", {}),
    }
    Path(args.out + ".plan.json").write_text(json.dumps(plan, indent=2))
    print(json.dumps({"ok": True, "matrix": args.out + ".mat",
                      "gs_flows": plan["gs_flows"],
                      "total_flits_per_cycle": round(sum(m["flits_per_cycle_total"] for m in meta), 4)},
                     indent=2))
    if args.emit_booksim:
        np.savetxt(args.out + ".booksim.matrix", T, fmt="%.6f")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""dse_to_frontend.py — bridge a T3 DSE config into a noc_frontend intent spec.

The DSE ranks fabric+router configs with BookSim (latency/hops, F6 verdict).
This turns a DSE point into a noc_frontend spec so the same config earns a
cycle-accurate RTL proof (Verilator GATE-R1 diff) — the L4 leg of the
ee9d "Traffic In -> Config Out -> Cycle-Accurate Proof" product.

Only MESH points are convertible on serving-leg: the fork's RTL (tb/noc_tb.sv)
instantiates noc_mesh, and the bridged 2-die top (noc_2die.sv) lives on the
t3-rtl-noc branch. torus/fattree DSE points are rejected with a clear message.

Usage:
    python3 dse/dse_to_frontend.py --topology mesh --vcs 4 --ir 0.08 --k 8
    python3 dse/dse_to_frontend.py --dse-yaml dse/inputs/space.yaml --top 3
    python3 dse/dse_to_frontend.py --point '{"topology":"mesh","vcs":4,...}'
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC_DIR = HERE.parent / "configs" / "noc_specs"
# DSE matrix inputs (probability .mat files) the frontend can pass through.
DSE_INPUTS = HERE / "inputs"


def dse_point_to_spec(values: dict, name: str | None = None) -> dict:
    """Map a DSE DesignPoint.values dict to a noc_frontend intent spec."""
    topology = values.get("topology", "mesh")
    if topology != "mesh":
        raise ValueError(
            f"only mesh RTL is on serving-leg (got {topology!r}); "
            f"torus/fattree RTL needs the t3-rtl-noc branch (noc_2die.sv)")
    k = int(values.get("x_dim", values.get("k", 8)))
    n = int(values.get("n", 2))
    if n != 2:
        raise ValueError(f"mesh mesh assumes n=2 (got n={n})")
    vcs = int(values.get("vcs", 4))
    ir = float(values.get("injection_rate", values.get("rate", 0.08)))

    spec = {
        "name": name or f"{topology}_k{k}_vcs{vcs}_ir{ir}",
        "workload": {
            "type": "uniform",   # DSE uses synthetic BookSim traffic by default
            "nodes": k * k,
            "num_packets": 3000,
            "seed": int(values.get("seed", 42)),
            "rate": ir,
        },
        "topology": {
            "x_dim": k, "y_dim": k,
            "two_die": False,
            "anynet": "configs/booksim2_configs/bridged_2die_onaxis.anynet",
            "bridge_col": 0, "bridge_row": 0,
        },
        "router": {
            "vcs": vcs,
            "vc_buf": int(values.get("vc_buf", 8)),
            "route_tables": False,
        },
        "sim": {
            "booksim_bin": "booksim",
            "latency_thres": 5000,
            "sample_period": 1000,
            "max_samples": 30,
        },
        "outdir": "/var/tmp/opencode/nocfe",
    }
    # Faithful MoE workload: pass the DSE's traffic matrix straight through so
    # BookSim AND the RTL replay the identical distribution.
    tf = values.get("traffic_file")
    if tf is not None:
        tf = Path(tf)
        spec["workload"]["type"] = "moe_dispatch"
        spec["workload"]["matrix_file"] = str(
            tf if tf.is_absolute() else (DSE_INPUTS / tf.name))
    return spec


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topology", default="mesh")
    ap.add_argument("--vcs", type=int, default=4)
    ap.add_argument("--ir", type=float, default=0.08)
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--n", type=int, default=2)
    ap.add_argument("--vc-buf", type=int, default=8)
    ap.add_argument("--matrix-file", default=None,
                    help="DSE probability .mat (BookSim matrix() passthrough)")
    ap.add_argument("--point", default=None,
                    help="JSON object of DSE point values")
    ap.add_argument("--dse-yaml", default=None,
                    help="DesignSpace yaml; --top N picks the Nth axis combo")
    ap.add_argument("--top", type=int, default=0)
    ap.add_argument("--out", default=None, help="spec output path")
    args = ap.parse_args()

    if args.point:
        values = json.loads(args.point)
    elif args.dse_yaml:
        sys.path.insert(0, str(HERE))
        from space import DesignSpace
        space = DesignSpace.from_yaml(args.dse_yaml)
        pts = space.enumerate()
        if not (0 <= args.top < len(pts)):
            sys.exit(f"--top {args.top} out of range (0..{len(pts)-1})")
        values = pts[args.top].values
    else:
        values = {
            "topology": args.topology, "vcs": args.vcs,
            "injection_rate": args.ir, "x_dim": args.k, "n": args.n,
            "vc_buf": args.vc_buf,
        }
        if args.matrix_file:
            values["traffic_file"] = args.matrix_file

    try:
        spec = dse_point_to_spec(values)
    except ValueError as e:
        sys.exit(f"✗ {e}")

    out = Path(args.out) if args.out else (SPEC_DIR / f"{spec['name']}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2))
    print(f"spec → {out}")
    print(f"  {spec['topology']['x_dim']}x{spec['topology']['y_dim']} mesh, "
          f"vc{spec['router']['vcs']}, rate {spec['workload']['rate']}, "
          f"workload={spec['workload']['type']}")


if __name__ == "__main__":
    main()

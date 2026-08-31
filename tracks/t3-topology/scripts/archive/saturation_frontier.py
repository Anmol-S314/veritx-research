#!/usr/bin/env python3
"""saturation_frontier.py — P0: find where each topology saturates on the real MoE matrix.

Sweeps injection rate for {mesh dor, torus dim_order, custom min, custom-escape min}
and reports the full (ir -> latency, accepted-rate) curve plus the saturation point.

FIXED: saturation detection now compares accepted vs injected AT EACH IR (not vs
peak across all IRs), which was causing false-positive saturation at ir=0.04.

Also runs the hybrid per-VC cert (escape_only bound) to provide the certified
upper bound on mixed-VC latency.

Usage:
  python3 saturation_frontier.py --workdir .noc_p0 --custom .noc_p0/custom_v2.anynet \
      --matrix .noc_p0/traffic.matrix --out experiments/saturation_frontier_m3b.md --json .noc_p0/saturation.json
"""
import argparse, json, subprocess, sys
from pathlib import Path

BOOKSIM = Path(__file__).resolve().parent.parent.parent.parent / "third_party/booksim2/src/booksim"

CFGS = {
    "mesh":  "topology = mesh;\nk = 8; n = 2;\nnum_vcs = 4; vc_buf_size = 8;\nrouting_function = dor;\ntraffic = matrix({matrix});\nsim_type = latency;\ninjection_rate = {ir};\nseed = 42;\n",
    "torus": "topology = torus;\nk = 8; n = 2;\nnum_vcs = 4; vc_buf_size = 8;\nrouting_function = dim_order;\ntraffic = matrix({matrix});\nsim_type = latency;\ninjection_rate = {ir};\nseed = 42;\n",
    "custom_min": "topology = anynet;\nnetwork_file = {anynet};\nnum_vcs = 4; vc_buf_size = 8;\nrouting_function = min;\ntraffic = matrix({matrix});\nsim_type = latency;\ninjection_rate = {ir};\nseed = 42;\n",
    "custom_escape": "topology = anynet;\nnetwork_file = {esc_anynet};\nnum_vcs = 4; vc_buf_size = 8;\nrouting_function = min;\ntraffic = matrix({matrix});\nsim_type = latency;\ninjection_rate = {ir};\nseed = 42;\n",
}

def run_booksim(cfg_text, workdir, tag, timeout=600):
    cfg = workdir / f"{tag}.cfg"
    cfg.write_text(cfg_text)
    try:
        p = subprocess.run([str(BOOKSIM), cfg.name], cwd=workdir, capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"tag": tag, "timeout": True}
    out = p.stdout
    res = {"tag": tag, "rc": p.returncode}
    for key, name in [("Network latency average", "latency"),
                      ("Hops average", "hops"),
                      ("Accepted packet rate average", "accepted"),
                      ("Injected packet rate average", "injected")]:
        for line in out.splitlines():
            if line.startswith(key):
                res[name] = float(line.split("=")[1].split("(")[0])
                break
    if "Simulation aborted" in out or "deadlock" in out.lower():
        res["aborted"] = True
        res["abort_reason"] = [l for l in out.splitlines() if "eadlock" in l or "borted" in l][:2]
    return res

def detect_saturation(curve):
    """Find saturation point: the IR where accepted rate first drops below
    95% of injected rate (i.e., accepted/injected < 0.95), or where the
    accepted rate stops increasing relative to the previous IR point.
    
    Returns (saturation_ir, peak_accepted, saturation_ratio).
    """
    ok = [p for p in curve if p.get("accepted") is not None and not p.get("aborted")
          and not p.get("timeout")]
    if not ok:
        return None, 0, None
    
    peak_acc = max(p["accepted"] for p in ok)
    
    # Method 1: accepted/injected ratio drops below 0.95 (true saturation)
    sat_ir = None
    for p in ok:
        inj = p.get("injected", p["ir"])
        acc = p["accepted"]
        if inj > 0 and acc / inj < 0.95:
            sat_ir = p["ir"]
            break
    
    # Method 2: accepted rate starts decreasing from its running peak
    if sat_ir is None:
        running_peak = 0
        for p in ok:
            if p["accepted"] > running_peak:
                running_peak = p["accepted"]
            elif p["accepted"] < 0.98 * running_peak:
                sat_ir = p["ir"]
                break
    
    return sat_ir, peak_acc, peak_acc

def run_hybrid_cert(anynet, matrix, ir=0.08, cycles=100000):
    """Run the hybrid per-VC cert via hybrid_vcsim.py."""
    cert_script = Path(__file__).resolve().parent.parent / "scripts" / "hybrid_vcsim.py"
    try:
        p = subprocess.run([
            sys.executable, str(cert_script),
            "--anynet", str(anynet),
            "--matrix", str(matrix),
            "--mode", "escape_only",
            "--ir", str(ir),
            "--cycles", str(cycles),
        ], capture_output=True, text=True, timeout=300)
        if p.returncode == 0:
            import json as _json
            return _json.loads(p.stdout)
    except Exception:
        pass
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", default=".noc_p0")
    ap.add_argument("--custom", default=".noc_p0/custom_v2.anynet")
    ap.add_argument("--esc-anynet", default=".noc_p0/escape_tree_v2.anynet")
    ap.add_argument("--matrix", default=".noc_p0/traffic.matrix")
    ap.add_argument("--irs", default="0.04,0.08,0.12,0.16,0.20,0.24,0.28,0.32,0.40,0.48,0.56,0.64,0.80,1.00,1.20")
    ap.add_argument("--skip-escape", action="store_true")
    ap.add_argument("--json", default=".noc_p0/saturation.json")
    args = ap.parse_args()

    wd = Path(args.workdir); wd.mkdir(parents=True, exist_ok=True)
    irs = [float(x) for x in args.irs.split(",")]
    results = {}
    for topo, tmpl in CFGS.items():
        if topo == "custom_escape" and args.skip_escape:
            continue
        if topo.startswith("custom") and not Path(args.custom).exists():
            print(f"skip {topo}: no {args.custom}"); continue
        if topo == "custom_escape" and not Path(args.esc_anynet).exists():
            print(f"skip {topo}: no {args.esc_anynet}"); continue
        curve = []
        for ir in irs:
            kw = dict(matrix=str(Path(args.matrix).resolve()), anynet=str(Path(args.custom).resolve()),
                      esc_anynet=str(Path(args.esc_anynet).resolve()), ir=f"{ir}")
            r = run_booksim(tmpl.format(**kw), wd, f"{topo}_ir{ir}")
            r["ir"] = ir
            curve.append(r)
            lat = r.get("latency"); acc = r.get("accepted"); inj = r.get("injected")
            print(f"{topo:14s} ir={ir:<5} lat={lat if lat is not None else 'TIMEOUT/ABORT'} "
                  f"acc={acc} inj={inj}", flush=True)
            # early stop on hard collapse far past saturation
            if lat is not None and lat > 10000:
                break
        results[topo] = curve

    # FIXED saturation analysis
    summary = {}
    for topo, curve in results.items():
        sat_ir, peak_acc, _ = detect_saturation(curve)
        ok = [p for p in curve if p.get("accepted") is not None and not p.get("aborted")
              and not p.get("timeout")]
        lat_at_032 = next((p.get("latency") for p in ok if abs(p["ir"] - 0.32) < 1e-9), None)
        summary[topo] = {
            "saturation_ir": sat_ir,
            "peak_accepted": round(peak_acc, 4),
            "lat_at_0.32": lat_at_032,
        }

    # Run hybrid cert for the escape-only bound
    if Path(args.custom).exists() and Path(args.matrix).exists():
        print("\nRunning hybrid per-VC cert (escape-only bound)...")
        cert = run_hybrid_cert(args.custom, args.matrix)
        if cert:
            summary["hybrid_escape_bound"] = {
                "mode": cert["mode"],
                "avg_latency": cert["avg_latency"],
                "avg_hops": cert["avg_hops"],
                "LIVE": cert["LIVE"],
                "injected": cert["injected"],
                "ejected": cert["ejected"],
                "demotions": cert["demotions"],
            }
            print(f"  escape-only bound: lat={cert['avg_latency']:.1f}, "
                  f"hops={cert['avg_hops']:.3f}, LIVE={cert['LIVE']}, "
                  f"demotions={cert['demotions']}")
    
    Path(args.json).write_text(json.dumps({"curves": results, "summary": summary}, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"-> {args.json}")

if __name__ == "__main__":
    main()

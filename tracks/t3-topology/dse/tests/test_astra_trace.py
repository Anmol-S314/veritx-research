import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

def main():
    from roofline import classify_trace
    trace_path = str(HERE / "inputs/qwen3_serving_astra.trace")
    assert Path(trace_path).exists(), f"trace not found: {trace_path}"
    r = classify_trace(trace_path, n_nodes=4)
    m = r["metrics"]
    print(f"classify: {r['classification']['classification']} "
          f"peak={m['peak_injection_rate']:.5f} burstiness={m['burstiness']:.1f}x")
    assert r["classification"]["classification"] in ("compute", "memory", "network"), \
        f"unexpected classification: {r['classification']['classification']}"
    assert m["peak_injection_rate"] > 0, "peak_injection_rate must be positive"
    assert m["burstiness"] >= 1.0, "burstiness must be >= 1.0"

    from space import DesignPoint
    from evaluator import run_booksim
    pt = DesignPoint(assignments=(("topology", "mesh"), ("vcs", 2)))
    defaults = {"x_dim": 2, "y_dim": 2, "injection_rate": m['peak_injection_rate'],
                "vc_buf": 8, "trace_file": trace_path,
                "cycles": 15621049}
    res = run_booksim(pt, defaults, timeout=600)
    assert res.ok, f"BookSim failed: {res.error}"
    print(f"BookSim on REAL serving trace: lat={res.avg_latency:.1f} "
          f"hops={res.avg_hops:.2f} thru={res.throughput:.4f}")
    assert res.avg_latency > 0, "latency must be positive"
    assert res.avg_hops > 0, "hops must be positive"
    print("PASS: test_astra_trace")

if __name__ == "__main__":
    main()

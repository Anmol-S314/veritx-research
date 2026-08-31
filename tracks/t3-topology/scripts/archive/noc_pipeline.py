#!/usr/bin/env python3
"""noc_pipeline.py — P1: Enforced deadlock-by-construction pipeline.

The ONLY product entry point. Given a topology + traffic matrix, this script:
  1. Verifies connectivity
  2. Generates escape spanning tree
  3. Runs deadlock certificate (CDG acyclicity)
  4. Runs hybrid per-VC liveness check
  5. Emits certified artifacts: {anynet, tree, cert.json, plan.json}

If ANY step fails, the pipeline aborts — no uncertified topology leaves.

Usage:
  python3 noc_pipeline.py --anynet .noc_p0/custom_v2.anynet \
      --matrix tracks/t3-topology/dse/inputs/qwen_moe_64d.mat \
      --out .noc_p0/pipeline_out
"""
import argparse
import json
import sys
import time
from collections import deque
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent


def fail(msg):
    print(f"\n❌ PIPELINE ABORTED: {msg}", file=sys.stderr)
    sys.exit(1)


def step(name, fn):
    """Run a pipeline step, print status, abort on failure."""
    print(f"  [{name}]...", end=" ", flush=True)
    t0 = time.time()
    try:
        result = fn()
        dt = time.time() - t0
        if result.get("status") == "FAIL":
            print(f"❌ FAIL ({dt:.1f}s): {result.get('detail', '')}")
            fail(result.get("detail", name))
        print(f"✅ PASS ({dt:.1f}s): {result.get('detail', '')}")
        return result
    except Exception as e:
        print(f"❌ ERROR ({time.time()-t0:.1f}s): {e}")
        fail(str(e))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anynet", required=True, help="topology .anynet file")
    ap.add_argument("--matrix", required=True, help="traffic matrix")
    ap.add_argument("--out", required=True, help="output directory for certified artifacts")
    ap.add_argument("--irs", default="0.04,0.08,0.16", help="IRs for liveness check")
    args = ap.parse_args()

    anynet = Path(args.anynet)
    matrix = Path(args.matrix)
    out_dir = Path(args.out)

    if not anynet.exists():
        fail(f"{anynet} not found")
    if not matrix.exists():
        fail(f"{matrix} not found")

    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(f"  NoC PIPELINE — deadlock-by-construction enforcement")
    print(f"  topology: {anynet.name}")
    print(f"  matrix:   {matrix.name}")
    print(f"  output:   {out_dir}")
    print("=" * 60)
    print()

    artifacts = {}
    timings = {}

    # ── Step 1: Connectivity ──
    def check_connectivity():
        sys.path.insert(0, str(SCRIPTS_DIR))
        from deadlock_routing import parse_anynet
        n, adj = parse_anynet(str(anynet))
        seen = {0}; q = deque([0])
        while q:
            u = q.popleft()
            for v in adj[u]:
                if v not in seen: seen.add(v); q.append(v)
        if len(seen) != n:
            return {"status": "FAIL", "detail": f"disconnected: {len(seen)}/{n} reachable"}
        edges = sum(len(v) for v in adj.values()) // 2
        return {"status": "PASS", "detail": f"{n} nodes, {edges} edges, connected",
                "n": n, "edges": edges}

    r = step("CONNECTIVITY", check_connectivity)
    artifacts["topology"] = {"n": r["n"], "edges": r["edges"]}

    # ── Step 2: Escape tree ──
    def gen_escape_tree():
        import subprocess
        out_prefix = str(out_dir / "escape")
        p = subprocess.run([sys.executable, str(SCRIPTS_DIR / "escape_anynet.py"),
                           "--anynet", str(anynet), "--matrix", str(matrix),
                           "--out", out_prefix],
                          capture_output=True, text=True, timeout=60)
        data = json.loads(p.stdout.split("\n{")[0] if "\n{" in p.stdout else p.stdout)
        # Actually parse the full JSON
        for line in reversed(p.stdout.strip().split("\n")):
            try:
                data = json.loads(line)
                break
            except:
                continue
        if not data.get("cdg", {}).get("acyclic"):
            return {"status": "FAIL", "detail": "escape tree CDG is cyclic"}
        if not data.get("escape_route_matches_unique_tree_path"):
            return {"status": "FAIL", "detail": f"{data.get('mismatches', '?')} path mismatches"}
        return {"status": "PASS",
                "detail": f"tree={data['tree_edges']} edges, depth={data['spanning_tree']['max_depth'] if 'spanning_tree' in data else '?'}, CDG acyclic",
                "tree_anynet": str(out_dir / "escape.anynet"),
                "data": data}

    r = step("ESCAPE TREE", gen_escape_tree)
    artifacts["escape_tree"] = r.get("data", {})

    # ── Step 3: Deadlock certificate ──
    def gen_deadlock_cert():
        import subprocess
        cert_path = str(out_dir / "cert.json")
        p = subprocess.run([sys.executable, str(SCRIPTS_DIR / "deadlock_guarantee.py"),
                           "--anynet", str(anynet), "--matrix", str(matrix),
                           "--out", cert_path],
                          capture_output=True, text=True, timeout=120)
        # Parse the first JSON object from stdout
        data = None
        text = p.stdout
        idx = text.find('{')
        if idx >= 0:
            depth = 0
            for i in range(idx, len(text)):
                if text[i] == '{': depth += 1
                elif text[i] == '}': depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(text[idx:i+1])
                    except:
                        pass
                    break
        if data is None:
            return {"status": "FAIL", "detail": f"could not parse cert output: {p.stdout[:200]}"}
        if data.get("status") != "PASS":
            return {"status": "FAIL", "detail": f"deadlock cert: {data.get('status', '?')}"}
        return {"status": "PASS",
                "detail": f"CDG={data['cdg']['n_channels']}ch acyclic, tree={data['spanning_tree']['n_edges']}edges",
                "data": data}

    r = step("DEADLOCK CERT", gen_deadlock_cert)
    artifacts["deadlock_cert"] = r.get("data", {})

    # ── Step 4: Hybrid liveness ──
    def check_hybrid_liveness():
        import subprocess
        irs = [float(x) for x in args.irs.split(",")]
        all_live = True
        details = []
        for ir in irs:
            p = subprocess.run([sys.executable, str(SCRIPTS_DIR / "hybrid_vcsim.py"),
                               "--anynet", str(anynet), "--matrix", str(matrix),
                               "--mode", "hybrid", "--ir", str(ir),
                               "--cycles", "30000", "--vcs-free", "3"],
                              capture_output=True, text=True, timeout=120)
            data = json.loads(p.stdout)
            if not data.get("LIVE"):
                all_live = False
            details.append(f"IR={ir}: lat={data['avg_latency']:.1f} "
                          f"{'LIVE' if data['LIVE'] else 'DEAD'} "
                          f"demoted={data['demotions']}")
        if not all_live:
            return {"status": "FAIL", "detail": "liveness violation: " + " | ".join(details)}
        return {"status": "PASS", "detail": " | ".join(details)}

    r = step("HYBRID LIVENESS", check_hybrid_liveness)

    # ── Step 5: Emit artifacts ──
    def emit_artifacts():
        import shutil
        # Copy the anynet
        shutil.copy2(anynet, out_dir / "topology.anynet")
        # Copy the matrix
        shutil.copy2(matrix, out_dir / "traffic.matrix")
        # Write plan.json
        plan = {
            "pipeline_version": "1.0",
            "topology": str(anynet.name),
            "matrix": str(matrix.name),
            "artifacts": {
                "topology": "topology.anynet",
                "escape_tree": "escape.anynet",
                "certificate": "cert.json",
                "traffic": "traffic.matrix",
            },
            "certification": {
                "deadlock_free": True,
                "method": "Dally-Seitz up/down escape routing on BFS spanning tree",
                "escape_vcs": 1,
                "free_vcs": 3,
                "total_vcs": 4,
            },
            "verification": {
                "deadlock_cert": True,
                "hybrid_liveness": True,
                "escape_tree_correct": True,
            },
        }
        (out_dir / "plan.json").write_text(json.dumps(plan, indent=2))
        return {"status": "PASS", "detail": f"emitted {len(list(out_dir.iterdir()))} files to {out_dir}"}

    step("EMIT ARTIFACTS", emit_artifacts)

    # ── Summary ──
    print()
    print("=" * 60)
    print("  ✅ PIPELINE COMPLETE — topology certified deadlock-free")
    print(f"  artifacts: {out_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()

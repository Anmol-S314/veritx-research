#!/usr/bin/env python3
"""Area denominator for the PyTorchSim topology sweep (T3).

The sweep measured CYCLES for one BERT encoder block on three NoCs. Cycles alone
cannot decide anything: a fat-tree can beat a mesh by buying more routers at a
higher radix, and if it pays 2x the area for 1.9x the speed the mesh was right
all along. This script supplies the missing axis.

It deliberately reuses area_report.py's radix-scaled router model (crossbar is
O(radix^2), plus one input buffer per port) rather than inventing a second one.
That model exists because the shipped `isaac_router` prices EVERY router at a
flat 150000 um^2 regardless of radix -- which is what produced the bogus "routers
are 95% of the die" result this work started from.

Topologies are the ones actually simulated, with Booksim's own constructors:

    mesh     k=8  n=2   -> kncube:  64 routers
    fattree  k=4  n=3   -> fattree: 48 switches
    fly      k=64 n=1   -> fly:      1 router, radix 64  (a 64-way CROSSBAR --
                                     an idealized upper bound, not a real NoC)

Run inside the tools image (needs Accelergy):
    python3 scripts/pytorchsim_area.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from area_report import accelergy_arch, check_estimators, run_accelergy  # noqa: E402

# The PyTorchSim NoC: 2 cores * 16 injection ports + 32 DRAM channels = 64 nodes.
NODES = 64
FLIT_BITS = 32       # flit_size = 32 in every .icnt used in the sweep
VC_BUF = 256         # vc_buf_size = 256, ditto

# Measured by the sweep (sw3/, and the earlier fly run). Cycles for one encoder
# block, 18 fused kernels; ONLY booksim_config_path differed between runs.
CYCLES = {"fly": 303_850, "fattree": 400_147, "mesh": 759_544}


def shape(topo):
    """(routers, radix) straight from Booksim's network constructors.

    radix = inter-router channels/router + nodes/router (injection ports), the
    same definition area_report.topology_shape uses. Kept explicit here because
    these come from PyTorchSim .icnt files, not from configs/*.cfg.
    """
    if topo == "mesh":                       # kncube, k=8 n=2
        k, n = 8, 2
        routers = k ** n                     # 64
        channels = 2 * n * routers           # 256 (bidirectional, both dims)
    elif topo == "fattree":                  # fattree.cpp, k=4 n=3
        k, n = 4, 3
        routers = n * k ** (n - 1)           # 48 switches
        channels = (2 * k * k ** (n - 1)) * (n - 1)   # 256
    elif topo == "fly":                      # fly.cpp, k=64 n=1 -> single crossbar
        k, n = 64, 1
        routers = n * k ** (n - 1)           # 1
        channels = (n - 1) * NODES           # 0: no inter-router links to build
    else:
        raise ValueError(topo)
    radix = channels / routers + NODES / routers
    return routers, radix


def _selfcheck():
    # Booksim's own constructors -- if these drift, every area number is for the
    # wrong network.
    assert shape("mesh")[0] == 64, "8x8 mesh must have 64 routers"
    assert abs(shape("mesh")[1] - 5.0) < 1e-9, "mesh router is radix 5 (N/E/S/W+local)"
    assert shape("fattree")[0] == 48, "k=4 n=3 fattree has 48 switches"
    assert shape("fly")[0] == 1, "fly k=64 n=1 is ONE router -- a 64-way crossbar"
    assert abs(shape("fly")[1] - 64.0) < 1e-9, "...at radix 64"
    # the fat-tree must use FEWER routers at HIGHER radix than the mesh: that is
    # the whole reason its router area comes out close to the mesh's.
    assert shape("fattree")[0] < shape("mesh")[0]
    assert shape("fattree")[1] > shape("mesh")[1]
    print("selfcheck OK")


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--selfcheck":
        return _selfcheck()
    check_estimators()   # refuse to run against an image whose Accelergy is a stub

    shapes = {t: shape(t) for t in CYCLES}
    # one Accelergy call: price every distinct radix at once
    arch = accelergy_arch(rf_entries=64, gb_kb=32, word_bits=8,
                          routers={t: r for t, (_, r) in shapes.items()},
                          flit_bits=FLIT_BITS, vc_buf_entries=VC_BUF)
    per_inst = run_accelergy(arch)

    rows = {}
    for topo, (routers, radix) in shapes.items():
        xbar = per_inst[f"Crossbar_{topo}"]
        # one input buffer PER PORT, so the buffer cost scales with radix too
        buf = per_inst[f"InBuf_{topo}"] * max(2, int(round(radix)))
        each = xbar + buf
        rows[topo] = {
            "routers": routers,
            "radix": round(radix, 1),
            "router_um2_each": round(each, 1),
            "noc_um2": round(each * routers, 1),
            "cycles": CYCLES[topo],
        }

    base = rows["mesh"]
    for r in rows.values():
        r["speedup_vs_mesh"] = round(base["cycles"] / r["cycles"], 2)
        r["area_vs_mesh"] = round(r["noc_um2"] / base["noc_um2"], 2)
        # The number that actually decides it. >1 means the topology buys more
        # speed than it costs in area, relative to the mesh.
        r["perf_per_area"] = round(r["speedup_vs_mesh"] / r["area_vs_mesh"], 2)

    out = HERE.parent / "results" / "pytorchsim_area.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2))

    print(f"\n  NoC area vs performance — 64-node, {FLIT_BITS}b flits, "
          f"BERT encoder block\n")
    print(f"  {'topology':<9} {'routers':>7} {'radix':>6} {'NoC um^2':>12} "
          f"{'speedup':>8} {'area':>7} {'perf/area':>10}")
    for t in ("mesh", "fattree", "fly"):
        r = rows[t]
        print(f"  {t:<9} {r['routers']:>7} {r['radix']:>6.1f} {r['noc_um2']:>12,.0f} "
              f"{r['speedup_vs_mesh']:>7.2f}x {r['area_vs_mesh']:>6.2f}x "
              f"{r['perf_per_area']:>9.2f}x")
    print(f"\n  (speedup/area/perf-per-area are all RELATIVE TO MESH)")
    print(f"  -> {out}")

    ft = rows["fattree"]
    verdict = ("fat-tree beats the mesh even after paying for its routers"
               if ft["perf_per_area"] > 1 else
               "the mesh is vindicated: fat-tree's speed costs more area than it buys")
    print(f"\n  VERDICT: {verdict} (perf/area = {ft['perf_per_area']}x)")


if __name__ == "__main__":
    main()

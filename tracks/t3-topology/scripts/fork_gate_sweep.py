#!/usr/bin/env python3
"""Run the fork Gate R1 across g values: BookSim trace -> hex -> RTL -> diff."""
import os, subprocess, sys

BOOKSIM = os.environ.get("BOOKSIM_BIN",
                         "/home/datavex/veritx-research/third_party/booksim2/src/booksim")
CFG = os.environ.get("FORK_CFG",
                     "/home/datavex/veritx-research/tracks/t3-topology/configs/mesh8x8.cfg")
RTL = os.environ.get("FORK_RTL", "/tmp/opencode/gate16_b3/Vnoc_tb")
SCRIPTS = os.environ.get("FORK_SCRIPTS",
                         "/home/datavex/veritx-research/tracks/t3-topology/scripts")

def gen_hex(out, trace):
    by_src = {}
    for l in trace:
        if len(l) == 8 and l[5] == "mcast":
            cyc, src, cl, dst, size = int(l[0]), int(l[1]), int(l[2]), int(l[3]), int(l[4])
            lo, hi = int(l[6]), int(l[7])
        else:
            cyc, src, cl, dst, size = map(int, l[:5])
            lo = hi = -1
        by_src.setdefault(src, []).append((cyc, cl, dst, size, lo, hi))
    for src, entries in by_src.items():
        with open(f"{out}/trace_n{src}.hex", "w") as f:
            for cyc, cl, dst, size, lo, hi in entries:
                f.write(f"{cyc:08x}{cl:02x}{dst:02x}{size:04x}\n")
                if lo >= 0:
                    f.write(f"00000000{lo:02x}{hi:02x}0000\n")
    last = max(int(l[0]) for l in trace)
    open(f"{out}/run_cycles", "w").write(str(last + 2500) + "\n")
    return last + 2500

for g in (4, 8, 16):
    out = f"/tmp/opencode/gf_{g}"
    os.makedirs(out, exist_ok=True)
    # g<=8 fits the 8x8 mesh; g=16 needs the 16x8 mesh (copies must lie on
    # the stream's path: row 0 has only 8 columns). The RTL binary must be
    # built with matching -GX_DIM/-GY_DIM (FORK_RTL).
    cfg = CFG if g <= 8 else "/home/datavex/veritx-research/tracks/t3-topology/configs/mesh16x8.cfg"
    subprocess.run([BOOKSIM, cfg, f"mcast_k={g}", "mcast_offset=0",
                    "mcast_single=1", "mcast_naive=0", "injection_rate=0.001",
                    "traffic=uniform", "packet_size=1", "sim_type=latency",
                    "sample_period=1000", "warmup_periods=3", "max_samples=30",
                    "trace_out=trace.txt", "flit_dump=flits.txt"],
                   cwd=out, capture_output=True)
    trace = [l.split() for l in open(f"{out}/trace.txt") if l.strip()]
    runc = gen_hex(out, trace)
    rtl = RTL if g <= 8 else "/tmp/opencode/gate16_b3/Vnoc_tb"
    r = subprocess.run([rtl, f"+run_cycles={runc}"], cwd=out,
                       capture_output=True, text=True, timeout=300)
    if "R1 SIM COMPLETE" not in r.stdout:
        print(f"g={g}: RTL FAILED\n{r.stdout[-400:]}")
        continue
    d = subprocess.run([sys.executable, f"{SCRIPTS}/rtl_r1.py", "diff", out],
                       capture_output=True, text=True)
    print(f"g={g}: {d.stdout.strip().splitlines()[-2:]}")

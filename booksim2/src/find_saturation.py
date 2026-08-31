#!/usr/bin/env python3
"""Fine-grained injection-rate sweep to find the real saturation point
(max sustained accepted throughput) for MECS(dor) vs Hybrid under skewed
(transpose) traffic, k=4/d=3/o=1/c=1/num_vcs=6/vc_buf_size=8 -- same
fixed params as gec_topology_comparison.xlsx, just finer rate steps."""
import re
import subprocess
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
BOOKSIM = SRC_DIR / "booksim"

RATES = [0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.14, 0.16, 0.18, 0.20]

CONFIG_TEMPLATE = """\
topology = gec;
routing_function = {routing_function};
k = 4;
c = 1;
o = 1;
d = 3;
mesh = 0;
hybrid = {hybrid_flag};
num_vcs = 6;
vc_buf_size = 8;
wait_for_tail_credit = 0;
vc_allocator = islip;
sw_allocator = islip;
alloc_iters = 1;
routing_delay = 1;
vc_alloc_delay = 1;
sw_alloc_delay = 1;
credit_delay = 1;
st_prepare_delay = 0;
st_final_delay = 1;
input_speedup = 1;
output_speedup = 1;
internal_speedup = 1.0;
hold_switch_for_packet = 0;
buffer_policy = private;
channel_width = 128;
use_noc_latency = 0;
traffic = transpose;
packet_size = 5;
injection_rate = {rate};
sim_type = latency;
warmup_periods = 3;
sample_period = 1000;
sim_count = 1;
"""

ACC_RE = re.compile(r"^Accepted packet rate average = ([\d.]+)", re.MULTILINE)
INJ_RE = re.compile(r"^Injected packet rate average = ([\d.]+)", re.MULTILINE)
LAT_RE = re.compile(r"^Packet latency average = ([\d.]+)", re.MULTILINE)
UNSTABLE_RE = re.compile(r"unstable", re.IGNORECASE)


def run_one(routing_function, hybrid_flag, rate):
    cfg = CONFIG_TEMPLATE.format(routing_function=routing_function, hybrid_flag=hybrid_flag, rate=rate)
    cfg_path = SRC_DIR / "_sat_tmp.config"
    cfg_path.write_text(cfg)
    proc = subprocess.run([str(BOOKSIM), str(cfg_path)], cwd=str(SRC_DIR),
                           capture_output=True, text=True, timeout=60)
    out = proc.stdout + proc.stderr
    acc = ACC_RE.findall(out)
    inj = INJ_RE.findall(out)
    lat = LAT_RE.findall(out)
    unstable = bool(UNSTABLE_RE.search(out))
    return (float(inj[-1]) if inj else None, float(acc[-1]) if acc else None,
            float(lat[-1]) if lat else None, unstable)


def main():
    for label, rf, hf in [("MECS(dor)", "dor", 0), ("Hybrid", "hybrid", 1)]:
        print(f"=== {label} ===")
        for rate in RATES:
            inj, acc, lat, unstable = run_one(rf, hf, rate)
            print(f"  rate={rate:.2f}  injected={inj}  accepted={acc}  latency={lat}  {'UNSTABLE' if unstable else 'stable'}")


if __name__ == "__main__":
    main()

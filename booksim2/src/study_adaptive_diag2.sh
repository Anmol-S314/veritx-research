#!/bin/bash
cd /home/sowmith/booksim2/src

run_one () {
  local routing=$1 numvcs=$2 traffic=$3 rate=$4 label=$5
  cat > /tmp/adaptive_diag2.config <<EOF
topology = gec;
routing_function = $routing;
k = 8;
c = 1;
o = 1;
d = 7;
mesh = 0;
num_vcs = $numvcs;
vc_buf_size = 8;
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
channel_width = 128;
use_noc_latency = 0;
traffic = $traffic;
packet_size = 5;
injection_rate = $rate;
sim_type = latency;
warmup_periods = 3;
sample_period = 2000;
sim_count = 1;
EOF
  out=$(timeout 30 ./booksim /tmp/adaptive_diag2.config 2>&1)
  inj=$(echo "$out" | grep "Injected packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  acc=$(echo "$out" | grep "Accepted packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  lat=$(echo "$out" | grep "^Packet latency average" | tail -1 | sed 's/.*= //;s/ .*//')
  unstable=$(echo "$out" | grep -c "unstable")
  err=$(echo "$out" | grep -c "^Error")
  echo "$label routing=$routing numvcs=$numvcs traffic=$traffic rate=$rate -> inj=$inj acc=$acc lat=$lat unstable=$unstable err=$err"
}

echo "=== k=8 (power of 2), transpose traffic, d=7 pure MECS ==="
for rate in 0.02 0.05 0.08 0.10 0.13; do
  run_one dor 21 transpose $rate "transpose"
  run_one adaptive_xy_yx 21 transpose $rate "transpose"
done

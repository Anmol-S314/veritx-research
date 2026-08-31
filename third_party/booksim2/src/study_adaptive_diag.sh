#!/bin/bash
cd /home/sowmith/booksim2/src

run_one () {
  local routing=$1 numvcs=$2 traffic=$3 rate=$4 label=$5
  cat > /tmp/adaptive_diag.config <<EOF
topology = gec;
routing_function = $routing;
k = 7;
c = 1;
o = 1;
d = 6;
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
  out=$(timeout 30 ./booksim /tmp/adaptive_diag.config 2>&1)
  inj=$(echo "$out" | grep "Injected packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  acc=$(echo "$out" | grep "Accepted packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  lat=$(echo "$out" | grep "^Packet latency average" | tail -1 | sed 's/.*= //;s/ .*//')
  unstable=$(echo "$out" | grep -c "unstable")
  echo "$label routing=$routing numvcs=$numvcs traffic=$traffic rate=$rate -> inj=$inj acc=$acc lat=$lat unstable=$unstable"
}

echo "=== isolating VC-fragmentation confound: num_vcs=24 (2 VCs/tap/phase for adaptive, matches dor's 2 VCs/tap) ==="
for rate in 0.20 0.30 0.50 0.70 0.90; do
  run_one dor 24 uniform $rate "MECS-eqVC"
  run_one adaptive_xy_yx 24 uniform $rate "MECS-eqVC"
done

echo "=== skewed traffic (transpose): does adaptive show benefit where uniform didn't? ==="
for rate in 0.05 0.10 0.15 0.20; do
  run_one dor 16 transpose $rate "MECS-transpose"
  run_one adaptive_xy_yx 16 transpose $rate "MECS-transpose"
done

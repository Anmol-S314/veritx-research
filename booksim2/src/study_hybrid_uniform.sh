#!/bin/bash
# Hybrid vs pure MECS vs pure express, k=7 c=1 o=1 d=6, num_vcs=16,
# vc_buf_size=8, packet_size=5, uniform traffic -- the case routing
# CAN help, as a contrast to the destination-bound matrix result.
cd /home/sowmith/booksim2/src
OUT=/home/sowmith/booksim2/results_hybrid_uniform.csv
echo "topology,routing,mesh,hybrid,o,d,injection_rate,injected_pkt_rate,accepted_pkt_rate,latency,unstable" > $OUT
RATES="0.10 0.20 0.30 0.40 0.50 0.60 0.70 0.80 0.90"

run_one () {
  local topo=$1 routing=$2 mesh=$3 hybrid=$4 o=$5 d=$6 rate=$7
  cat > /tmp/hybrid_uniform_test.config <<EOF
topology = gec;
routing_function = $routing;
k = 7;
c = 1;
o = $o;
d = $d;
mesh = $mesh;
hybrid = $hybrid;
num_vcs = 16;
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
traffic = uniform;
packet_size = 5;
injection_rate = $rate;
sim_type = latency;
warmup_periods = 3;
sample_period = 2000;
sim_count = 1;
EOF
  out=$(timeout 30 ./booksim /tmp/hybrid_uniform_test.config 2>&1)
  inj=$(echo "$out" | grep "Injected packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  acc=$(echo "$out" | grep "Accepted packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  lat=$(echo "$out" | grep "^Packet latency average" | tail -1 | sed 's/.*= //;s/ .*//')
  unstable=$(echo "$out" | grep -c "unstable")
  echo "$topo,$routing,$mesh,$hybrid,$o,$d,$rate,$inj,$acc,$lat,$unstable" >> $OUT
}

for rate in $RATES; do
  run_one MECS dor 0 0 1 6 $rate
  run_one hybrid hybrid 0 1 1 6 $rate
done
echo "DONE: $OUT"

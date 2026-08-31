#!/bin/bash
# Hybrid mesh+MECS vs pure MECS, same k=4 c=1 (16 nodes, matches
# traffic_matrix.txt), same o=1,d=3, num_vcs=8, vc_buf_size=8,
# packet_size=5, real traffic_matrix.txt traffic.
cd /home/sowmith/booksim2/src
OUT=/home/sowmith/booksim2/results_hybrid_matrix.csv
echo "topology,routing,injection_rate,injected_pkt_rate,accepted_pkt_rate,latency,unstable" > $OUT

run_one () {
  local topo=$1 routing=$2 hybrid=$3 rate=$4
  cat > /tmp/hybrid_matrix_test.config <<EOF
topology = gec;
routing_function = $routing;
k = 4;
c = 1;
o = 1;
d = 3;
mesh = 0;
hybrid = $hybrid;
num_vcs = 8;
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
traffic = matrix(../traffic_matrix.txt);
packet_size = 5;
injection_rate = $rate;
sim_type = latency;
warmup_periods = 3;
sample_period = 1000;
sim_count = 1;
EOF
  out=$(timeout 30 ./booksim /tmp/hybrid_matrix_test.config 2>&1)
  inj=$(echo "$out" | grep "Injected packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  acc=$(echo "$out" | grep "Accepted packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  lat=$(echo "$out" | grep "^Packet latency average" | tail -1 | sed 's/.*= //;s/ .*//')
  unstable=$(echo "$out" | grep -c "unstable")
  echo "$topo,$routing,$rate,$inj,$acc,$lat,$unstable" >> $OUT
}

for rate in 0.005 0.01 0.015 0.02 0.025 0.03 0.04 0.05; do
  run_one MECS dor 0 $rate
  run_one hybrid hybrid 1 $rate
done
echo "DONE: $OUT"
cat $OUT

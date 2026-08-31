#!/bin/bash
# Hybrid vs pure MECS under transpose (skewed) traffic -- k=8 (power of
# two, required by transpose), o=1, d=7, num_vcs=21 (>= 2*d), vc_buf_size=8.
cd /home/sowmith/booksim2/src
OUT=/home/sowmith/booksim2/results_hybrid_transpose.csv
echo "topology,routing,hybrid,injection_rate,injected_pkt_rate,accepted_pkt_rate,latency,unstable" > $OUT

run_one () {
  local topo=$1 routing=$2 hybrid=$3 rate=$4
  cat > /tmp/hybrid_transpose_test.config <<EOF
topology = gec;
routing_function = $routing;
k = 8;
c = 1;
o = 1;
d = 7;
mesh = 0;
hybrid = $hybrid;
num_vcs = 21;
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
traffic = transpose;
packet_size = 5;
injection_rate = $rate;
sim_type = latency;
warmup_periods = 3;
sample_period = 2000;
sim_count = 1;
EOF
  out=$(timeout 30 ./booksim /tmp/hybrid_transpose_test.config 2>&1)
  inj=$(echo "$out" | grep "Injected packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  acc=$(echo "$out" | grep "Accepted packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  lat=$(echo "$out" | grep "^Packet latency average" | tail -1 | sed 's/.*= //;s/ .*//')
  unstable=$(echo "$out" | grep -c "unstable")
  echo "$topo,$routing,$hybrid,$rate,$inj,$acc,$lat,$unstable" >> $OUT
}

for rate in 0.02 0.05 0.08 0.10 0.13; do
  run_one MECS dor 0 $rate
  run_one hybrid hybrid 1 $rate
done
echo "DONE: $OUT"
cat $OUT

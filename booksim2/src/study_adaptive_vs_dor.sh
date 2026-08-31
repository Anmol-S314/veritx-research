#!/bin/bash
# dor_gec vs adaptive_xy_yx_gec, matched num_vcs=16 (above adaptive's
# 2*d floor for d=6), vc_buf_size=8, k=7, c=1, packet_size=5, uniform
# traffic. Both express (o=6,d=1) and pure MECS (o=1,d=6).
cd /home/sowmith/booksim2/src
OUT=/home/sowmith/booksim2/results_adaptive_vs_dor.csv
echo "routing,mode,o,d,injection_rate,injected_pkt_rate,accepted_pkt_rate,latency,unstable" > $OUT
RATES="0.10 0.15 0.20 0.25 0.30 0.35 0.40 0.45 0.50 0.55 0.60 0.65 0.70 0.75 0.80 0.85 0.90"

run_one () {
  local routing=$1 mode=$2 o=$3 d=$4 rate=$5
  cat > /tmp/adaptive_test.config <<EOF
topology = gec;
routing_function = $routing;
k = 7;
c = 1;
o = $o;
d = $d;
mesh = 0;
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
  out=$(timeout 30 ./booksim /tmp/adaptive_test.config 2>&1)
  inj=$(echo "$out" | grep "Injected packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  acc=$(echo "$out" | grep "Accepted packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  lat=$(echo "$out" | grep "^Packet latency average" | tail -1 | sed 's/.*= //;s/ .*//')
  unstable=$(echo "$out" | grep -c "unstable")
  echo "$routing,$mode,$o,$d,$rate,$inj,$acc,$lat,$unstable" >> $OUT
}

for rate in $RATES; do
  run_one dor express 6 1 $rate
  run_one adaptive_xy_yx express 6 1 $rate
  run_one dor mecs 1 6 $rate
  run_one adaptive_xy_yx mecs 1 6 $rate
done
echo "DONE: $OUT"
wc -l $OUT

#!/bin/bash
# MECS-only (k=4, c=1, o=1, d=3 -- matches mecs_gec.config), num_vcs=3
# fixed (= d, i.e. exactly 1 VC per shared tap -- the minimum GEC allows),
# vc_buf_size swept, injection_rate 0.10-0.90 step 0.05, traffic_matrix.txt
# (not uniform) as the actual traffic pattern.
cd /home/sowmith/booksim2/src
OUT=/home/sowmith/booksim2/results_vcbuf_matrix.csv
echo "topology,k,o,d,num_vcs,vc_buf_size,injection_rate,injected_pkt_rate,accepted_pkt_rate,latency,unstable,build_error" > $OUT
RATES="0.10 0.15 0.20 0.25 0.30 0.35 0.40 0.45 0.50 0.55 0.60 0.65 0.70 0.75 0.80 0.85 0.90"

run_one () {
  local vcbuf=$1 rate=$2
  cat > /tmp/study_test_matrix.config <<EOF
topology = gec;
routing_function = dor;
k = 4;
c = 1;
o = 1;
d = 3;
mesh = 0;
num_vcs = 3;
vc_buf_size = $vcbuf;
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
traffic = matrix(../traffic_matrix.txt);
packet_size = 5;
injection_rate = $rate;
sim_type = latency;
warmup_periods = 3;
sample_period = 2000;
sim_count = 1;
EOF
  out=$(timeout 30 ./booksim /tmp/study_test_matrix.config 2>&1)
  build_err=$(echo "$out" | grep -c "GEC config error\|Error:")
  inj=$(echo "$out" | grep "Injected packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  acc=$(echo "$out" | grep "Accepted packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  lat=$(echo "$out" | grep "^Packet latency average" | tail -1 | sed 's/.*= //;s/ .*//')
  unstable=$(echo "$out" | grep -c "unstable")
  echo "MECS_o1d3,4,1,3,3,$vcbuf,$rate,$inj,$acc,$lat,$unstable,$build_err" >> $OUT
}

for vcbuf in 2 4 6 8 12 16 24; do
  for rate in $RATES; do
    run_one $vcbuf $rate
  done
done
echo "DONE: $OUT"
wc -l $OUT

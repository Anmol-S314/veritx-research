#!/bin/bash
# MECS-only (k=7, c=1, o=1, d=6 -- pure MECS, whole row/column on one
# shared channel per direction) num_vcs sensitivity, vc_buf_size=8 fixed,
# injection_rate 0.10-0.90 step 0.05. Hard floor is num_vcs>=d=6.
cd /home/sowmith/booksim2/src
OUT=/home/sowmith/booksim2/results_numvcs.csv
echo "topology,k,o,d,num_vcs,vc_buf_size,injection_rate,injected_pkt_rate,accepted_pkt_rate,latency,unstable,build_error" > $OUT
RATES="0.10 0.15 0.20 0.25 0.30 0.35 0.40 0.45 0.50 0.55 0.60 0.65 0.70 0.75 0.80 0.85 0.90"

run_one () {
  local numvcs=$1 rate=$2
  cat > /tmp/study_test2.config <<EOF
topology = gec;
routing_function = dor;
k = 7;
c = 1;
o = 1;
d = 6;
mesh = 0;
num_vcs = $numvcs;
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
traffic = uniform;
packet_size = 5;
injection_rate = $rate;
sim_type = latency;
warmup_periods = 3;
sample_period = 2000;
sim_count = 1;
EOF
  out=$(timeout 30 ./booksim /tmp/study_test2.config 2>&1)
  build_err=$(echo "$out" | grep -c "GEC config error\|Error:")
  inj=$(echo "$out" | grep "Injected packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  acc=$(echo "$out" | grep "Accepted packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  lat=$(echo "$out" | grep "^Packet latency average" | tail -1 | sed 's/.*= //;s/ .*//')
  unstable=$(echo "$out" | grep -c "unstable")
  echo "MECS_o1d6,7,1,6,$numvcs,8,$rate,$inj,$acc,$lat,$unstable,$build_err" >> $OUT
}

for numvcs in 6 8 10 12 16 20; do
  for rate in $RATES; do
    run_one $numvcs $rate
  done
done
echo "DONE: $OUT"
wc -l $OUT

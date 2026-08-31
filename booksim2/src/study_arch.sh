#!/bin/bash
# Experiment 5: router architecture knobs -- input_speedup/output_speedup
# (crossbar parallelism) and alloc_iters (iSLIP allocator iterations).
# MECS o=1,d=6,k=7, num_vcs=8, vc_buf_size=8, packet_size=5.
# injection_rate 0.10-0.90 step 0.05.
cd /home/sowmith/booksim2/src
OUT=/home/sowmith/booksim2/results_arch.csv
echo "experiment,topology,k,o,d,num_vcs,vc_buf_size,input_speedup,output_speedup,alloc_iters,injection_rate,injected_pkt_rate,accepted_pkt_rate,latency,unstable,build_error" > $OUT
RATES="0.10 0.15 0.20 0.25 0.30 0.35 0.40 0.45 0.50 0.55 0.60 0.65 0.70 0.75 0.80 0.85 0.90"

run_one () {
  local ispeed=$1 ospeed=$2 iters=$3 rate=$4
  cat > /tmp/study_test5.config <<EOF
topology = gec;
routing_function = dor;
k = 7;
c = 1;
o = 1;
d = 6;
mesh = 0;
num_vcs = 8;
vc_buf_size = 8;
wait_for_tail_credit = 0;
vc_allocator = islip;
sw_allocator = islip;
alloc_iters = $iters;
routing_delay = 1;
vc_alloc_delay = 1;
sw_alloc_delay = 1;
credit_delay = 1;
st_prepare_delay = 0;
st_final_delay = 1;
input_speedup = $ispeed;
output_speedup = $ospeed;
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
  out=$(timeout 30 ./booksim /tmp/study_test5.config 2>&1)
  build_err=$(echo "$out" | grep -c "GEC config error\|Error:")
  inj=$(echo "$out" | grep "Injected packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  acc=$(echo "$out" | grep "Accepted packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  lat=$(echo "$out" | grep "^Packet latency average" | tail -1 | sed 's/.*= //;s/ .*//')
  unstable=$(echo "$out" | grep -c "unstable")
  echo "arch,MECS_o1d6,7,1,6,8,8,$ispeed,$ospeed,$iters,$rate,$inj,$acc,$lat,$unstable,$build_err" >> $OUT
}

# speedup sweep (alloc_iters fixed at 1)
for sp in "1 1" "2 1" "1 2" "2 2"; do
  isp=$(echo $sp | cut -d' ' -f1)
  osp=$(echo $sp | cut -d' ' -f2)
  for rate in $RATES; do
    run_one $isp $osp 1 $rate
  done
done
# alloc_iters sweep (speedup fixed at 1,1)
for iters in 2 4; do
  for rate in $RATES; do
    run_one 1 1 $iters $rate
  done
done
echo "DONE: $OUT"
wc -l $OUT

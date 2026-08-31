#!/bin/bash
# Experiment 4: packet_size sensitivity, MECS o=1,d=6,k=7, num_vcs=8,
# vc_buf_size=8. injection_rate 0.10-0.90 step 0.05. packet_size changes
# where the terminal 1-flit/cycle ceiling falls in packet-rate terms
# (ceiling = 1/packet_size packets/cycle), which is exactly what we want
# to see quantified directly instead of inferred.
cd /home/sowmith/booksim2/src
OUT=/home/sowmith/booksim2/results_packetsize.csv
echo "experiment,topology,k,o,d,num_vcs,vc_buf_size,packet_size,injection_rate,injected_pkt_rate,accepted_pkt_rate,injected_flit_rate,accepted_flit_rate,latency,unstable,build_error" > $OUT
RATES="0.10 0.15 0.20 0.25 0.30 0.35 0.40 0.45 0.50 0.55 0.60 0.65 0.70 0.75 0.80 0.85 0.90"

run_one () {
  local pktsize=$1 rate=$2
  cat > /tmp/study_test4.config <<EOF
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
packet_size = $pktsize;
injection_rate = $rate;
sim_type = latency;
warmup_periods = 3;
sample_period = 2000;
sim_count = 1;
EOF
  out=$(timeout 30 ./booksim /tmp/study_test4.config 2>&1)
  build_err=$(echo "$out" | grep -c "GEC config error\|Error:")
  inj=$(echo "$out" | grep "Injected packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  acc=$(echo "$out" | grep "Accepted packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  injf=$(echo "$out" | grep "Injected flit rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  accf=$(echo "$out" | grep "Accepted flit rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  lat=$(echo "$out" | grep "^Packet latency average" | tail -1 | sed 's/.*= //;s/ .*//')
  unstable=$(echo "$out" | grep -c "unstable")
  echo "packetsize,MECS_o1d6,7,1,6,8,8,$pktsize,$rate,$inj,$acc,$injf,$accf,$lat,$unstable,$build_err" >> $OUT
}

for pktsize in 1 3 5 8; do
  for rate in $RATES; do
    run_one $pktsize $rate
  done
done
echo "DONE: $OUT"
wc -l $OUT

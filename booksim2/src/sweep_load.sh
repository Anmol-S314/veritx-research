#!/bin/bash
# o,d sweep at fixed k with multi-flit packets (packet_size=5) -- this is
# the realistic case (packet_size=1 makes every flit a head flit, which
# masks any bug in how body/tail flits get routed onto a shared channel).
cd /home/sowmith/booksim2/src
K=7
for od in "6 1" "3 2" "2 3" "1 6"; do
  o=$(echo $od | cut -d' ' -f1)
  d=$(echo $od | cut -d' ' -f2)
  echo "==================== o=$o d=$d (k=$K) ===================="
  for rate in 0.05 0.10 0.20 0.30 0.50 0.70 0.90 1.00; do
    cat > /tmp/gec_load_test <<EOF
topology = gec;
routing_function = dor;
k = $K;
c = 1;
o = $o;
d = $d;
mesh = 0;
num_vcs = $((d<8?8:d));
vc_buf_size = 8;
use_noc_latency = 0;
traffic = uniform;
packet_size = 5;
injection_rate = $rate;
sim_type = latency;
warmup_periods = 3;
sample_period = 2000;
sim_count = 1;
EOF
    out=$(./booksim /tmp/gec_load_test 2>&1)
    inj=$(echo "$out" | grep "Injected packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
    acc=$(echo "$out" | grep "Accepted packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
    lat=$(echo "$out" | grep "^Packet latency average" | tail -1 | sed 's/.*= //;s/ .*//')
    err=$(echo "$out" | grep -c "Error in network\|Assertion")
    unstable=$(echo "$out" | grep -c "unstable")
    echo "  rate=$rate  injected=$inj  accepted=$acc  latency=$lat  unstable=$unstable  errors=$err"
  done
done

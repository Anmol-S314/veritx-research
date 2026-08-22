#!/bin/bash
cd /home/sowmith/booksim2/src
for k in 4 5 8; do
  d=$((k-1))
  cat > /tmp/gec_mecs_k$k <<EOF
topology = gec;
routing_function = dor;
k = $k;
c = 1;
o = 1;
d = $d;
mesh = 0;
num_vcs = $d;
vc_buf_size = 8;
use_noc_latency = 0;
traffic = uniform;
injection_rate = 0.01;
sim_type = latency;
warmup_periods = 2;
sample_period = 2000;
sim_count = 1;
EOF
  echo "--- pure MECS k=$k (o=1,d=$d) ---"
  ./booksim /tmp/gec_mecs_k$k 2>&1 | grep '^GEC:'
done
for k in 4 5 8; do
  o=$((k-1))
  cat > /tmp/gec_express_k$k <<EOF
topology = gec;
routing_function = dor;
k = $k;
c = 1;
o = $o;
d = 1;
mesh = 0;
num_vcs = 4;
vc_buf_size = 8;
use_noc_latency = 0;
traffic = uniform;
injection_rate = 0.01;
sim_type = latency;
warmup_periods = 2;
sample_period = 2000;
sim_count = 1;
EOF
  echo "--- express k=$k (o=k-1,d=1) ---"
  ./booksim /tmp/gec_express_k$k 2>&1 | grep '^GEC:'
done

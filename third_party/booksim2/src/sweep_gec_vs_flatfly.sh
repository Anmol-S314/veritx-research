#!/bin/bash
# Matched-parameter comparison: GEC in its express (d=1, full row/column
# point-to-point) mode vs BookSim's native flatfly topology, at the same
# k/c (same node count, same radix c+2(k-1)), same router timing knobs,
# same VC/buffer resources, same routing sophistication (both dor_gec and
# min_flatfly are deterministic single-path dimension-order routing --
# min_flatfly's "ran" prefix is a stale name, flatfly_outport() in
# flatfly_onchip.cpp is not actually randomized), swept across injection
# rates with uniform traffic. If GEC's graph/channel/router construction
# is correct, injected/accepted/latency should track flatfly closely at
# every rate.
cd /home/sowmith/booksim2/src

K=4
C=1
NUM_VCS=8
VC_BUF_SIZE=8
PKT_SIZE=5

COMMON="
num_vcs = $NUM_VCS;
vc_buf_size = $VC_BUF_SIZE;
packet_size = $PKT_SIZE;
use_noc_latency = 0;
routing_delay = 1;
vc_alloc_delay = 1;
sw_alloc_delay = 1;
credit_delay = 1;
st_prepare_delay = 0;
st_final_delay = 1;
input_speedup = 1;
output_speedup = 1;
internal_speedup = 1.0;
vc_allocator = islip;
sw_allocator = islip;
alloc_iters = 1;
wait_for_tail_credit = 0;
hold_switch_for_packet = 0;
buffer_policy = private;
channel_width = 128;
traffic = uniform;
sim_type = latency;
warmup_periods = 3;
sample_period = 2000;
sim_count = 1;
"

cat > /tmp/gec_test <<EOF
topology = gec;
routing_function = dor;
k = $K;
c = $C;
o = $((K-1));
d = 1;
mesh = 0;
$COMMON
EOF

cat > /tmp/flatfly_test <<EOF
topology = flatfly;
subnets = 1;
routing_function = ran_min;
k = $K;
n = 2;
c = $C;
x = $K;
y = $K;
xr = 1;
yr = 1;
use_read_write = 0;
$COMMON
EOF

printf "%-8s | %-32s | %-32s | %s\n" "rate" "GEC (inj/acc/lat)" "flatfly (inj/acc/lat)" "match?"
printf -- '-%.0s' $(seq 1 100); echo

for rate in 0.05 0.10 0.20 0.30 0.40 0.50 0.60 0.70 0.80 0.90; do
  echo "injection_rate = $rate;" >> /tmp/gec_test
  echo "injection_rate = $rate;" >> /tmp/flatfly_test

  gec_out=$(./booksim /tmp/gec_test 2>&1)
  fly_out=$(./booksim /tmp/flatfly_test 2>&1)

  # strip the rate line back off so it can be re-appended next iteration
  head -n -1 /tmp/gec_test > /tmp/gec_test.tmp && mv /tmp/gec_test.tmp /tmp/gec_test
  head -n -1 /tmp/flatfly_test > /tmp/flatfly_test.tmp && mv /tmp/flatfly_test.tmp /tmp/flatfly_test

  gi=$(echo "$gec_out" | grep "Injected packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  ga=$(echo "$gec_out" | grep "Accepted packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  gl=$(echo "$gec_out" | grep "^Packet latency average" | tail -1 | sed 's/.*= //;s/ .*//')
  gu=$(echo "$gec_out" | grep -c "unstable")

  fi=$(echo "$fly_out" | grep "Injected packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  fa=$(echo "$fly_out" | grep "Accepted packet rate average" | tail -1 | sed 's/.*= //;s/ .*//')
  fl=$(echo "$fly_out" | grep "^Packet latency average" | tail -1 | sed 's/.*= //;s/ .*//')
  fu=$(echo "$fly_out" | grep -c "unstable")

  match="?"
  if [ "$gu" = "$fu" ]; then
    close=$(echo "$gl $fl" | awk '{d=($1-$2); if(d<0)d=-d; m=($1>$2)?$1:$2; if(m<1)m=1; print (d/m<0.15)?"yes":"no"}')
    match=$close
  else
    match="no (stability differs: gec_unstable=$gu fly_unstable=$fu)"
  fi

  printf "%-8s | inj=%-8s acc=%-8s lat=%-8s | inj=%-8s acc=%-8s lat=%-8s | %s\n" \
    "$rate" "$gi" "$ga" "$gl" "$fi" "$fa" "$fl" "$match"
done

// Smoke test: multicast fold on the REAL bridged_2die fabric (2x8x8 + bridge,
// anynet min-hop routing). Verifies copies eject along the route path —
// including a CROSS-DIE stream (die-A col-0 down the bridge column to die B).
#include <iostream>
#include <vector>
#include "veritx_embed.hpp"

using namespace VeritXEmbed;

static EmbedTM * tm;

static int wait_for(std::vector<int> const & dsts, int guard_limit) {
  int guard = 0;
  bool all = false;
  while (!all && guard++ < guard_limit) {
    tm->RunCycles(1024);
    all = true;
    for (int d : dsts)
      if (!tm->HasRetired(d)) { all = false; break; }
  }
  return guard;
}

int main() {
  tm = CreateEmbeddedTM(
      "/var/tmp/r1work/fixed_anynet/bridged_2die_fixed.cfg",
      {"injection_rate=0.0", "packet_size=1", "sample_period=100000",
       "warmup_periods=0", "max_samples=1", "sim_count=1"});
  if (!tm) { std::cerr << "create FAILED\n"; return 1; }
  std::cout << "bridged_2die fabric up, nodes=" << tm->NumNodes() << "\n";

  // ---- 1) die-A row multicast: root 0 -> cols 1..7 of row 0 ----
  std::vector<int> row_dsts{1, 2, 3, 4, 5, 6, 7};
  tm->RunCycles(10);
  for (int i = 0; i < 100; ++i) tm->InjectMcast(0, row_dsts, 0);
  int g = wait_for(row_dsts, 2000000);
  int total = 0;
  for (int d : row_dsts) total += (int)tm->DrainRetired(d).size();
  std::cout << "ROW-MCAST 0->{1..7}: far-end retired after " << g
            << " chunks, deliveries " << total << "/700 (expect 700)\n";
  if (total != 700) return 1;

  // ---- 2) CROSS-DIE multicast: root 0 -> col-0 column of die B ----
  // route 0->64: 0,8,16,24,32,40,48,56,(bridge),64 — copies 8..56 on die A,
  // far end 64 on die B. ONE injection, 8 deliveries across the bridge.
  std::vector<int> xdie_dsts{8, 16, 24, 32, 40, 48, 56, 64};
  tm->RunCycles(10);
  for (int i = 0; i < 100; ++i) tm->InjectMcast(0, xdie_dsts, 0);
  g = wait_for(xdie_dsts, 2000000);
  total = 0;
  for (int d : xdie_dsts) total += (int)tm->DrainRetired(d).size();
  std::cout << "CROSS-DIE MCAST 0->{8,16,24,32,40,48,56,64}: after " << g
            << " chunks, deliveries " << total << "/800 (expect 800)\n";
  if (total != 800) return 1;

  // ---- 3) die-B row multicast: root 64 -> cols 1..7 of die-B row 0 ----
  std::vector<int> b_row{65, 66, 67, 68, 69, 70, 71};
  tm->RunCycles(10);
  for (int i = 0; i < 100; ++i) tm->InjectMcast(64, b_row, 0);
  g = wait_for(b_row, 2000000);
  total = 0;
  for (int d : b_row) total += (int)tm->DrainRetired(d).size();
  std::cout << "DIE-B ROW-MCAST 64->{65..71}: after " << g
            << " chunks, deliveries " << total << "/700 (expect 700)\n";
  if (total != 700) return 1;

  std::cout << "ALL BRIDGED_2DIE MULTICAST TESTS PASS\n";
  return 0;
}

// Smoke test for the VeritXEmbed API: external unicast + row-multicast.
#include <iostream>
#include <vector>
#include "veritx_embed.hpp"

using namespace VeritXEmbed;

int main() {
  EmbedTM * tm = CreateEmbeddedTM(
      "/var/tmp/r1work/booksim2-embed/src/examples/mesh88_lat",
      {"injection_rate=0.0", "traffic=uniform", "packet_size=4",
       "sim_count=1", "sample_period=10000", "warmup_periods=0"});
  if (!tm) { std::cerr << "CreateEmbeddedTM FAILED\n"; return 1; }

  // ---- unicast: node 0 -> node 9, 4 flits ----
  tm->RunCycles(5);
  tm->InjectUnicast(0, 9, 4, 0);
  int guard = 0;
  while (!tm->HasRetired(9) && guard++ < 100000) tm->RunCycles(1);
  std::vector<Retired> r = tm->DrainRetired(9);
  std::cout << "UNICAST 0->9 size4: retired at cycle "
            << (r.empty() ? -1 : r[0].atime) << " (steps " << guard << "), pid "
            << (r.empty() ? -1 : r[0].pid) << "\n";
  if (r.empty()) return 1;

  // ---- row multicast: node 0 -> {1,2,3,7} along the row path ----
  tm->RunCycles(5);
  tm->InjectMcast(0, std::vector<int>{1, 2, 3, 7}, 0);
  guard = 0;
  while (!tm->HasRetired(7) && guard++ < 100000) tm->RunCycles(1);
  int total = 0;
  for (int d : {1, 2, 3, 7}) {
    int n = tm->DrainRetired(d).size();
    std::cout << "  mcast delivery to node " << d << ": " << n << "\n";
    total += n;
  }
  std::cout << "MCAST 0->{1,2,3,7}: far-end retired at steps " << guard
            << ", total deliveries " << total << " (expect 4)\n";
  return total == 4 ? 0 : 1;
}

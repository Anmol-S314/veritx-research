#include <iostream>
#include <vector>
#include "veritx_embed.hpp"
using namespace VeritXEmbed;
int main() {
  EmbedTM * tm = CreateEmbeddedTM(
      "/home/datavex/veritx-research/tracks/t3-topology/configs/booksim2_configs/bridged_2die.cfg",
      {"injection_rate=0.0", "packet_size=1", "sample_period=100000",
       "warmup_periods=0", "max_samples=1", "sim_count=1"});
  std::cout << "fabric up nodes=" << tm->NumNodes() << std::endl;
  // cross-die: die-A root 0 -> die-B col-0 column. Route 0->64 via bridge.
  std::vector<int> xdie{8, 16, 24, 32, 40, 48, 56, 64};
  tm->RunCycles(10);
  for (int i = 0; i < 10; ++i) tm->InjectMcast(0, xdie, 0);
  for (int g = 0; g < 100000; ++g) {
    tm->RunCycles(1024);
    int n = 0;
    for (int d : xdie) if (tm->HasRetired(d)) n++;
    if (g % 10000 == 0)
      std::cout << "g=" << g << " retired=" << n << std::endl;
    if (n == 8) { std::cout << "CROSS-DIE OK at g=" << g << std::endl; return 0; }
  }
  std::cout << "CROSS-DIE TIMEOUT" << std::endl;
  return 1;
}

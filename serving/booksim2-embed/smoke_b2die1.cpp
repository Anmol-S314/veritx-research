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
  std::vector<int> row_dsts{1, 2, 3, 4, 5, 6, 7};
  tm->RunCycles(10);
  for (int i = 0; i < 10; ++i) tm->InjectMcast(0, row_dsts, 0);
  for (int g = 0; g < 50000; ++g) {
    tm->RunCycles(1024);
    int n = 0;
    for (int d : row_dsts) if (tm->HasRetired(d)) n++;
    if (g % 5000 == 0)
      std::cout << "g=" << g << " retired=" << n << std::endl;
    if (n == 7) { std::cout << "ROW OK at g=" << g << std::endl; return 0; }
  }
  std::cout << "ROW TIMEOUT" << std::endl;
  return 1;
}

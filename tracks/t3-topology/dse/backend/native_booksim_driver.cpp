// Bounded host protocol around the actual VeritX BookSim embed API.
#include "veritx_embed.hpp"
#include "random_utils.hpp"
#include <cstdio>
#include <iostream>
#include <memory>
#include <sstream>
#include <unistd.h>

int main(int argc, char **argv) {
  if (argc != 3) return 2;
  // Native diagnostics (including printf) must not corrupt the wire protocol.
  FILE *wire = fdopen(dup(STDOUT_FILENO), "w");
  if (!wire || dup2(STDERR_FILENO, STDOUT_FILENO) < 0) return 3;
  try {
    RandomSeed(0);
    std::unique_ptr<VeritXEmbed::EmbedTM> tm(VeritXEmbed::CreateEmbeddedTM(argv[1], {}));
    if (!tm) return 4;
    tm->SetHostFlitLimit(std::stoll(argv[2]));
    fprintf(wire, "NODES %d\n", tm->NumNodes()); fflush(wire);
    std::string line;
    while (std::getline(std::cin, line)) {
      std::istringstream in(line); std::string op; in >> op;
      if (op == "inject") {
        int s, d, z, c;
        if (!(in >> s >> d >> z >> c)) throw std::invalid_argument("bad injection");
        fprintf(wire, "PID %d\n", tm->InjectUnicast(s, d, z, c));
      } else if (op == "step") {
        tm->RunCycles(1); fprintf(wire, "CYCLE %lld\n", (long long)tm->Cycle());
      } else if (op == "drain") {
        int n;
        if (!(in >> n) || n < 0 || n >= tm->NumNodes()) throw std::invalid_argument("bad node");
        for (auto const &r : tm->DrainRetired(n))
          fprintf(wire, "RET %d %d %d %d %lld %lld\n", r.pid, r.src, r.dst, r.cl,
                  (long long)r.itime, (long long)r.atime);
        fprintf(wire, "END\n");
      } else if (op == "counts") {
        fprintf(wire, "COUNTS %lld %lld %lld %lld %lld %lld\n",
                (long long)tm->PacketsRequested(), (long long)tm->UnicastFlitsConstructed(),
                (long long)tm->FlitsRetired(), (long long)tm->TailDeliveriesRecorded(),
                (long long)tm->InFlightFlitCount(), (long long)tm->PartialQueueFlitCount());
      } else if (op == "quit") {
        fprintf(wire, "BYE\n"); fflush(wire); break;
      } else throw std::invalid_argument("unknown command");
      fflush(wire);
    }
  } catch (std::exception const &e) {
    fprintf(wire, "ERR %s\n", e.what()); fflush(wire); fclose(wire); return 5;
  }
  fclose(wire); return 0;
}

// Bounded host protocol around the actual VeritX BookSim embed API.
#include "veritx_embed.hpp"
#include "random_utils.hpp"
#include <cstdio>
#include <iostream>
#include <memory>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <unistd.h>

int main(int argc, char **argv) {
  if (argc != 3) return 2;
  // Native diagnostics (including printf) must not corrupt the wire protocol.
  FILE *wire = fdopen(dup(STDOUT_FILENO), "w");
  if (!wire || dup2(STDERR_FILENO, STDOUT_FILENO) < 0) return 3;
  struct McastRequest {
    std::string operation;
    int src;
    int cl;
    std::vector<int> destinations;
    std::set<int> seen;
  };
  try {
    RandomSeed(0);
    std::unique_ptr<VeritXEmbed::EmbedTM> tm(VeritXEmbed::CreateEmbeddedTM(argv[1], {}));
    if (!tm) return 4;
    tm->SetHostFlitLimit(std::stoll(argv[2]));
    std::map<int, McastRequest> multicast;
    fprintf(wire, "NODES %d\n", tm->NumNodes()); fflush(wire);
    std::string line;
    while (std::getline(std::cin, line)) {
      std::istringstream in(line); std::string op; in >> op;
      if (op == "inject") {
        int s, d, z, c;
        if (!(in >> s >> d >> z >> c)) throw std::invalid_argument("bad injection");
        fprintf(wire, "PID %d\n", tm->InjectUnicast(s, d, z, c));
      } else if (op == "inject_mcast") {
        std::string operation; int src, replication, cl, fanout;
        if (!(in >> operation >> src >> replication >> cl >> fanout)
            || operation.empty() || operation.size() > 256
            || operation.size() % 2 != 0
            || src != replication || fanout < 2 || fanout >= tm->NumNodes())
          throw std::invalid_argument("bad authored multicast binding");
        for (unsigned char ch : operation)
          if (!((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f')))
            throw std::invalid_argument("multicast operation id must be lowercase hex");
        std::vector<int> destinations; std::set<int> unique;
        for (int i = 0; i < fanout; ++i) {
          int dst;
          if (!(in >> dst) || dst < 0 || dst >= tm->NumNodes()
              || dst == src || !unique.insert(dst).second)
            throw std::invalid_argument("invalid or duplicate multicast destination");
          destinations.push_back(dst);
        }
        std::string extra;
        if (in >> extra) throw std::invalid_argument("extra multicast request fields");
        for (auto const &entry : multicast)
          if (entry.second.operation == operation)
            throw std::invalid_argument("multicast operation id was injected twice");
        int const pid = tm->InjectMcast(src, destinations, cl);
        if (pid < 0) {
          fprintf(wire, "MADMIT\n");
        } else {
          McastRequest request{operation, src, cl, destinations, {}};
          if (!multicast.insert(std::make_pair(pid, request)).second)
            throw std::logic_error("duplicate native multicast PID");
          fprintf(wire, "MPID %d %s\n", pid, operation.c_str());
        }
      } else if (op == "step") {
        tm->RunCycles(1); fprintf(wire, "CYCLE %lld\n", (long long)tm->Cycle());
      } else if (op == "drain") {
        int n;
        if (!(in >> n) || n < 0 || n >= tm->NumNodes()) throw std::invalid_argument("bad node");
        for (auto const &r : tm->DrainRetired(n)) {
          auto request = multicast.find(r.pid);
          if (request == multicast.end()) {
            if (r.multicast)
              throw std::logic_error("multicast retirement has no authored operation binding");
            fprintf(wire, "RET %d %d %d %d %lld %lld\n", r.pid, r.src, r.dst, r.cl,
                    (long long)r.itime, (long long)r.atime);
            continue;
          }
          McastRequest &m = request->second;
          if (!r.multicast || r.src != m.src || r.cl != m.cl
              || r.branch_id < 0 || r.branch_id >= (int)m.destinations.size()
              || m.destinations[r.branch_id] != r.dst
              || !m.seen.insert(r.dst).second)
            throw std::logic_error("native multicast branch mismatched or retired more than once");
          fprintf(wire, "MRET %s %d %d %d %d %lld %lld %d %d %d %lu",
                  m.operation.c_str(), r.pid, r.src, r.dst, r.cl,
                  (long long)r.itime, (long long)r.atime,
                  r.branch_id, r.route_steps, r.physical_link_flits,
                  (unsigned long)r.route_trace.size());
          for (auto const &link : r.route_trace)
            fprintf(wire, " %d %d", link.first, link.second);
          fprintf(wire, "\n");
        }
        fprintf(wire, "END\n");
      } else if (op == "counts") {
        fprintf(wire, "COUNTS %lld %lld %lld %lld %lld %lld\n",
                (long long)tm->PacketsRequested(), (long long)tm->UnicastFlitsConstructed(),
                (long long)tm->FlitsRetired(), (long long)tm->TailDeliveriesRecorded(),
                (long long)tm->InFlightFlitCount(), (long long)tm->PartialQueueFlitCount());
        fprintf(wire, "MCOUNTS %lld %lld %lld\n",
                (long long)tm->McastBranchFlitsConstructed(),
                (long long)tm->McastBranchFlitsRetired(),
                (long long)tm->McastBranchPhysicalLinkFlitsRetired());
      } else if (op == "quit") {
        for (auto const &entry : multicast)
          if (entry.second.seen.size() != entry.second.destinations.size())
            throw std::logic_error("native multicast operation did not retire every authored branch");
        fprintf(wire, "BYE\n"); fflush(wire); break;
      } else throw std::invalid_argument("unknown command");
      fflush(wire);
    }
  } catch (std::exception const &e) {
    fprintf(wire, "ERR %s\n", e.what()); fflush(wire); fclose(wire); return 5;
  }
  fclose(wire); return 0;
}

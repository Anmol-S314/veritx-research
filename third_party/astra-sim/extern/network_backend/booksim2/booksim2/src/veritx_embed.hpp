#ifndef _VERITX_EMBED_HPP_
#define _VERITX_EMBED_HPP_

// VeritX embedding API: drive this booksim2 fork as a cycle-accurate fabric
// from an external host (the ASTRA-sim network backend).
//
// The pattern mirrors main.cpp's setup (ParseArgs -> InitializeRoutingMap ->
// Network::New -> TrafficManager::New) but instantiates EmbedTM, a
// TrafficManager subclass that (a) steps in caller-controlled chunks
// (RunCycles), (b) accepts externally injected packets with arbitrary
// (src, dst, size, cl) at the current cycle (InjectUnicast / InjectMcast),
// and (c) reports packet completions per node via retire queues
// (HasRetired / DrainRetired). Base traffic-pattern generation is disabled
// (zero injection rate in the cfg); every packet comes from the host.

#include <string>
#include <vector>

#include "booksim_config.hpp"
#include "trafficmanager.hpp"

namespace VeritXEmbed {

struct Retired {
  int atime;  // retirement cycle (== fabric cycle at the end of the step)
  int cl;     // traffic class
  int src;    // source node
  int dst;    // node at which the packet retired
  int pid;    // packet id (fabric-wide)
  int itime;  // injection cycle (head flit ctime)
};

class EmbedTM : public TrafficManager {
public:
  EmbedTM(BookSimConfig const & config, std::vector<Network *> const & net);

  void RunCycles(int cycles);
  int Cycle() const { return _time; }
  int NumNodes() const { return _nodes; }

  // Inject a unicast packet of `size` flits at the CURRENT cycle.
  void InjectUnicast(int src, int dst, int size, int cl);

  // Inject one multicast stream delivering single-flit copies to every node
  // in `dsts` (fork at the routers along the stream's path; far-end dest is
  // dsts.back()). Requires single-flit deliveries (size 1 per dest).
  void InjectMcast(int src, std::vector<int> const & dsts, int cl);

  // True while any generated flit is still unretired (injection queues,
  // buffers, or in flight). Lets the host keep stepping until the fabric
  // drains — the ASTRA-sim event loop's liveness condition.
  bool HasInFlight() const {
    for (int c = 0; c < _classes; ++c)
      if (!_total_in_flight_flits[c].empty()) return true;
    return false;
  }

  bool HasRetired(int node) const { return !_retired_q[node].empty(); }
  std::vector<Retired> DrainRetired(int node);

protected:
  void _RetireFlit(Flit * f, int dest) override;

private:
  void _BuildUnicast(int src, int dst, int size, int cl, int time);
  void _BuildMcastStream(int src, std::vector<int> const & dsts, int cl,
                         int time);

  std::vector<std::vector<Retired> > _retired_q;
};

// Build the full fabric (networks + EmbedTM) from a booksim cfg file path.
// `overrides` are "param=value" strings applied after the file, exactly like
// the CLI (main.cpp ParseArgs semantics). Caller owns the returned pointer.
EmbedTM * CreateEmbeddedTM(std::string const & cfg_file,
                           std::vector<std::string> const & overrides);

}  // namespace VeritXEmbed

#endif  // _VERITX_EMBED_HPP_

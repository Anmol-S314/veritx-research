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
  int64_t atime;  // retirement cycle (== fabric cycle at the end of the step)
  int cl;     // traffic class
  int src;    // source node
  int dst;    // node at which the packet retired
  int pid;    // packet id (fabric-wide)
  int64_t itime;  // injection cycle (head flit ctime)
};

class EmbedTM : public TrafficManager {
public:
  EmbedTM(BookSimConfig const & config, std::vector<Network *> const & net);

  void RunCycles(int64_t cycles);
  // Advance the fabric clock by `cycles` WITHOUT stepping the network.
  // Only valid while the fabric is idle (no in-flight flits); used to keep
  // the fabric timebase synchronized with the host event queue across idle
  // (agentic tool-gap) clock jumps, which otherwise desync the DP ALLTOALL
  // wave barrier and deadlock the binary.
  void JumpCycles(int64_t cycles) { assert(!HasInFlight()); _time += cycles; }
  int64_t Cycle() const { return _time; }
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

  // VeritX: per-packet latency / hop summary over every recorded retirement
  // (all classes). Populated only when flits carry record=true (the embed
  // builders set it); empty summary when no packets retired. Percentiles
  // are exact (sorted vector, nearest-rank), not estimated.
  struct PlatSummary {
    int64_t count = 0;
    double avg = 0.0, min = 0.0, p50 = 0.0, p95 = 0.0, p99 = 0.0, max = 0.0;
    double hops_avg = 0.0;
    int hops_min = 0, hops_max = 0;
  };
  PlatSummary PlatStats() const;

  // VeritX ledger diagnostics: cheap counters/snapshots over
  // traffic-manager state, used by the frontend LEDGER dumps. All O(1)
  // except the two scans, which are O(in-flight) and only run on the
  // diagnostic path.
  int64_t InFlightFlitCount() const {
    int64_t n = 0;
    for (size_t c = 0; c < _total_in_flight_flits.size(); ++c)
      n += (int64_t)_total_in_flight_flits[c].size();
    return n;
  }
  int64_t PartialQueueFlitCount() const {
    int64_t n = 0;
    for (size_t s = 0; s < _partial_packets.size(); ++s)
      for (size_t c = 0; c < _partial_packets[s].size(); ++c)
        n += (int64_t)_partial_packets[s][c].size();
    return n;
  }
  int64_t PacketsRequested() const { return _packets_requested; }
  int64_t UnicastFlitsConstructed() const { return _unicast_flits; }
  int64_t McastDeliveriesConstructed() const { return _mcast_deliveries; }
  int64_t FlitsRetired() const { return _flits_retired; }
  int64_t TailDeliveriesRecorded() const { return _tails_retired; }
  // Oldest in-flight flit by injection (head-flit ctime); false if idle.
  bool SampleOldestInFlight(int & id, int & src, int & dst,
                            int64_t & ctime, int64_t & itime, bool & head,
                            bool & tail, int & vc) const {
    bool found = false;
    int64_t best = 0;
    for (size_t c = 0; c < _total_in_flight_flits.size(); ++c) {
      for (std::map<int, Flit *>::const_iterator it =
               _total_in_flight_flits[c].begin();
           it != _total_in_flight_flits[c].end(); ++it) {
        Flit const * f = it->second;
        if (!found || f->ctime < best) {
          found = true;
          best = f->ctime;
          id = f->id;
          src = f->src;
          dst = f->dest;
          ctime = f->ctime;
          itime = f->itime;
          head = f->head;
          tail = f->tail;
          vc = f->vc;
        }
      }
    }
    return found;
  }

protected:
  void _RetireFlit(Flit * f, int dest) override;

private:
  void _BuildUnicast(int src, int dst, int size, int cl, int64_t time);
  void _BuildMcastStream(int src, std::vector<int> const & dsts, int cl,
                         int64_t time);

  std::vector<std::vector<Retired> > _retired_q;
  // Cumulative ledger counters (monotonic; never drained).
  int64_t _packets_requested = 0;
  int64_t _unicast_flits = 0;
  int64_t _mcast_deliveries = 0;
  int64_t _flits_retired = 0;
  int64_t _tails_retired = 0;
};

// Build the full fabric (networks + EmbedTM) from a booksim cfg file path.
// `overrides` are "param=value" strings applied after the file, exactly like
// the CLI (main.cpp ParseArgs semantics). Caller owns the returned pointer.
EmbedTM * CreateEmbeddedTM(std::string const & cfg_file,
                           std::vector<std::string> const & overrides);

}  // namespace VeritXEmbed

#endif  // _VERITX_EMBED_HPP_

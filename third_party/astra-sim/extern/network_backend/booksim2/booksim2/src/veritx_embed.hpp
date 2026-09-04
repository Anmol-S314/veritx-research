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
#include <iostream>

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
  // Lifecycle ledger (observability only; does not affect simulation).
  int64_t PacketsRequested() const { return _packets_requested; }
  int64_t UnicastFlitsConstructed() const { return _unicast_flits_constructed; }
  int64_t McastDeliveriesConstructed() const {
    return _mcast_deliveries_constructed;
  }
  int64_t FlitsRetired() const { return _flits_retired; }
  int64_t TailDeliveriesRecorded() const { return _tail_deliveries_recorded; }
  int64_t PartialQueueFlitCount() const;
  int64_t InFlightFlitCount() const;
  // Copy one currently in-flight flit, preferring the smallest flit id.
  // Returns false when the flight set is empty.
  bool SampleOldestInFlight(int & id, int & src, int & dst, int64_t & ctime,
                            int64_t & itime, bool & head, bool & tail,
                            int & vc) const;
  // Dump one node's injection-side BufferState (per-VC occupancy/holder).
  // Diagnostic for VC-reservation leaks: a VC whose _in_use_by never clears
  // blocks all later packets needing an output VC.
  void DumpInjectBuf(int node) const {
    if (node >= 0 && node < (int)_buf_states.size() && !_buf_states[node].empty() &&
        _buf_states[node][0] != nullptr) {
      _buf_states[node][0]->Display(std::cerr);
    }
  }
  // Advance the fabric clock by `cycles` WITHOUT stepping the network.
  // Only valid while the fabric is idle (no in-flight flits); used to keep
  // the fabric timebase synchronized with the host event queue across idle
  // (agentic tool-gap) clock jumps, which otherwise desync the DP ALLTOALL
  // wave barrier and deadlock the binary.
  void JumpCycles(int64_t cycles) {
    assert(!HasInFlight());
    _time += cycles;
    // VeritX: fast-forward injection clocks too. TrafficManager::_Inject
    // catches a stale _qtime up to _time one cycle per _Step iteration, so a
    // billion-cycle jump would wedge the next _Step for billions of
    // iterations. The fabric is idle (asserted above) with nothing to
    // generate (embed mode synthesizes no demand), so jumping straight is
    // behavior-preserving.
    for (size_t i = 0; i < _qtime.size(); ++i)
      for (size_t c = 0; c < _qtime[i].size(); ++c)
        if (_qtime[i][c] < _time) _qtime[i][c] = _time;
  }
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

protected:
  void _RetireFlit(Flit * f, int dest) override;

private:
  void _BuildUnicast(int src, int dst, int size, int cl, int64_t time);
  void _BuildMcastStream(int src, std::vector<int> const & dsts, int cl,
                         int64_t time);

  std::vector<std::vector<Retired> > _retired_q;

  // Ledger counters: observe host requests, constructed objects, stage
  // occupancy, and completions without changing simulation behavior.
  int64_t _packets_requested = 0;
  int64_t _unicast_flits_constructed = 0;
  int64_t _mcast_deliveries_constructed = 0;
  int64_t _flits_retired = 0;
  int64_t _tail_deliveries_recorded = 0;
};

// Build the full fabric (networks + EmbedTM) from a booksim cfg file path.
// `overrides` are "param=value" strings applied after the file, exactly like
// the CLI (main.cpp ParseArgs semantics). Caller owns the returned pointer.
EmbedTM * CreateEmbeddedTM(std::string const & cfg_file,
                           std::vector<std::string> const & overrides);

}  // namespace VeritXEmbed

#endif  // _VERITX_EMBED_HPP_

#ifndef _TRACETRAFFICMANAGER_HPP_
#define _TRACETRAFFICMANAGER_HPP_

// Drop this file (and tracetrafficmanager.cpp) into booksim2/src/.
// Requires three small patches to trafficmanager.hpp / trafficmanager.cpp —
// see INTEGRATION.md. Everything else here uses BookSim's existing,
// already-virtual extension points, verified directly against
// booksim2/src/trafficmanager.cpp, traffic.cpp, batchtrafficmanager.hpp.

#include <deque>
#include <vector>
#include <map>
#include <fstream>
#include <cstdint>

#include "trafficmanager.hpp"
#include "traffic.hpp"

// One row of the input trace: "at cycle `timestamp`, node `src` sends
// `packet_size` flits to node `dst`". `type`/`transaction_id` are
// pass-through metadata BookSim itself never needs to interpret.
struct TraceEvent {
  uint64_t timestamp;
  int      src;
  int      dst;
  int      packet_size;      // flits
  int      txn_type;         // 0=READ, 1=WRITE, 2=OTHER (metadata only)
  uint64_t transaction_id;
  int      cl = 0;           // traffic class (veritx format carries it; single-class use ignores it)
};

class TraceTrafficManager : public TrafficManager {

protected:

  // One time-ordered queue per source node.
  std::vector<std::deque<TraceEvent> > _trace_queue;

  // BookSim packet id -> the trace event that produced it, so results can
  // be logged per BookSim packet, not just per source.
  std::map<int, TraceEvent> _pid_to_event;

  std::ofstream _packets_csv;

  void _LoadTraceFile(std::string const & filename);

  // ---- Real extension points (see INTEGRATION.md for which of these
  //      need a BookSim source patch to become virtual) ----

  virtual int  _IssuePacket(int source, int cl);                 // WHEN   (already virtual in stock BookSim)
  virtual int  _GetNextPacketSize(int cl) const;                 // SIZE   (needs the `virtual` patch)
  virtual void _OnPacketGenerated(int pid, int source, int cl,   // bookkeeping hook (needs a new patch)
                                   int time);
  virtual void _RetireFlit(Flit * f, int dest);                  // logging (already virtual in stock BookSim)

public:

  TraceTrafficManager(Configuration const & config,
                       vector<Network *> const & net);
  virtual ~TraceTrafficManager();
};

// Replaces the statistical traffic pattern (uniform, transpose, ...) with
// one that simply returns whatever destination the trace queued up for
// this source. Installed directly into TrafficManager's protected
// `_traffic_pattern` vector in the constructor below — no change to
// traffic.cpp's string factory is needed.
//
// Convergence note: the pending event lives IN the pattern object (one
// instance per class), not in the manager. _IssuePacket() stages it here,
// _GeneratePacket() consumes it via dest()/size in the same call chain, so
// the slot always belongs to the (source, class) currently being generated
// — no cross-object temporal coupling, no _last_issue_source routing hack.
class TraceFileTrafficPattern : public TrafficPattern {
private:
  TraceEvent _pending_event;
  bool       _pending_valid = false;
public:
  TraceFileTrafficPattern(int nodes)
    : TrafficPattern(nodes) {}
  void SetPending(TraceEvent const & ev) { _pending_event = ev; _pending_valid = true; }
  void ClearPending() { _pending_valid = false; }
  bool HasPending() const { return _pending_valid; }
  TraceEvent const & Pending() const { return _pending_event; }
  virtual int dest(int source) {
    (void)source;
    return _pending_valid ? _pending_event.dst : 0;
  }
};

#endif

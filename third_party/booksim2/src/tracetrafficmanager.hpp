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
};

class TraceTrafficManager : public TrafficManager {

  friend class TraceFileTrafficPattern;

protected:

  // One time-ordered queue per source node.
  std::vector<std::deque<TraceEvent> > _trace_queue;

  // The event currently being turned into a BookSim packet for a given
  // source, valid only in the brief window between _IssuePacket() and
  // _GeneratePacket() for that source (see notes in the .cpp).
  std::vector<TraceEvent> _pending_event;
  std::vector<bool>       _pending_valid;
  int                     _last_issue_source;

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

  // Used by TraceFileTrafficPattern::dest(); do not call from outside the
  // (source, class) pair currently being generated.
  int PendingDestination(int source) const;
};

// Replaces the statistical traffic pattern (uniform, transpose, ...) with
// one that simply returns whatever destination the trace queued up for
// this source. Installed directly into TrafficManager's protected
// `_traffic_pattern` vector in the constructor below — no change to
// traffic.cpp's string factory is needed.
class TraceFileTrafficPattern : public TrafficPattern {
private:
  TraceTrafficManager * _tm;
public:
  TraceFileTrafficPattern(int nodes, TraceTrafficManager * tm)
    : TrafficPattern(nodes), _tm(tm) {}
  virtual int dest(int source) { return _tm->PendingDestination(source); }
};

#endif

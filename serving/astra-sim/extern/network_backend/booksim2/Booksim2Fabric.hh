/******************************************************************************
VeritX — BookSim2 fabric wrapper for ASTRA-sim's network backend slot.

Owns ONE shared EmbedTM instance (our booksim2 fork, embedding API) and a
cycle-based event queue. ASTRA-sim ranks drive it through Booksim2NetworkApi;
the fabric steps only when the event queue advances (proceed()), and packet
arrivals are reported back as events at their retirement cycle.
*******************************************************************************/

#ifndef __VERITX_BOOKSIM2_FABRIC_HH__
#define __VERITX_BOOKSIM2_FABRIC_HH__

#include <functional>
#include <map>
#include <memory>
#include <queue>
#include <string>
#include <utility>
#include <vector>

#include "astra-sim/system/Common.hh"
#include "veritx_embed.hpp"

namespace VeritX {

// One fabric arrival: a packet fully retired at `dst` at cycle `atime`.
struct Arrival {
  int atime;
  int src;
  int dst;
  int pid;
};

// ---- cycle-based event queue (mirrors the analytical backend's EventQueue,
//      but steps the fabric between events) --------------------------------
class EventQueue {
 public:
  EventQueue(VeritXEmbed::EmbedTM * tm) : _tm(tm), _now(0), _seq(0) {}

  // Called after every fabric advance (arrivals drained). Set by the
  // frontend main to pump chunk-arrival events.
  std::function<void()> advance_hook;

  void schedule_event(int cycle, void (*fn)(void *), void * arg) {
    _heap.push({cycle, _seq++, fn, arg});
  }

  bool finished() const { return _heap.empty(); }

  int get_current_time() const { return _now; }

  void proceed() {
    auto ev = _heap.top();
    _heap.pop();
    if (ev.cycle > _now) {
      int delta = ev.cycle - _now;
      _tm->RunCycles(delta);
      _now = ev.cycle;
      _drain_retired();
    }
    ev.fn(ev.arg);
  }

  // Arrivals collected during the last run_cycles chunk, FIFO per (src, dst).
  std::queue<Arrival> & arrivals(int src, int dst) {
    return _arrivals[std::make_pair(src, dst)];
  }
  bool has_arrival(int src, int dst) {
    return !_arrivals[std::make_pair(src, dst)].empty();
  }

  void run_cycles(int cycles) {
    _tm->RunCycles(cycles);
    _now += cycles;
    _drain_retired();
  }

 private:
  struct Event {
    int cycle;
    long seq;
    void (*fn)(void *);
    void * arg;
    bool operator>(Event const & o) const {
      return std::tie(cycle, seq) > std::tie(o.cycle, o.seq);
    }
  };

  void _drain_retired() {
    int const nodes = _tm->NumNodes();
    for (int n = 0; n < nodes; ++n) {
      auto retired = _tm->DrainRetired(n);
      for (auto const & r : retired)
        _arrivals[std::make_pair(r.src, r.dst)].push({r.atime, r.src, r.dst, r.pid});
    }
    if (advance_hook) advance_hook();
  }

  VeritXEmbed::EmbedTM * _tm;
  int _now;
  long _seq;
  std::priority_queue<Event, std::vector<Event>, std::greater<Event>> _heap;
  std::map<std::pair<int, int>, std::queue<Arrival>> _arrivals;
};

// ---- the fabric: network config + shared EmbedTM + timebase --------------
class BookSim2Fabric {
 public:
  BookSim2Fabric(std::string const & cfg_file,
                 std::vector<std::string> const & overrides,
                 double ns_per_cycle, int flit_bytes);
  ~BookSim2Fabric();

  int node_count() const { return _tm->NumNodes(); }
  int flit_bytes() const { return _flit_bytes; }
  double ns_per_cycle() const { return _ns_per_cycle; }
  double bytes_per_second() const {
    return static_cast<double>(_flit_bytes) * 1e9 / _ns_per_cycle;
  }

  VeritXEmbed::EmbedTM * tm() { return _tm; }

 private:
  VeritXEmbed::EmbedTM * _tm;
  double _ns_per_cycle;
  int _flit_bytes;
};

}  // namespace VeritX

#endif  // __VERITX_BOOKSIM2_FABRIC_HH__

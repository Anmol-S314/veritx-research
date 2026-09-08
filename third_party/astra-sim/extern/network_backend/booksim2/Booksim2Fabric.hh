/******************************************************************************
VeritX — BookSim2 fabric wrapper for ASTRA-sim's network backend slot.

Owns ONE shared EmbedTM instance (our booksim2 fork, embedding API) and a
cycle-based event queue. ASTRA-sim ranks drive it through Booksim2NetworkApi;
the fabric steps only when the event queue advances (proceed()), and packet
arrivals are reported back as events at their retirement cycle.
*******************************************************************************/

#ifndef __VERITX_BOOKSIM2_FABRIC_HH__
#define __VERITX_BOOKSIM2_FABRIC_HH__

#include <cstdlib>
#include <functional>
#include <iostream>
#include <map>
#include <memory>
#include <queue>
#include <string>
#include <utility>
#include <vector>

#include "astra-sim/system/Common.hh"
#include "veritx_embed.hpp"

namespace VeritX {

// VERITX_LEDGER=1: contract ledger; >=2: verbose per-event tracing.
inline int LedgerLevel() {
  static const int level = [] {
    const char* v = std::getenv("VERITX_LEDGER");
    return v ? std::atoi(v) : 0;
  }();
  return level;
}

// One fabric arrival: a packet fully retired at `dst` at cycle `atime`.
struct Arrival {
  int64_t atime;
  int src;
  int dst;
  int pid;
};

// ---- cycle-based event queue (mirrors the analytical backend's EventQueue,
//      but steps the fabric between events) --------------------------------
class EventQueue {
 public:
  EventQueue(VeritXEmbed::EmbedTM * tm)
      : _tm(tm), _now(0), _seq(0), _scheduled(0), _executed(0) {}

  // Called after every fabric advance (arrivals drained). Set by the
  // frontend main to pump chunk-arrival events.
  std::function<void()> advance_hook;

  void schedule_event(int64_t cycle, void (*fn)(void *), void * arg) {
    _heap.push({cycle, _seq++, fn, arg});
    ++_scheduled;
  }

  bool finished() const { return _heap.empty(); }
  int64_t PendingEventCount() const {
    return static_cast<int64_t>(_heap.size());
  }
  int64_t NextEventTime() const {
    return _heap.empty() ? -1 : _heap.top().cycle;
  }
  int64_t ScheduledEventCount() const { return _scheduled; }
  int64_t ExecutedEventCount() const { return _executed; }
  int64_t PendingArrivalCount() const {
    int64_t total = 0;
    for (const auto & kv : _arrivals) total += static_cast<int64_t>(kv.second.size());
    return total;
  }

  int64_t get_current_time() const { return _now; }

  void jump_to(int64_t target) {
    if (target > _now) {
      // VeritX fix: also advance the fabric clock in lock-step. The booksim
      // EmbedTM keeps its own `_time`, and proceed()/run_cycles() step it
      // via RunCycles — but this method only moved _now. After an idle
      // (agentic tool-gap) jump the fabric lagged behind the event queue, so
      // the next DP-group ALLTOALL wave could never synchronize across
      // members (both blocked on a futex forever). jump_to is only reached
      // when the fabric is idle, so JumpCycles (which asserts that) is safe.
      int64_t old = _now;
      _now = target;
      _tm->JumpCycles(target - old);
      _drain_retired();
      if (advance_hook) advance_hook();
    }
  }

  void proceed() {
    auto ev = _heap.top();
    _heap.pop();
    ++_executed;
    if (ev.cycle > _now) {
      // If there are in-flight packets, drain the fabric fully before
      // jumping.  The previous 100K cap was too small for LLM AllReduce
      // bursts (many MBs → many flits) and caused the jump to skip
      // packet retirements, leaving collectives stuck with unreleased nodes.
      if (_tm->HasInFlight()) {
        // Drain until empty or until we reach ev.cycle, whichever comes first.
        // Use small chunks so we interleave retirement checks.
        while (_tm->HasInFlight() && _now < ev.cycle) {
          constexpr int64_t DRAIN_CHUNK = 1000;
          int64_t step = std::min<int64_t>(DRAIN_CHUNK, ev.cycle - _now);
          _tm->RunCycles(step);
          _now += step;
          _drain_retired();
        }
        // If still in-flight but we hit ev.cycle, we must continue stepping
        // past ev.cycle until fabric drains — don't jump over in-flight data.
        // Bounded: a genuine drain finishes in <<1M chunks for LLM bursts;
        // exceeding the bound means stuck flits (bookkeeping or routing bug).
        // Fail loud instead of spinning forever with no output.
        int64_t drain_chunks = 0;
        while (_tm->HasInFlight()) {
          constexpr int64_t DRAIN_CHUNK = 1000;
          constexpr int64_t MAX_DRAIN_CHUNKS = 100000;  // 1e8 cycles
          _tm->RunCycles(DRAIN_CHUNK);
          _now += DRAIN_CHUNK;
          _drain_retired();
          if (++drain_chunks >= MAX_DRAIN_CHUNKS) {
            std::cerr << "[LEDGER][DRAIN_STUCK] ev_cycle=" << ev.cycle
                      << " now=" << _now
                      << " inflight=" << _tm->InFlightFlitCount() << std::endl;
            std::cerr << "Booksim2: fabric drain exceeded 1e8 cycles with "
                      << _tm->InFlightFlitCount()
                      << " flits still in flight; proceeding anyway."
                      << std::endl;
            break;
          }
        }
        // Now _now >= ev.cycle and fabric is idle; ensure we are at least at ev.cycle
        if (_now < ev.cycle) _now = ev.cycle;
        _drain_retired();
      } else {
        // No in-flight packets — safe to jump directly. Must also advance
        // the fabric clock in lock-step: jumping only _now lets the fabric
        // lag behind (compute-heavy events with no comm leave it idle), and
        // that drift breaks DP-group ALLTOALL wave synchronization.
        int64_t old = _now;
        _now = ev.cycle;
        if (ev.cycle > old) _tm->JumpCycles(ev.cycle - old);
        _drain_retired();
      }
    }
    if (VeritX::LedgerLevel() >= 2) {
      std::cerr << "[LEDGER][EVENT] cycle=" << ev.cycle << " now=" << _now
                << " fn=" << reinterpret_cast<const void*>(ev.fn) << std::endl;
    }
    ev.fn(ev.arg);
    if (VeritX::LedgerLevel() >= 2) {
      std::cerr << "[LEDGER][EVENT_DONE] cycle=" << ev.cycle
                << " now=" << _now << std::endl;
    }
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
    if (advance_hook) advance_hook();
  }

 private:
  struct Event {
    int64_t cycle;
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
  int64_t _now;
  long _seq;
  int64_t _scheduled;
  int64_t _executed;
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

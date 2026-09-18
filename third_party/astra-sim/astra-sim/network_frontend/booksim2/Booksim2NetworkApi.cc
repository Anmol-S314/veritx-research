#include "Booksim2NetworkApi.hh"

#include <algorithm>
#include <cassert>
#include <cmath>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <tuple>

using namespace AstraSim;

namespace VeritX {

BookSim2Fabric * Booksim2NetworkApi::_fabric = NULL;
EventQueue * Booksim2NetworkApi::_eq = NULL;
CallbackTracker Booksim2NetworkApi::_tracker = {};
ChunkIdGenerator Booksim2NetworkApi::_chunk_id_generator = {};
std::map<std::pair<int, int>, std::queue<Booksim2NetworkApi::PendingSend>>
    Booksim2NetworkApi::_pending = {};
std::map<int, Booksim2NetworkApi::FoldGroup> Booksim2NetworkApi::_fold_groups = {};
bool Booksim2NetworkApi::_mcast_fold = false;
int Booksim2NetworkApi::_fold_window = 8;
int Booksim2NetworkApi::_embedded_mtu_flits = 0;

// VeritX trial: split one message-sized injection into ceil(flits/mtu)
// packets (full-MTU + tail). Returns fragment count for _pending matching
// (remaining_flits counts down one per fragment arrival).
static int inject_fragmented(BookSim2Fabric * fabric, int src, int dst,
                             int flits, int mtu) {  if (mtu <= 0 || flits <= mtu) {
    fabric->tm()->InjectUnicast(src, dst, flits, 0);
    return 1;
  }
  int full = flits / mtu, tail = flits % mtu, n = 0;
  for (int i = 0; i < full; ++i) {
    fabric->tm()->InjectUnicast(src, dst, mtu, 0);
    ++n;
  }
  if (tail) {
    fabric->tm()->InjectUnicast(src, dst, tail, 0);
    ++n;
  }
  return n;
}

Booksim2NetworkApi::Booksim2NetworkApi(int rank, BookSim2Fabric * fabric,
                                       EventQueue * eq)
    : AstraNetworkAPI(rank) {
  (void)fabric;
  (void)eq;
}

void Booksim2NetworkApi::process_chunk_arrival(void * args) {
  // args: (tag, src, dst, count, chunk_id) — mirror analytical semantics:
  // if both callbacks are registered, fire both; else fire send only and
  // mark the transmission finished so the late sim_recv fires immediately.
  auto * data = static_cast<std::tuple<int, int, int, uint64_t, int> *>(args);
  const auto [tag, src, dst, count, chunk_id] = *data;
  delete data;

  TrackerEntry * entry = _tracker.search_entry(tag, src, dst, count, chunk_id);
  if (entry == NULL) {
    std::cerr << "Booksim2: chunk arrival with no tracker entry (tag " << tag
              << " src " << src << " dst " << dst << ")" << std::endl;
    return;
  }

  if (VeritX::LedgerLevel() >= 2)
    std::cerr << "[LEDGER][ARRIVE] tag=" << tag << " src=" << src << " dst=" << dst
              << " count=" << count << " chunk=" << chunk_id
              << " both=" << entry->both_callbacks_registered()
              << " finished=" << entry->is_transmission_finished() << std::endl;

  if (getenv("VERITX_DEBUG"))
    std::cerr << "[dbg] chunk_arrival tag=" << tag << " src=" << src << " dst=" << dst
              << " count=" << count << " both=" << entry->both_callbacks_registered()
              << " finished=" << entry->is_transmission_finished() << std::endl;
  if (entry->both_callbacks_registered()) {
    entry->invoke_send_handler();
    if (getenv("VERITX_DEBUG"))
      std::cerr << "[dbg] send handler invoked src=" << src << " dst=" << dst << std::endl;
    entry->invoke_recv_handler();
    if (getenv("VERITX_DEBUG"))
      std::cerr << "[dbg] recv handler invoked src=" << src << " dst=" << dst << std::endl;
    _tracker.pop_entry(tag, src, dst, count, chunk_id);
  } else {
    if (entry->has_send_callback()) {
      entry->invoke_send_handler();
      if (getenv("VERITX_DEBUG"))
        std::cerr << "[dbg] send handler invoked (recv pending) src=" << src << " dst=" << dst << std::endl;
    }
    entry->set_transmission_finished();
  }
}

void Booksim2NetworkApi::flush_fold_group(int src) {
  auto it = _fold_groups.find(src);
  if (it == _fold_groups.end() || it->second.dsts.empty()) return;
  FoldGroup g = it->second;
  _fold_groups.erase(it);

  // Order dsts by snake position: the mcast stream terminates at the FAR
  // end, so the far end must be the last-visited node and every copy must
  // lie before it on the route (copies eject only at routers the stream
  // transits). Requires snake routing on a square mesh (documented).
  int const nodes = _fabric->node_count();
  int const k = static_cast<int>(std::sqrt(nodes));
  auto snake_pos = [&](int n) {
    int const x = n % k, y = n / k;
    return (y & 1) ? y * k + (k - 1 - x) : y * k + x;
  };
  std::sort(g.dsts.begin(), g.dsts.end(),
            [&](int a, int b) { return snake_pos(a) < snake_pos(b); });

  if (getenv("VERITX_DEBUG"))
    std::cerr << "[dbg] FOLD src=" << src << " count=" << g.count
              << " k=" << g.dsts.size() << " far=" << g.dsts.back()
              << " t=" << _eq->get_current_time() << std::endl;
  int const flits = (g.count + _fabric->flit_bytes() - 1) / _fabric->flit_bytes();
  if (g.dsts.size() == 1) {
    // k=1: a plain unicast packet (the mcast stream path requires a
    // routable far end and gains nothing for a single dest).
    int nfrag = inject_fragmented(_fabric, src, g.dsts[0], flits,
                                  _embedded_mtu_flits);
    g.pendings[0].remaining_flits = nfrag;
    _pending[std::make_pair(src, g.dsts[0])].push(g.pendings[0]);
    return;
  }
  for (int f = 0; f < flits; ++f)
    _fabric->tm()->InjectMcast(src, g.dsts, 0);
  for (size_t i = 0; i < g.dsts.size(); ++i) {
    g.pendings[i].remaining_flits = flits;
    _pending[std::make_pair(src, g.dsts[i])].push(g.pendings[i]);
  }
}

void Booksim2NetworkApi::flush_check(void * arg) {
  int const src = *static_cast<int *>(arg);
  delete static_cast<int *>(arg);
  flush_fold_group(src);
}

void Booksim2NetworkApi::flush_all() {
  std::vector<int> srcs;
  for (auto const & kv : _fold_groups)
    if (!kv.second.dsts.empty()) srcs.push_back(kv.first);
  for (int src : srcs) flush_fold_group(src);
}

bool Booksim2NetworkApi::has_pending_groups() {
  for (auto const & kv : _fold_groups)
    if (!kv.second.dsts.empty()) return true;
  return false;
}

int64_t Booksim2NetworkApi::PendingSendCount() {
  int64_t total = 0;
  for (auto const & kv : _pending)
    total += static_cast<int64_t>(kv.second.size());
  return total;
}

int64_t Booksim2NetworkApi::PendingFoldGroupCount() {
  int64_t total = 0;
  for (auto const & kv : _fold_groups)
    if (!kv.second.dsts.empty()) ++total;
  return total;
}

void Booksim2NetworkApi::pump_arrivals() {
  assert(_fabric != NULL && _eq != NULL);
  if (getenv("VERITX_DEBUG"))
    std::cerr << "[dbg] pump t=" << _eq->get_current_time() << std::endl;
  int const nodes = _fabric->node_count();
  for (int src = 0; src < nodes; ++src) {
    for (int dst = 0; dst < nodes; ++dst) {
      auto key = std::make_pair(src, dst);
      auto & q = _eq->arrivals(src, dst);
      auto & pending = _pending[key];
      while (!q.empty() && !pending.empty()) {
        Arrival const a = q.front();
        if (getenv("VERITX_DEBUG"))
          std::cerr << "[dbg] arrival src=" << src << " dst=" << dst
                    << " atime=" << a.atime << std::endl;
        q.pop();
        PendingSend & p = pending.front();
        if (--p.remaining_flits > 0) continue;  // more streams still arriving
        auto * arg = new std::tuple<int, int, int, uint64_t, int>(
            p.tag, src, dst, p.count, p.chunk_id);
        _eq->schedule_event(a.atime, Booksim2NetworkApi::process_chunk_arrival,
                            arg);
        pending.pop();
      }
    }
  }
}

int Booksim2NetworkApi::sim_send(void * buffer, uint64_t count, int type,
                                 int dst, int tag, sim_request * request,
                                 void (*msg_handler)(void *), void * fun_arg) {
  assert(_fabric != NULL && _eq != NULL);
  const int src = sim_comm_get_rank();
  if (getenv("VERITX_DEBUG"))
    std::cerr << "[dbg] sim_send src=" << src << " dst=" << dst
              << " count=" << count << " tag=" << tag << " t=" << _eq->get_current_time() << std::endl;
  const int chunk_id =
      _chunk_id_generator.create_send_chunk_id(tag, src, dst, count);
  if (VeritX::LedgerLevel() >= 2)
    std::cerr << "[LEDGER][SEND] src=" << src << " dst=" << dst
              << " count=" << count << " tag=" << tag << " chunk=" << chunk_id
              << " t=" << _eq->get_current_time() << std::endl;

  TrackerEntry * entry = _tracker.search_entry(tag, src, dst, count, chunk_id);
  if (entry != NULL) {
    entry->register_send_callback(msg_handler, fun_arg);
  } else {
    auto * new_entry =
        _tracker.create_new_entry(tag, src, dst, count, chunk_id);
    new_entry->register_send_callback(msg_handler, fun_arg);
  }

  // bytes -> flits
  int const flit_bytes = _fabric->flit_bytes();
  int flits = static_cast<int>((count + flit_bytes - 1) / flit_bytes);
  if (flits < 1) flits = 1;

  if (_mcast_fold) {
    int64_t const now = _eq->get_current_time();
    auto & g = _fold_groups[src];
    bool joinable = !g.dsts.empty() && g.count == count &&
                    (now - g.last_cycle) <= _fold_window &&
                    std::find(g.dsts.begin(), g.dsts.end(), dst) == g.dsts.end();
    if (joinable) {
      g.dsts.push_back(dst);
      g.pendings.push_back({tag, count, chunk_id, 0});
      g.last_cycle = now;
      return 0;  // deferred; the whole fanout injects as one mcast stream
    }
    flush_fold_group(src);
    g = FoldGroup{};
    g.count = count;
    g.last_cycle = now;
    g.dsts.push_back(dst);
    g.pendings.push_back({tag, count, chunk_id, 0});
    // Bounded defer: flush this group after the fold window closes so
    // non-fanout (k=1) sends do not wait for the next event.
    auto * src_arg = new int(src);
    _eq->schedule_event(now + _fold_window + 1, flush_check, src_arg);
    return 0;
  }

  // VeritX trial: fragment message-sized sends (see set_embedded_mtu).
  // remaining_flits counts fragments; the chunk completes on the last
  // fragment's arrival (same machinery as the fold path).
  int nfrag = inject_fragmented(_fabric, src, dst, flits,
                                _embedded_mtu_flits);
  _pending[std::make_pair(src, dst)].push({tag, count, chunk_id, nfrag});
  if (getenv("VERITX_DEBUG"))
    std::cerr << "[dbg] sim_send injected flits=" << flits << " nfrag="
              << nfrag << " pending="
              << _pending[std::make_pair(src, dst)].size() << std::endl;
  return 0;
}

int Booksim2NetworkApi::sim_recv(void * buffer, uint64_t count, int type,
                                 int src, int tag, sim_request * request,
                                 void (*msg_handler)(void *), void * fun_arg) {
  const int dst = sim_comm_get_rank();
  const int chunk_id =
      _chunk_id_generator.create_recv_chunk_id(tag, src, dst, count);
  if (VeritX::LedgerLevel() >= 2)
    std::cerr << "[LEDGER][RECV] src=" << src << " dst=" << dst
              << " count=" << count << " tag=" << tag << " chunk=" << chunk_id
              << " t=" << _eq->get_current_time() << std::endl;

  TrackerEntry * entry = _tracker.search_entry(tag, src, dst, count, chunk_id);
  if (getenv("VERITX_DEBUG"))
    std::cerr << "[dbg] sim_recv src=" << src << " dst=" << dst << " count=" << count
              << " tag=" << tag << " entry=" << (entry!=NULL) << std::endl;
  if (entry != NULL) {
    if (entry->is_transmission_finished()) {
      _tracker.pop_entry(tag, src, dst, count, chunk_id);
      const timespec_t delta{NS, 0};
      sim_schedule(delta, msg_handler, fun_arg);
    } else {
      entry->register_recv_callback(msg_handler, fun_arg);
    }
  } else {
    auto * new_entry =
        _tracker.create_new_entry(tag, src, dst, count, chunk_id);
    new_entry->register_recv_callback(msg_handler, fun_arg);
  }
  return 0;
}

void Booksim2NetworkApi::sim_schedule(const timespec_t delta,
                                      void (*fun_ptr)(void *),
                                      void * const fun_arg) {
  assert(delta.time_res == NS);
  assert(fun_ptr != NULL);
  assert(_fabric != NULL && _eq != NULL);
  const double ns_per_cycle = _fabric->ns_per_cycle();
  int64_t cycles = std::llround(delta.time_val / ns_per_cycle);
  int64_t const now = _eq->get_current_time();
  if (VeritX::LedgerLevel() >= 2)
    std::cerr << "[LEDGER][SKED] now=" << now << " delta_ns=" << delta.time_val
              << " cycles=" << cycles << " target=" << (now + cycles)
              << std::endl;
  _eq->schedule_event(now + cycles, fun_ptr, fun_arg);
}

timespec_t Booksim2NetworkApi::sim_get_time() {
  assert(_eq != NULL);
  const double ns = static_cast<double>(_eq->get_current_time()) *
                    _fabric->ns_per_cycle();
  return {NS, ns};
}

double Booksim2NetworkApi::get_BW_at_dimension(int dim) {
  assert(_fabric != NULL);
  (void)dim;
  return _fabric->bytes_per_second();
}

}  // namespace VeritX

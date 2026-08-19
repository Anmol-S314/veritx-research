#pragma once

// Booksim2NetworkApi: per-rank AstraNetworkAPI implementation driving ONE
// shared BookSim2 fabric (our fork, embedding API). Mirrors the analytical
// frontend's semantics: sim_send/sim_recv register callbacks on a shared
// tracker; arrivals are matched FIFO per (src, dst) and fire the chunk
// arrival event at the fabric cycle the packet retired.

#include <cstdint>
#include <memory>
#include <queue>
#include <vector>

#include "astra-sim/common/AstraNetworkAPI.hh"
#include "astra-sim/system/Common.hh"
#include "common/Booksim2Tracker.hh"
#include "extern/network_backend/booksim2/Booksim2Fabric.hh"

namespace VeritX {

class Booksim2NetworkApi : public AstraSim::AstraNetworkAPI {
 public:
  Booksim2NetworkApi(int rank, BookSim2Fabric * fabric, EventQueue * eq);
  ~Booksim2NetworkApi() override = default;

  // ---- static setup (one fabric + one event queue for all ranks) ----
  static void set_fabric(BookSim2Fabric * fabric) { _fabric = fabric; }
  static void set_event_queue(EventQueue * eq) { _eq = eq; }

  // Multicast folding: consecutive sim_send calls from one src with the same
  // byte count to different dsts within `window` cycles are folded into ONE
  // fabric multicast stream (1 injection, k deliveries) — the bridge-fork
  // mechanism. Copies eject only at nodes ON the stream path, so folding is
  // only correct on fabrics whose routing visits all group members (snake on
  // mesh / dispatch-fanout geometry on the route-table fabric).
  static void set_mcast_fold(bool on, int window) {
    _mcast_fold = on;
    _fold_window = window;
  }
  static void flush_all();
  static bool has_pending_groups();
  static void flush_check(void * arg);

  // Drain arrivals produced by the last fabric advance and fire chunk
  // arrival events at their retirement cycle. Called by EventQueue after
  // every run_cycles chunk.
  static void pump_arrivals();

  // ---- AstraNetworkAPI ----
  int sim_send(void * buffer, uint64_t count, int type, int dst, int tag,
               AstraSim::sim_request * request, void (*msg_handler)(void * fun_arg),
               void * fun_arg) override;
  int sim_recv(void * buffer, uint64_t count, int type, int src, int tag,
               AstraSim::sim_request * request, void (*msg_handler)(void * fun_arg),
               void * fun_arg) override;
  void sim_schedule(AstraSim::timespec_t delta, void (*fun_ptr)(void * fun_arg),
                    void * fun_arg) override;
  AstraSim::timespec_t sim_get_time() override;
  double get_BW_at_dimension(int dim) override;

 private:
  static void process_chunk_arrival(void * args);

  static BookSim2Fabric * _fabric;
  static EventQueue * _eq;
  static CallbackTracker _tracker;
  static ChunkIdGenerator _chunk_id_generator;

  // One pending send context per (src, dst) FIFO; arrivals pop the head.
  struct PendingSend {
    int tag;
    uint64_t count;
    int chunk_id;
    int remaining_flits;  // arrivals still expected for this send
  };
  static std::map<std::pair<int, int>, std::queue<PendingSend>> _pending;

  // Multicast fold group: sends deferred from one src awaiting fanout.
  struct FoldGroup {
    uint64_t count = 0;
    int last_cycle = 0;
    std::vector<int> dsts;
    std::vector<PendingSend> pendings;
  };
  static std::map<int, FoldGroup> _fold_groups;
  static bool _mcast_fold;
  static int _fold_window;
  static void flush_fold_group(int src);
};

}  // namespace VeritX

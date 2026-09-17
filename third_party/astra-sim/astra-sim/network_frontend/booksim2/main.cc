/******************************************************************************
VeritX — ASTRA-sim entry point with our BookSim2 fork as the network backend.
Mirrors the analytical frontend's main, but the network is ONE shared
BookSim2 fabric (embedding API) driven by a cycle-based event queue.
*******************************************************************************/

#include <cstring>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <string>
#include <vector>
#include <unistd.h>  // VeritX: access() for per-rank workload file check

#include "astra-sim/common/Logging.hh"
#include "astra-sim/system/Sys.hh"
#include "Booksim2NetworkApi.hh"
#include "common/CmdLineParser.hh"
#include "extern/network_backend/booksim2/Booksim2Fabric.hh"
#include "remote_memory_backend/analytical/AnalyticalRemoteMemory.hh"

using namespace AstraSim;
using namespace VeritX;

namespace {
bool LedgerLevel() {
  // VERITX_LEDGER=1: collective-execution contract ledger (low volume:
  // CMD/LOAD/COLL/STREAM/STATE/STEP/DRAIN_STUCK). VERITX_LEDGER=2: adds
  // verbose per-packet/per-event tracing (EVENT/SKED/SEND/RECV/...).
  static const int level = [] {
    const char* v = std::getenv("VERITX_LEDGER");
    return v ? std::atoi(v) : 0;
  }();
  return level;
}
bool LedgerEnabled() {
  return LedgerLevel() >= 1;
}
bool LedgerVerbose() {
  return LedgerLevel() >= 2;
}

void LedgerQuiescence(uint64_t round, const char* where, EventQueue& event_queue,
                      BookSim2Fabric& fabric,
                      const std::vector<Sys*>& systems) {
  if (!LedgerEnabled()) return;
  const bool queue_idle = event_queue.finished();
  const bool fabric_idle = !fabric.tm()->HasInFlight();
  const int64_t heap = event_queue.PendingEventCount();
  const int64_t arrivals = event_queue.PendingArrivalCount();
  const int64_t api_pending = Booksim2NetworkApi::PendingSendCount();
  const int64_t fold_groups = Booksim2NetworkApi::PendingFoldGroupCount();
  int64_t sys_pending = 0;
  std::string pending_sys;
  for (size_t i = 0; i < systems.size(); ++i) {
    if (systems[i]->pending_events > 0) {
      ++sys_pending;
      if (pending_sys.size() < 63) {
        if (!pending_sys.empty()) pending_sys += ",";
        pending_sys += std::to_string(i);
      }
    }
  }
  std::cerr << "[LEDGER][STATE] round=" << round << " where=" << where
            << " now=" << event_queue.get_current_time()
            << " fab=" << fabric.tm()->Cycle()
            << " heap=" << heap << " next_ev=" << event_queue.NextEventTime()
            << " sched=" << event_queue.ScheduledEventCount()
            << " exec=" << event_queue.ExecutedEventCount()
            << " arrivals=" << arrivals
            << " api_pending=" << api_pending
            << " fold_groups=" << fold_groups
            << " sys_pending=" << sys_pending << "(" << pending_sys << ")"
            << " inflight=" << fabric.tm()->InFlightFlitCount()
            << " partial=" << fabric.tm()->PartialQueueFlitCount()
            << " req_packets=" << fabric.tm()->PacketsRequested()
            << " built_unicast=" << fabric.tm()->UnicastFlitsConstructed()
            << " built_mcast=" << fabric.tm()->McastDeliveriesConstructed()
            << " retired_flits=" << fabric.tm()->FlitsRetired()
            << " tail_deliveries=" << fabric.tm()->TailDeliveriesRecorded()
            << " can_advance="
            << (queue_idle && fabric_idle && heap == 0 && arrivals == 0 &&
                api_pending == 0 && fold_groups == 0 && sys_pending == 0)
            << std::endl;
  if (fabric.tm()->InFlightFlitCount() > 0) {
    int id = 0, src = 0, dst = 0, vc = 0;
    int64_t ctime = 0, itime = 0;
    bool head = false, tail = false;
    if (fabric.tm()->SampleOldestInFlight(id, src, dst, ctime, itime, head,
                                          tail, vc)) {
      std::cerr << "[LEDGER][STUCK_FLIT] round=" << round << " where=" << where
                << " id=" << id << " src=" << src << " dst=" << dst
                << " ctime=" << ctime << " itime=" << itime
                << " head=" << head << " tail=" << tail << " vc=" << vc
                << " now=" << fabric.tm()->Cycle() << std::endl;
    }
  }
}
}  // namespace

int main(int argc, char * argv[]) {
  CmdLineParser cmd_line_parser(argv[0]);
  cmd_line_parser.parse(argc, argv);

  const std::string workload_configuration =
      cmd_line_parser.get<std::string>("workload-configuration");
  const std::string comm_group_configuration =
      cmd_line_parser.get<std::string>("comm-group-configuration");
  const std::string system_configuration =
      cmd_line_parser.get<std::string>("system-configuration");
  const std::string remote_memory_configuration =
      cmd_line_parser.get<std::string>("remote-memory-configuration");
  const std::string network_configuration =
      cmd_line_parser.get<std::string>("network-configuration");
  const std::string logging_configuration =
      cmd_line_parser.get<std::string>("logging-configuration");
  const std::string logging_folder =
      cmd_line_parser.get<std::string>("logging-folder");
  const int num_queues_per_dim =
      cmd_line_parser.get<int>("num-queues-per-dim");
  const double comm_scale = cmd_line_parser.get<double>("comm-scale");
  const double injection_scale = cmd_line_parser.get<double>("injection-scale");
  const bool rendezvous_protocol =
      cmd_line_parser.get<bool>("rendezvous-protocol");

  // ---- booksim2 fabric parameters (VeritX extras) ----
  const int flit_bytes = cmd_line_parser.has("booksim2-flit-bytes")
                             ? cmd_line_parser.get<int>("booksim2-flit-bytes")
                             : 8;
  const double ns_per_cycle = cmd_line_parser.has("booksim2-ns-per-cycle")
                                  ? cmd_line_parser.get<double>(
                                        "booksim2-ns-per-cycle")
                                  : 1.0;
  std::vector<std::string> booksim2_overrides;
  if (cmd_line_parser.has("booksim2-extra")) {
    std::string extra = cmd_line_parser.get<std::string>("booksim2-extra");
    // semicolon-separated param=value pairs
    size_t start = 0;
    while (start < extra.size()) {
      size_t end = extra.find(';', start);
      if (end == std::string::npos) end = extra.size();
      if (end > start) booksim2_overrides.push_back(extra.substr(start, end - start));
      start = end + 1;
    }
  }

  AstraSim::LoggerFactory::init(logging_configuration, logging_folder);

  // ---- one shared fabric + one event queue ----
  BookSim2Fabric fabric(network_configuration, booksim2_overrides,
                        ns_per_cycle, flit_bytes);
  EventQueue event_queue(fabric.tm());

  const int npus_count = fabric.node_count();
  // VeritX: physical topology dims (e.g. "1,2") matching network.yml, so
  // trace collectives scoped to dim>=1 (EP/DP) map onto real fabric dims
  // instead of being silently dropped. Defaults to flat (legacy).
  std::vector<int> npus_count_per_dim;
  std::string dims_arg;
  if (cmd_line_parser.has("physical-dims")) {
    dims_arg = cmd_line_parser.get<std::string>("physical-dims");
  }
  if (!dims_arg.empty()) {
    size_t start = 0;
    int product = 1;
    while (start < dims_arg.size()) {
      size_t end = dims_arg.find(',', start);
      if (end == std::string::npos) end = dims_arg.size();
      if (end > start) {
        int d = std::atoi(dims_arg.substr(start, end - start).c_str());
        if (d < 1) {
          std::cerr << "booksim2: invalid --physical-dims '" << dims_arg
                    << "'" << std::endl;
          return 1;
        }
        npus_count_per_dim.push_back(d);
        product *= d;
      }
      start = end + 1;
    }
    if (npus_count_per_dim.empty() || product != npus_count) {
      std::cerr << "booksim2: --physical-dims '" << dims_arg
                << "' product != fabric node count (" << npus_count << ")"
                << std::endl;
      return 1;
    }
    if (LedgerEnabled()) {
      std::cerr << "[LEDGER][TOPO] npus=" << npus_count << " dims=" << dims_arg
                << std::endl;
    }
  } else {
    npus_count_per_dim = std::vector<int>{npus_count};
  }

  Booksim2NetworkApi::set_fabric(&fabric);
  Booksim2NetworkApi::set_event_queue(&event_queue);
  event_queue.advance_hook = []() { Booksim2NetworkApi::pump_arrivals(); };

  const bool mcast_fold =
      cmd_line_parser.get<bool>("booksim2-mcast-fold");
  const int mcast_window =
      cmd_line_parser.get<int>("booksim2-mcast-window");
  Booksim2NetworkApi::set_mcast_fold(mcast_fold, mcast_window);

  auto memory_api =
      std::make_unique<Analytical::AnalyticalRemoteMemory>(remote_memory_configuration);
  std::vector<std::unique_ptr<Booksim2NetworkApi>> network_apis;
  std::vector<Sys *> systems;

  std::vector<int> queues_per_dim(npus_count_per_dim.size(),
                                   num_queues_per_dim);
  for (int i = 0; i < npus_count; ++i) {
    auto network_api = std::make_unique<Booksim2NetworkApi>(i, &fabric,
                                                            &event_queue);
    auto * system =
        new Sys(i, workload_configuration, comm_group_configuration,
                system_configuration, memory_api.get(), network_api.get(),
                npus_count_per_dim, queues_per_dim, injection_scale,
                comm_scale, rendezvous_protocol);
    network_apis.push_back(std::move(network_api));
    systems.push_back(system);
  }

  // Fire initial workload (event_handler) synchronously before entering interactive mode.
  // This ensures the first Waiting contains valid completion data and advances wall_time.
  {
    // Snapshot per-rank GPU-op/comm ticks so the report below can emit a
    // real per-round exposed-communication number (wall_delta - gpu_delta,
    // the same formula as Workload::report) instead of echoing wall_time.
    // Snapshots must be per-round: each round reloads Workload (fresh
    // counters) while the event-queue wall clock is cumulative.
    std::vector<uint64_t> init_gpu_before(npus_count, 0), init_comm_before(npus_count, 0);
    for (int i = 0; i < npus_count; ++i) {
      init_gpu_before[i] = systems[i]->workload->hw_resource->tics_gpu_ops;
      init_comm_before[i] = systems[i]->workload->hw_resource->tics_gpu_comms;
    }
    uint64_t init_wall_before = event_queue.get_current_time();
    for (int i = 0; i < npus_count; ++i) systems[i]->workload->fire();
    while (true) {
      while (!event_queue.finished() || fabric.tm()->HasInFlight()) {
        if (!event_queue.finished()) event_queue.proceed();
        else event_queue.run_cycles(1000000);
      }
      Booksim2NetworkApi::flush_all();
      bool all_done = true;
      for (auto* sys : systems) if (sys->pending_events > 0) { all_done = false; break; }
      if (all_done && event_queue.finished() && !fabric.tm()->HasInFlight() && !Booksim2NetworkApi::has_pending_groups()) break;
      if (!all_done && event_queue.finished() && !fabric.tm()->HasInFlight()) event_queue.run_cycles(1);
    }
    uint64_t wall_time = event_queue.get_current_time();
    uint64_t init_wall_delta = wall_time >= init_wall_before ? wall_time - init_wall_before : 0;
    for (int i = 0; i < npus_count; ++i) {
      uint64_t gpu_after = systems[i]->workload->hw_resource->tics_gpu_ops;
      uint64_t comm_after = systems[i]->workload->hw_resource->tics_gpu_comms;
      uint64_t gpu_delta = gpu_after >= init_gpu_before[i] ? gpu_after - init_gpu_before[i] : 0;
      uint64_t comm_delta = comm_after >= init_comm_before[i] ? comm_after - init_comm_before[i] : 0;
      uint64_t exposed = (gpu_delta + comm_delta == 0) ? 0
          : (init_wall_delta >= gpu_delta ? init_wall_delta - gpu_delta : 0);
      std::cout << "[workload] sys[" << i << "] finished, " << wall_time << " cycles, exposed communication " << exposed << " cycles." << std::endl;
    }
    std::cout << "Waiting" << std::endl;
  }

  // Interactive mode: read subsequent workload paths from stdin
  {
    const bool ledger_enabled = LedgerEnabled();
    uint64_t interactive_round = 0;

    std::string line;
    // VeritX multi-instance protocol:
    //   "load <path>"  queue a reload (applied only to systems whose
    //                  <path>.<rank>.et exists — lets one round carry the
    //                  disjoint rank sets of several instances / DP members)
    //   "run"          apply all queued loads, fire unfinished workloads,
    //                  run to quiescence, report sys lines + Waiting
    //   "<path>"       legacy single-path round (= "load <path>" + "run")
    //   "pass [t]" / "exit" / "done" unchanged
    std::vector<std::string> pending_loads;
    while (std::getline(std::cin, line)) {
      ++interactive_round;
      // Trim whitespace
      line.erase(0, line.find_first_not_of(" \t\n\r"));
      line.erase(line.find_last_not_of(" \t\n\r") + 1);

      if (line.empty() || line.rfind("pass", 0) == 0) {
        // "pass" or "pass <target>" — advance event queue if a future
        // target time is supplied (agentic tool-call gaps). This keeps the
        // binary's wall_time monotonic with Python's _sim_time.
        // If fabric is idle, jump directly (no need to simulate idle cycles).
        if (line.size() > 4) {
          try {
            std::string ts = line.substr(5);
            // trim
            ts.erase(0, ts.find_first_not_of(" \t"));
            ts.erase(ts.find_last_not_of(" \t") + 1);
            if (!ts.empty()) {
              uint64_t target = std::stoull(ts);
              uint64_t cur = event_queue.get_current_time();
              if (target > cur) {
                if (fabric.tm()->HasInFlight() || !event_queue.finished()) {
                  uint64_t delta = target - cur;
                  event_queue.run_cycles(delta);
                } else {
                  event_queue.jump_to(target);
                }
              }
            }
          } catch (...) {
          }
        }
        if (ledger_enabled) {
          std::cerr << "[LEDGER][CMD] round=" << interactive_round
                    << " cmd=" << line << std::endl;
          LedgerQuiescence(interactive_round, "pass", event_queue, fabric,
                           systems);
        }
        uint64_t wall_time = event_queue.get_current_time();
        // Pure time advance (tool-call gap): no collective ran this round,
        // so exposed is 0. Total stays cumulative for the Python clock.
        for (int i = 0; i < npus_count; ++i) {
          std::cout << "[workload] sys[" << i << "] finished, "
                    << wall_time << " cycles, exposed communication "
                    << 0 << " cycles." << std::endl;
        }
        std::cout << "Waiting" << std::endl;
        continue;
      }

      if (line == "exit") {
        break;
      }
      // VeritX: "done" means ONE instance finished — keep serving the
      // rest. (Old code treated it like "exit" and killed the shared
      // binary with other instances' work still queued: clean EXIT:0 with
      // missing requests.)
      // MUST echo "Waiting": serving's loop does read_wait() BEFORE sending
      // its next command — every command (done included) needs exactly one
      // Waiting-terminated reply or serving deadlocks in read_wait.
      // (Silent-ack experiment: serving hung forever; manal's done=exit
      // variant "passes" the DP test only by dying at the first done and
      // riding serving's clean-EOF path.)
      if (line == "done") {
        std::cout << "Waiting" << std::endl;
        continue;
      }

      if (line.rfind("load ", 0) == 0) {
        std::string path = line.substr(5);
        size_t a = path.find_first_not_of(" \t");
        if (a != std::string::npos) path = path.substr(a);
        size_t b = path.find_last_not_of(" \t");
        if (b != std::string::npos) path = path.substr(0, b + 1);
        pending_loads.push_back(path);
        continue;  // accumulate; act on "run"
      }

      if (line == "run") {
        // round with whatever loads were queued (empty set = re-report only)
      } else {
        // legacy bare path line: single load + run
        pending_loads.clear();
        pending_loads.push_back(line);
      }

      // VeritX: reload each system from the first queued path that actually
      // contains its rank file; systems not covered keep their (finished)
      // workload, whose fire() is a guarded no-op.
      for (int i = 0; i < npus_count; ++i) {
        for (auto const & path : pending_loads) {
          std::string rank_file = path + "." + std::to_string(i) + ".et";
          if (access(rank_file.c_str(), R_OK) == 0) {
            if (ledger_enabled) {
              std::cerr << "[LEDGER][LOAD] round=" << interactive_round
                        << " sys=" << i << " path=" << path
                        << " rank_file=" << rank_file << std::endl;
            }
            delete systems[i]->workload;
            systems[i]->workload = new Workload(systems[i], path, comm_group_configuration);
            break;
          }
        }
      }
      pending_loads.clear();

      // Snapshot per-rank GPU-op/comm ticks after reload (fresh counters)
      // and before fire; ranks idle this round report exposed 0.
      std::vector<uint64_t> round_gpu_before(npus_count, 0), round_comm_before(npus_count, 0);
      for (int i = 0; i < npus_count; ++i) {
        round_gpu_before[i] = systems[i]->workload->hw_resource->tics_gpu_ops;
        round_comm_before[i] = systems[i]->workload->hw_resource->tics_gpu_comms;
      }
      uint64_t round_wall_before = event_queue.get_current_time();

      // Fire workloads
      for (int i = 0; i < npus_count; ++i) systems[i]->workload->fire();
      if (ledger_enabled) {
        LedgerQuiescence(interactive_round, "round-start", event_queue, fabric,
                         systems);
      }

      // Run event loop until ALL systems finish AND fabric is idle
      uint64_t quiescence_iters = 0;
      uint64_t drain_chunks = 0;
      while (true) {
        // Step fabric while there are events or in-flight packets
        while (!event_queue.finished() || fabric.tm()->HasInFlight()) {
          if (ledger_enabled && ++drain_chunks % 100 == 0) {
            LedgerQuiescence(interactive_round, "drain", event_queue, fabric,
                             systems);
          }
          if (!event_queue.finished())
            event_queue.proceed();
          else {
            if (ledger_enabled) {
              std::cerr << "[LEDGER][STEP] round=" << interactive_round
                        << " fab_before=" << fabric.tm()->Cycle()
                        << " inflight=" << fabric.tm()->InFlightFlitCount()
                        << " heap=" << event_queue.PendingEventCount()
                        << std::endl;
            }
            event_queue.run_cycles(1000000);
            if (ledger_enabled) {
              std::cerr << "[LEDGER][STEPPED] round=" << interactive_round
                        << " fab_after=" << fabric.tm()->Cycle()
                        << " inflight=" << fabric.tm()->InFlightFlitCount()
                        << " partial=" << fabric.tm()->PartialQueueFlitCount()
                        << " retired=" << fabric.tm()->FlitsRetired()
                        << " req_pkts=" << fabric.tm()->PacketsRequested()
                        << std::endl;
              int _oid = 0, _osrc = 0, _odst = 0, _ovc = 0;
              int64_t _oct = 0, _oit = 0;
              bool _oh = false, _ot = false;
              if (fabric.tm()->SampleOldestInFlight(
                      _oid, _osrc, _odst, _oct, _oit, _oh, _ot, _ovc)) {
                std::cerr << "[LEDGER][OLDEST] round=" << interactive_round
                          << " id=" << _oid << " src=" << _osrc
                          << " dst=" << _odst << " ctime=" << _oct
                          << " itime=" << _oit << " head=" << _oh
                          << " tail=" << _ot << " vc=" << _ovc << std::endl;
              }
            }
          }
        }
        Booksim2NetworkApi::flush_all();

        // Check if ALL systems are done (no pending events in any system)
        bool all_done = true;
        for (auto* sys : systems) {
          if (sys->pending_events > 0) {
            all_done = false;
            break;
          }
        }
        if (all_done && event_queue.finished() && !fabric.tm()->HasInFlight() &&
            !Booksim2NetworkApi::has_pending_groups())
          break;

        // If fabric is idle but systems still have events, step one cycle
        // to let the fabric callback fire and process system events
        if (!all_done && event_queue.finished() && !fabric.tm()->HasInFlight()) {
          event_queue.run_cycles(1);
        }
        if (ledger_enabled && ++quiescence_iters % 10000 == 0) {
          LedgerQuiescence(interactive_round, "outer", event_queue, fabric,
                           systems);
        }
        if (ledger_enabled && quiescence_iters % 1000 == 0) {
          LedgerQuiescence(interactive_round, "spin", event_queue, fabric,
                           systems);
        }
      }

      // Output results: total stays the cumulative wall time (the Python
      // controller keys its monotonic clock off it); exposed is the
      // per-round non-overlapped share (wall_delta - gpu_delta, clamped
      // at 0, and 0 for ranks idle this round).
      uint64_t wall_time = event_queue.get_current_time();
      uint64_t round_wall_delta = wall_time >= round_wall_before ? wall_time - round_wall_before : 0;
      // VeritX: per-packet latency/hop summary for this round's retirements.
      // Machine-parseable one-liner; values are exact (see EmbedTM::PlatStats).
      {
        VeritXEmbed::EmbedTM::PlatSummary ps = fabric.tm()->PlatStats();
        std::cout << "[plat] packets=" << ps.count
                  << " avg=" << ps.avg << " min=" << ps.min
                  << " p50=" << ps.p50 << " p95=" << ps.p95 << " p99=" << ps.p99
                  << " max=" << ps.max
                  << " hops_avg=" << ps.hops_avg
                  << " hops_min=" << ps.hops_min << " hops_max=" << ps.hops_max
                  << std::endl;
      }
      for (int i = 0; i < npus_count; ++i) {
        uint64_t gpu_after = systems[i]->workload->hw_resource->tics_gpu_ops;
        uint64_t comm_after = systems[i]->workload->hw_resource->tics_gpu_comms;
        uint64_t gpu_delta = gpu_after >= round_gpu_before[i] ? gpu_after - round_gpu_before[i] : 0;
        uint64_t comm_delta = comm_after >= round_comm_before[i] ? comm_after - round_comm_before[i] : 0;
        uint64_t exposed = (gpu_delta + comm_delta == 0) ? 0
            : (round_wall_delta >= gpu_delta ? round_wall_delta - gpu_delta : 0);
        std::cout << "[workload] sys[" << i << "] finished, "
                  << wall_time << " cycles, exposed communication "
                  << exposed << " cycles." << std::endl;
      }
      std::cout << "Waiting" << std::endl;
    }
  }

  { // batch mode fallback
    // Batch mode: process initial workload and exit
    for (int i = 0; i < npus_count; ++i) systems[i]->workload->fire();

    while (true) {
      while (!event_queue.finished() || fabric.tm()->HasInFlight()) {
        if (!event_queue.finished())
          event_queue.proceed();
        else
          event_queue.run_cycles(4096);
      }
      Booksim2NetworkApi::flush_all();
      if (event_queue.finished() && !fabric.tm()->HasInFlight() &&
          !Booksim2NetworkApi::has_pending_groups())
        break;
    }
    {
      VeritXEmbed::EmbedTM::PlatSummary ps = fabric.tm()->PlatStats();
      std::cout << "[plat] packets=" << ps.count
                << " avg=" << ps.avg << " min=" << ps.min
                << " p50=" << ps.p50 << " p95=" << ps.p95 << " p99=" << ps.p99
                << " max=" << ps.max
                << " hops_avg=" << ps.hops_avg
                << " hops_min=" << ps.hops_min << " hops_max=" << ps.hops_max
                << std::endl;
    }
  }

  for (auto * s : systems) delete s;
  AstraSim::LoggerFactory::shutdown();
  return 0;
}

/******************************************************************************
VeritX — ASTRA-sim entry point with our BookSim2 fork as the network backend.
Mirrors the analytical frontend's main, but the network is ONE shared
BookSim2 fabric (embedding API) driven by a cycle-based event queue.
*******************************************************************************/

#include <cstring>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

#include "astra-sim/common/Logging.hh"
#include "astra-sim/system/Sys.hh"
#include "Booksim2NetworkApi.hh"
#include "common/CmdLineParser.hh"
#include "extern/network_backend/booksim2/Booksim2Fabric.hh"
#include "remote_memory_backend/analytical/AnalyticalRemoteMemory.hh"

using namespace AstraSim;
using namespace VeritX;

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
  const std::vector<int> npus_count_per_dim{npus_count};

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

  std::vector<int> queues_per_dim(1, num_queues_per_dim);
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
    for (int i = 0; i < npus_count; ++i) {
      std::cout << "[workload] sys[" << i << "] finished, " << wall_time << " cycles, exposed communication " << wall_time << " cycles." << std::endl;
    }
    std::cout << "Waiting" << std::endl;
  }

  // Interactive mode: read subsequent workload paths from stdin
  {

    std::string line;
    while (std::getline(std::cin, line)) {
      // Trim whitespace
      line.erase(0, line.find_first_not_of(" \t\n\r"));
      line.erase(line.find_last_not_of(" \t\n\r") + 1);

      if (line.empty() || line == "pass") {
        // No work — output current time as completion (no new events)
        uint64_t wall_time = event_queue.get_current_time();
        for (int i = 0; i < npus_count; ++i) {
          std::cout << "[workload] sys[" << i << "] finished, "
                    << wall_time << " cycles, exposed communication "
                    << wall_time << " cycles." << std::endl;
        }
        std::cout << "Waiting" << std::endl;
        continue;
      }

      if (line == "exit" || line == "done") {
        break;
      }

      // Reload workload from new path
      for (int i = 0; i < npus_count; ++i) {
        delete systems[i]->workload;
        systems[i]->workload = new Workload(systems[i], line, comm_group_configuration);
      }

      // Fire workloads
      for (int i = 0; i < npus_count; ++i) systems[i]->workload->fire();

      // Run event loop until ALL systems finish AND fabric is idle
      while (true) {
        // Step fabric while there are events or in-flight packets
        while (!event_queue.finished() || fabric.tm()->HasInFlight()) {
          if (!event_queue.finished())
            event_queue.proceed();
          else
            event_queue.run_cycles(1000000);
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
      }

      // Output results for each system using event queue time as wall time
      uint64_t wall_time = event_queue.get_current_time();
      for (int i = 0; i < npus_count; ++i) {
        std::cout << "[workload] sys[" << i << "] finished, "
                  << wall_time << " cycles, exposed communication "
                  << wall_time << " cycles." << std::endl;
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
  }

  for (auto * s : systems) delete s;
  AstraSim::LoggerFactory::shutdown();
  return 0;
}

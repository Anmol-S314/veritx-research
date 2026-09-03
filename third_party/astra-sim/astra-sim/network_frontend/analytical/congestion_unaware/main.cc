/******************************************************************************
This source code is licensed under the MIT license found in the
LICENSE file in the root directory of this source tree.
*******************************************************************************/

#include "astra-sim/common/Logging.hh"
#include "common/CmdLineParser.hh"
#include "congestion_unaware/CongestionUnawareNetworkApi.hh"
#include <iostream>
#include <string>
#include <astra-network-analytical/common/EventQueue.h>
#include <astra-network-analytical/common/NetworkParser.h>
#include <astra-network-analytical/congestion_unaware/Helper.h>
#include <remote_memory_backend/analytical/AnalyticalRemoteMemory.hh>

using namespace AstraSim;
using namespace Analytical;
using namespace AstraSimAnalytical;
using namespace AstraSimAnalyticalCongestionUnaware;
using namespace NetworkAnalytical;
using namespace NetworkAnalyticalCongestionUnaware;

int main(int argc, char* argv[]) {
    // Parse command line arguments
    auto cmd_line_parser = CmdLineParser(argv[0]);
    cmd_line_parser.parse(argc, argv);

    // Get command line arguments
    const auto workload_configuration =
        cmd_line_parser.get<std::string>("workload-configuration");
    const auto comm_group_configuration =
        cmd_line_parser.get<std::string>("comm-group-configuration");
    const auto system_configuration =
        cmd_line_parser.get<std::string>("system-configuration");
    const auto remote_memory_configuration =
        cmd_line_parser.get<std::string>("remote-memory-configuration");
    const auto network_configuration =
        cmd_line_parser.get<std::string>("network-configuration");
    const auto logging_configuration =
        cmd_line_parser.get<std::string>("logging-configuration");
    const auto logging_folder =
        cmd_line_parser.get<std::string>("logging-folder");
    const auto num_queues_per_dim =
        cmd_line_parser.get<int>("num-queues-per-dim");
    const auto comm_scale = cmd_line_parser.get<double>("comm-scale");
    const auto injection_scale = cmd_line_parser.get<double>("injection-scale");
    const auto rendezvous_protocol =
        cmd_line_parser.get<bool>("rendezvous-protocol");

    AstraSim::LoggerFactory::init(logging_configuration, logging_folder);

    // Instantiate event queue
    const auto event_queue = std::make_shared<EventQueue>();

    // Generate topology
    const auto network_parser = NetworkParser(network_configuration);
    const auto topology = construct_topology(network_parser);

    // Get topology information
    const auto npus_count = topology->get_npus_count();
    const auto npus_count_per_dim = topology->get_npus_count_per_dim();
    const auto dims_count = topology->get_dims_count();

    // Set up Network API
    CongestionUnawareNetworkApi::set_event_queue(event_queue);
    CongestionUnawareNetworkApi::set_topology(topology);

    // Create ASTRA-sim related resources
    auto network_apis =
        std::vector<std::unique_ptr<CongestionUnawareNetworkApi>>();
    const auto memory_api =
        std::make_unique<AnalyticalRemoteMemory>(remote_memory_configuration);
    auto systems = std::vector<Sys*>();

    auto queues_per_dim = std::vector<int>();
    for (auto i = 0; i < dims_count; i++) {
        queues_per_dim.push_back(num_queues_per_dim);
    }

    for (int i = 0; i < npus_count; i++) {
        // create network and system
        auto network_api = std::make_unique<CongestionUnawareNetworkApi>(i);
        auto* const system =
            new Sys(i, workload_configuration, comm_group_configuration,
                    system_configuration, memory_api.get(), network_api.get(),
                    npus_count_per_dim, queues_per_dim, injection_scale,
                    comm_scale, rendezvous_protocol);

        // push back network and system
        network_apis.push_back(std::move(network_api));
        systems.push_back(system);
    }

    // Initiate first workload (event_handler) and run
    for (int i = 0; i < npus_count; i++) {
        systems[i]->workload->fire();
    }
    while (!event_queue->finished()) {
        event_queue->proceed();
    }
    std::cout << "Waiting" << std::endl << std::flush;

    // Interactive loop for LLMServingSim (mirrors booksim2/main.cc)
    std::string line;
    while (std::getline(std::cin, line)) {
        size_t a = line.find_first_not_of(" \t\n\r");
        if (a == std::string::npos) continue;
        size_t b = line.find_last_not_of(" \t\n\r");
        line = line.substr(a, b - a + 1);
        if (line.empty()) continue;
        if (line.rfind("pass", 0) == 0) {
            if (line.size() > 4) {
                try {
                    std::string ts = line.substr(5);
                    size_t aa = ts.find_first_not_of(" \t");
                    if (aa != std::string::npos) ts = ts.substr(aa);
                    size_t bb = ts.find_last_not_of(" \t");
                    if (bb != std::string::npos) ts = ts.substr(0, bb + 1);
                    if (!ts.empty()) {
                        uint64_t target = std::stoull(ts);
                        while (!event_queue->finished() && (uint64_t)event_queue->get_current_time() < target) {
                            event_queue->proceed();
                        }
                    }
                } catch (...) {}
            }
            std::cout << "Waiting" << std::endl << std::flush;
            continue;
        }
        if (line == "exit" || line == "done") break;
        for (int i = 0; i < npus_count; ++i) {
            delete systems[i]->workload;
            systems[i]->workload = new Workload(systems[i], line, comm_group_configuration);
        }
        for (int i = 0; i < npus_count; ++i) systems[i]->workload->fire();
        while (!event_queue->finished()) event_queue->proceed();
        std::cout << "Waiting" << std::endl << std::flush;
    }

    for (auto it : systems) delete it;
    systems.clear();
    AstraSim::LoggerFactory::shutdown();
    return 0;
}

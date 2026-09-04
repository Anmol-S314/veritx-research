/******************************************************************************
This source code is licensed under the MIT license found in the
LICENSE file in the root directory of this source tree.
*******************************************************************************/

#include "astra-sim/system/StreamBaseline.hh"

#include "astra-sim/system/astraccl/Algorithm.hh"

#include <cstdlib>
#include <iostream>

using namespace AstraSim;

namespace {
// VERITX_LEDGER>=2: verbose per-stream init tracing.
int veritx_ledger_level() {
    static const int level = [] {
        const char* v = std::getenv("VERITX_LEDGER");
        return v ? std::atoi(v) : 0;
    }();
    return level;
}
}  // namespace

StreamBaseline::StreamBaseline(Sys* owner,
                               DataSet* dataset,
                               int stream_id,
                               std::list<CollectivePhase> phases_to_go,
                               int priority)
    : BaseStream(stream_id, owner, phases_to_go) {
    this->owner = owner;
    this->stream_id = stream_id;
    this->phases_to_go = phases_to_go;
    this->dataset = dataset;
    this->priority = priority;
    steps_finished = 0;
    initial_data_size = phases_to_go.front().initial_data_size;
}

void StreamBaseline::init() {
    initialized = true;
    last_init = Sys::boostedTick();
    if (veritx_ledger_level() >= 2) {
        std::cerr << "[LEDGER][INIT] rank=" << owner->id
                  << " stream_id=" << stream_id
                  << " enabled=" << my_current_phase.enabled
                  << " steps=" << steps_finished << std::endl;
    }
    if (!my_current_phase.enabled) {
        return;
    }
    my_current_phase.algorithm->run(EventType::StreamInit, nullptr);
    if (steps_finished == 1) {
        queuing_delay.push_back(last_phase_change - creation_time);
    }
    queuing_delay.push_back(Sys::boostedTick() - last_phase_change);
    total_packets_sent = 1;
}

void StreamBaseline::call(EventType event, CallData* data) {
    SharedBusStat* sharedBusStat = (SharedBusStat*)data;
    update_bus_stats(BusType::Both, sharedBusStat);
    my_current_phase.algorithm->run(EventType::General, data);
    if (data != nullptr) {
        delete sharedBusStat;
    }
}

void StreamBaseline::consume(RecvPacketEventHandlerData* message) {
    net_message_latency.back() +=
        Sys::boostedTick() - message->ready_time;  // not accurate
    net_message_counter++;
    my_current_phase.algorithm->run(EventType::PacketReceived, message);
}

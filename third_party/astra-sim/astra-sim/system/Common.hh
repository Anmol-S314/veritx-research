/******************************************************************************
This source code is licensed under the MIT license found in the
LICENSE file in the root directory of this source tree.
*******************************************************************************/

#ifndef __COMMON_HH__
#define __COMMON_HH__

#include <cstdint>
#include <string>

namespace AstraSim {

typedef unsigned long long Tick;

constexpr uint64_t CLOCK_PERIOD = 1;           // 1ns
constexpr uint64_t FREQ = 1000 * 1000 * 1000;  // 1GHz

enum time_type_e { SE = 0, MS, US, NS, FS };

enum req_type_e { UINT8 = 0, BFLOAT16, FP32 };

struct timespec_t {
    time_type_e time_res;
    long double time_val;
};

struct sim_request {
    uint32_t srcRank;
    uint32_t dstRank;
    uint32_t tag;
    req_type_e reqType;
    uint64_t reqCount;
    uint32_t vnet;
    uint32_t layerNum;
    // VeritX canonical class attribution (attribution-only, no timing or
    // scheduling effect). Stamped by the collective algorithm from its
    // ComType; Sys::front_end_sim_send backstops NATIVE/RNDZ bands.
    // 0 (kUnknown) = unattributable; qualification must refuse it.
    uint8_t veritx_class_id = 0;
};

class MetaData {
  public:
    timespec_t timestamp;
};

enum class ComType {
    None = 0,
    Reduce_Scatter,
    All_Gather,
    All_Reduce,
    All_to_All,
    All_Reduce_All_to_All
};

// VeritX canonical class id carried from the collective algorithm to the
// embedded BookSim injection call. Must match the Python-side contract
// (VeritXClassId in the VERITX ABI spec): 0=unknown, 1=allreduce,
// 2=reducescatter, 3=allgather, 4=alltoall, 5=native, 6=rendezvous.
enum class VeritXClassId : uint8_t {
    kUnknown = 0,
    kAllReduce = 1,
    kReduceScatter = 2,
    kAllGather = 3,
    kAllToAll = 4,
    kNative = 5,
    kRendezvous = 6
};

// Collective kind -> canonical class. Anything outside the qualified
// envelope (notably All_Reduce_All_to_All) maps to kUnknown: v1 ABI
// cannot attribute it, so qualification must refuse, never guess.
inline VeritXClassId veritx_class_of_comtype(ComType type) {
    switch (type) {
        case ComType::All_Reduce:
            return VeritXClassId::kAllReduce;
        case ComType::Reduce_Scatter:
            return VeritXClassId::kReduceScatter;
        case ComType::All_Gather:
            return VeritXClassId::kAllGather;
        case ComType::All_to_All:
            return VeritXClassId::kAllToAll;
        default:
            return VeritXClassId::kUnknown;
    }
}

enum class CollectiveOptimization { Baseline = 0, LocalBWAware };

enum class CollectiveBarrier { Blocking = 0, Non_Blocking };

enum class SchedulingPolicy { LIFO = 0, FIFO, EXPLICIT, None };

enum class IntraDimensionScheduling {
    FIFO = 0,
    RG,
    SmallestFirst,
    LessRemainingPhaseFirst
};

enum class InterDimensionScheduling {
    Ascending = 0,
    OnlineGreedy,
    RoundRobin,
    OfflineGreedy,
    OfflineGreedyFlex
};

enum class InjectionPolicy {
    Infinite = 0,
    Aggressive,
    SemiAggressive,
    ExtraAggressive,
    Normal
};

enum class PacketRouting { Hardware = 0, Software };

enum class BusType { Both = 0, Shared, Mem };

enum class StreamState {
    Created = 0,
    Transferring,
    Ready,
    Executing,
    Zombie,
    Dead
};

enum class EventType {
    CallEvents = 0,
    General,
    RendezvousSend,
    RendezvousRecv,
    PacketReceived,
    PacketSent,
    Rec_Finished,
    Send_Finished,
    Processing_Finished,
    NPU_to_MA,
    MA_to_NPU,
    Consider_Process,
    Consider_Retire,
    Consider_Send_Back,
    StreamInit,
    CommProcessingFinished,
    CollectiveCommunicationFinished,
    CompFinished,
    MemLoadFinished,
    MemStoreFinished
};

}  // namespace AstraSim

#endif /* __COMMON_HH__ */

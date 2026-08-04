// T3 NoC multicast microbenchmark — SENDER kernel (one Tensix data-movement core).
//
// Reads a payload from DRAM bank 0 into local L1 once, then multicasts it from L1 to a
// rectangular block of `num_dests` destination cores `repeat` times. Host times the whole
// program; (wall-time / repeat) vs num_dests is the result — flat => multicast is ~free in
// fanout, linear => it degenerates to serial unicast.
//
// All four rectangle coords are PHYSICAL NoC coordinates (get_noc_multicast_addr requires
// them; see host note on Wormhole grid holes). The host guarantees the rect contains only
// Tensix cores and never the col-5 DRAM column. The sender is NOT inside the rect (host
// picks blocks accordingly), so num_dests is exact.
#include <cstdint>
#include "dataflow_api.h"

void kernel_main() {
    uint32_t dram_src_addr = get_arg_val<uint32_t>(0);  // payload in DRAM (bank 0)
    uint32_t l1_addr       = get_arg_val<uint32_t>(1);  // payload L1 offset (sender + receivers)
    uint32_t size          = get_arg_val<uint32_t>(2);  // payload bytes
    uint32_t x_start       = get_arg_val<uint32_t>(3);  // dest rect, PHYSICAL NoC coords
    uint32_t y_start       = get_arg_val<uint32_t>(4);
    uint32_t x_end         = get_arg_val<uint32_t>(5);
    uint32_t y_end         = get_arg_val<uint32_t>(6);
    uint32_t num_dests     = get_arg_val<uint32_t>(7);  // receivers (sender excluded)
    uint32_t repeat        = get_arg_val<uint32_t>(8);

    // 1) pull the payload into local L1 once (this cost is amortised over `repeat`).
    // VERIFY: the mesh buffer landed in DRAM bank 0 on WH for these small sizes.
    uint64_t dram_noc_addr = get_noc_addr_from_bank_id<true>(0, dram_src_addr);
    noc_async_read(dram_noc_addr, l1_addr, size);
    noc_async_read_barrier();

    // 2) multicast that L1 buffer to the dest rect `repeat` times, pipelined (no barrier
    //    inside the loop; the NOC async queue absorbs the back-to-back writes).
    uint64_t dst_mcast_addr =
        get_noc_multicast_addr(x_start, y_start, x_end, y_end, l1_addr);
    for (uint32_t i = 0; i < repeat; i++) {
        noc_async_write_multicast(l1_addr, dst_mcast_addr, size, num_dests);
    }
    noc_async_write_barrier();
}
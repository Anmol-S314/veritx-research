// T3 NoC multicast microbenchmark — SENDER kernel (runs on one Tensix data-movement core).
//
// Reads a payload from DRAM into local L1 once, then multicasts it from L1 to a rectangle
// of `num_dests` destination cores `repeat` times. Host times the whole program; the shape
// of (wall-time / repeat) vs num_dests is the result (flat => multicast ~free in fanout).
//
// DRAFT: grounded in tt-metal `main` data-movement API, NOT yet compiled. See ../../README.md
// punch-list. `// VERIFY:` marks spots to confirm against the SDK on the card.
#include <cstdint>
#include "dataflow_api.h"

void kernel_main() {
    uint32_t dram_src_addr = get_arg_val<uint32_t>(0);  // payload in DRAM
    uint32_t dram_bank_id  = get_arg_val<uint32_t>(1);
    uint32_t l1_addr       = get_arg_val<uint32_t>(2);  // L1 offset, same on sender + dests
    uint32_t size          = get_arg_val<uint32_t>(3);  // payload bytes
    uint32_t num_dests     = get_arg_val<uint32_t>(4);  // fanout N
    uint32_t x_start       = get_arg_val<uint32_t>(5);  // dest rectangle (NoC coords)
    uint32_t y_start       = get_arg_val<uint32_t>(6);
    uint32_t x_end         = get_arg_val<uint32_t>(7);
    uint32_t y_end         = get_arg_val<uint32_t>(8);
    uint32_t repeat        = get_arg_val<uint32_t>(9);

    // 1) pull the payload into local L1 once (this cost is amortised by `repeat`).
    uint64_t dram_noc_addr = get_noc_addr_from_bank_id<true>(dram_bank_id, dram_src_addr);  // VERIFY: DRAM addr helper name
    noc_async_read(dram_noc_addr, l1_addr, size);
    noc_async_read_barrier();

    // 2) multicast that L1 buffer to the destination rectangle, `repeat` times.
    // VERIFY: if the sender core is inside [x_start..x_end]x[y_start..y_end], swap for
    //         noc_async_write_multicast_loopback_src, else it is excluded (num_dests correct).
    uint64_t dst_mcast_addr = get_noc_multicast_addr(x_start, y_start, x_end, y_end, l1_addr);
    for (uint32_t i = 0; i < repeat; i++) {
        noc_async_write_multicast(l1_addr, dst_mcast_addr, size, num_dests);
    }
    noc_async_write_barrier();
}

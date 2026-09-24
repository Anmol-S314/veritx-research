// T3 NoC multicast microbenchmark — HOST program.
//
// Sweeps fanout and payload size; for each, launches mcast_sender on one Tensix core
// which multicasts an L1 payload to an SxS block of destination cores REPEAT times.
// Host times each run and prints wall-time-per-multicast + aggregate delivered GB/s.
//
// THE TEST (see README): does wall-time-per-multicast stay ~FLAT as fanout grows
// (multicast forks across the NoC in one pass, as interchip_roofline.py / SCHEDULE.md
// assume) or grow ~LINEARLY (multicast degenerates to a serial unicast loop)? The
// *shape* is the result, not the absolute number.
//
// COORDINATES — verified against the current tt-metal API (see tt-metal docs:
// get_noc_multicast_addr takes PHYSICAL NoC coordinates). Wormhole's NoC grid has
// holes — cols {0,5} (ARC / DRAM) and rows {0,6} (Ethernet) are not Tensix, and
// logical Tensix coords skip them — so a multicast rectangle must never span them.
// The dest block is anchored in the physical col 1..4 x row 1..4 sub-grid (sender at
// logical {0,0} -> physical {1,1}), which contains ONLY Tensix cores. A rect spanning
// col 5 would multicast into DRAM nodes.
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <vector>

#include <tt-metalium/host_api.hpp>
#include <tt-metalium/device.hpp>
#include <tt-metalium/core_coord.hpp>
#include <tt-metalium/distributed.hpp>

using namespace tt::tt_metal;

#ifndef OVERRIDE_KERNEL_PREFIX
#define OVERRIDE_KERNEL_PREFIX ""
#endif

int main() {
    constexpr int device_id = 0;
    auto mesh_device = distributed::MeshDevice::create_unit_mesh(device_id);
    distributed::MeshCommandQueue& cq = mesh_device->mesh_command_queue();

    const CoreCoord grid = mesh_device->compute_with_storage_grid_size();

    // Dest blocks are SxS squares anchored at the sender (logical {0,0} = physical {1,1}).
    // S <= 3 keeps the PHYSICAL rectangle inside cols 1..4 x rows 1..4 (the mcast rect
    // must not contain the col-5 DRAM column). Fanouts: S=1 -> 1 dest, S=2 -> 3, S=3 -> 8.
    const std::vector<uint32_t> block_sizes = {1, 2, 3};
    const uint32_t max_block = 3;
    if (grid.x < max_block || grid.y < max_block) {
        printf("  ✗ worker grid %ux%u too small for a %ux%u dest block\n",
               (uint32_t)grid.x, (uint32_t)grid.y, max_block, max_block);
        mesh_device->close();
        return 1;
    }

    const CoreCoord sender_logical = {0, 0};

    // Multicast target L1 offset on every core (payload landing zone, sender + receivers).
    // 128 KiB sits above the DM kernel region on WH (L1 ~1.46 MiB) and below any collision;
    // payload sizes are capped at 64 KiB to stay under it.  // VERIFY: on-card.
    constexpr uint32_t L1_SCRATCH = 128 * 1024;
    constexpr uint32_t REPEAT = 1000;  // amortises host dispatch latency into the per-op time

    const std::vector<uint32_t> sizes = {2048, 8192, 32768, 65536};

    printf("%10s %8s %10s %16s\n", "size_B", "dests", "us/op", "delivered_GBps");
    for (uint32_t size : sizes) {
        // One replicated DRAM mesh buffer holds the payload (unit mesh => one device).
        distributed::DeviceLocalBufferConfig dram_cfg{
            .page_size = size, .buffer_type = BufferType::DRAM};
        distributed::ReplicatedBufferConfig buf_cfg{.size = size};
        auto src = distributed::MeshBuffer::create(buf_cfg, dram_cfg, mesh_device.get());
        std::vector<uint32_t> payload(size / sizeof(uint32_t), 0xA5A5A5A5);
        distributed::EnqueueWriteMeshBuffer(cq, src, payload, false);

        for (uint32_t s : block_sizes) {
            // Dest rect in LOGICAL coords, then translated to PHYSICAL for the kernel.
            CoreCoord rect_a_logical, rect_b_logical;
            uint32_t num_dests;
            if (s == 1) {
                // Fanout 1 baseline: multicast to a single remote core.
                rect_a_logical = rect_b_logical = {1, 0};
                num_dests = 1;
            } else {
                // Sender {0,0} sits inside the SxS rect; non-loopback multicast skips it.
                rect_a_logical = {0, 0};
                rect_b_logical = {(size_t)s - 1, (size_t)s - 1};
                num_dests = s * s - 1;
            }
            const CoreCoord rect_a_noc =
                mesh_device->worker_core_from_logical_core(rect_a_logical);
            const CoreCoord rect_b_noc =
                mesh_device->worker_core_from_logical_core(rect_b_logical);

            Program program = CreateProgram();
            auto kernel = CreateKernel(
                program,
                OVERRIDE_KERNEL_PREFIX "noc_multicast_bw/kernels/dataflow/mcast_sender.cpp",
                sender_logical,
                DataMovementConfig{.processor = DataMovementProcessor::RISCV_0,
                                   .noc = NOC::RISCV_0_default});
            SetRuntimeArgs(
                program, kernel, sender_logical,
                {src->address(), L1_SCRATCH, size,
                 (uint32_t)rect_a_noc.x, (uint32_t)rect_a_noc.y,
                 (uint32_t)rect_b_noc.x, (uint32_t)rect_b_noc.y,
                 num_dests, REPEAT});

            distributed::MeshWorkload workload;
            distributed::MeshCoordinateRange dev_range(mesh_device->shape());
            workload.add_program(dev_range, std::move(program));

            auto t0 = std::chrono::steady_clock::now();
            distributed::EnqueueMeshWorkload(cq, workload, false);
            distributed::Finish(cq);
            auto t1 = std::chrono::steady_clock::now();

            const double us_total =
                std::chrono::duration<double, std::micro>(t1 - t0).count();
            const double bytes_total = (double)size * num_dests * REPEAT;
            printf("%10u %8u %9.3f %16.2f\n", size, num_dests, us_total / REPEAT,
                   bytes_total / (us_total * 1e-6) / 1e9);
        }
    }
    mesh_device->close();
    return 0;
}

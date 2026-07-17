// T3 NoC multicast microbenchmark — HOST program.
//
// Sweeps fanout N and payload size; for each, launches mcast_sender on core (0,0) which
// multicasts a payload to an NxN-ish rectangle of destination cores REPEAT times. Times the
// program on the host and prints wall-time-per-multicast + aggregate delivered GB/s.
//
// THE TEST (see README): does wall-time-per-multicast stay ~FLAT as N grows (multicast is a
// real bandwidth lever, as interchip_roofline.py assumes) or grow ~LINEARLY (multicast
// degenerates to serial unicast on this NoC)? The *shape* is the result.
//
// DRAFT: grounded in tt-metal `main` MeshDevice API, NOT yet compiled. `// VERIFY:` = confirm
// on the card. See README punch-list.
#include <chrono>
#include <cstdint>
#include <vector>
#include <cstdio>

#include "tt_metal/host_api.hpp"
#include "tt_metal/impl/device/mesh_device.hpp"

using namespace tt::tt_metal;

int main() {
    constexpr int device_id = 0;
    auto mesh_device = distributed::MeshDevice::create_unit_mesh(device_id);
    auto& cq = mesh_device->mesh_command_queue();

    constexpr CoreCoord sender = {0, 0};
    constexpr uint32_t L1_SCRATCH = 128 * 1024;   // VERIFY: an unreserved L1 offset for the payload
    constexpr uint32_t REPEAT = 1000;             // amortise host-side dispatch latency

    // Sweep payload size x fanout. Destination rectangle starts at (1,0) so the sender (0,0)
    // is excluded; grows along +x. VERIFY: worker-grid extent + logical-vs-NoC coords on WH.
    const std::vector<uint32_t> sizes = {2048, 8192, 32768, 131072};
    const std::vector<uint32_t> fanouts = {1, 2, 4, 8, 16, 32};

    printf("%10s %6s %14s %16s\n", "size_B", "N", "us/mcast", "delivered_GBps");
    for (uint32_t size : sizes) {
        // one DRAM source buffer holds the payload
        distributed::DeviceLocalBufferConfig dram_cfg{
            .page_size = size, .buffer_type = BufferType::DRAM};
        distributed::ReplicatedBufferConfig buf_cfg{.size = size};
        auto src = distributed::MeshBuffer::create(buf_cfg, dram_cfg, mesh_device.get());
        std::vector<uint32_t> payload(size / sizeof(uint32_t), 0xA5A5A5A5);
        distributed::EnqueueWriteMeshBuffer(cq, src, payload, false);

        for (uint32_t N : fanouts) {
            Program program = CreateProgram();
            // destination rectangle: (1,0) .. (N,0)   VERIFY: keep within worker grid width
            const uint32_t x_start = 1, y_start = 0, x_end = N, y_end = 0;

            // Reserve the multicast target L1 offset on sender + all destinations so the
            // write lands in a known region.  VERIFY: CB config + that this covers dests.
            CoreRange all_cores({0, 0}, {x_end, y_end});
            CircularBufferConfig cb_cfg(size, {{0, tt::DataFormat::UInt32}});  // VERIFY: cb index/format/addr
            cb_cfg.set_page_size(0, size);
            CreateCircularBuffer(program, all_cores, cb_cfg);

            KernelHandle k = CreateKernel(
                program, "tracks/t3-topology/hardware/kernels/dataflow/mcast_sender.cpp",
                sender, DataMovementConfig{.processor = DataMovementProcessor::RISCV_0,
                                           .noc = NOC::RISCV_0_default});
            SetRuntimeArgs(program, k, sender,
                {src->address(), /*bank*/ 0, L1_SCRATCH, size, N,
                 x_start, y_start, x_end, y_end, REPEAT});

            distributed::MeshWorkload workload;
            distributed::MeshCoordinateRange dev_range(mesh_device->shape());  // VERIFY: unit-mesh range ctor
            workload.add_program(dev_range, std::move(program));

            auto t0 = std::chrono::high_resolution_clock::now();
            distributed::EnqueueMeshWorkload(cq, workload, false);
            distributed::Finish(cq);
            auto t1 = std::chrono::high_resolution_clock::now();

            double us = std::chrono::duration<double, std::micro>(t1 - t0).count();
            double us_per = us / REPEAT;
            double delivered_GBps = (double)size * N * REPEAT / (us * 1e-6) / 1e9;
            printf("%10u %6u %14.3f %16.2f\n", size, N, us_per, delivered_GBps);
        }
    }
    mesh_device->close();
    return 0;
}

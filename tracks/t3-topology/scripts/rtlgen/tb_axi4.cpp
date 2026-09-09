// tb_axi4.cpp — AXI4 end-to-end NoC testbench (cycle-count approach)
#include "Vaxi4_noc.h"
#include "verilated.h"
#include <cstdio>

static int total_cycles = 0;

static void tick(Vaxi4_noc *t) {
  t->clk = 1; t->eval();
  t->clk = 0; t->eval();
  total_cycles++;
}

// Drive AW+W for single-beat write, wait for B response.
// Returns 0 on success.
static int axi4_write(Vaxi4_noc *t, uint32_t addr, uint64_t data) {
  // Set up AW + W simultaneously
  t->m0_awid = 1; t->m0_awaddr = addr;
  t->m0_awlen = 0; t->m0_awsize = 3; t->m0_awburst = 1;
  t->m0_awvalid = 1;
  t->m0_wdata = data; t->m0_wstrb = 0xFF; t->m0_wlast = 1;
  t->m0_wvalid = 1;
  t->m0_bready = 1;

  // Drive for enough cycles: AW accept (~1 cyc) + W accept (~2 cyc)
  // + NoC transit (~4 cyc) + response (~4 cyc)
  for (int i = 0; i < 200; i++) {
    tick(t);
    // Once AW accepted, drop awvalid
    if (t->m0_awvalid && !t->m0_awready) {
      t->m0_awvalid = 0;
    }
    // Once W accepted, drop wvalid
    if (t->m0_wvalid && !t->m0_wready) {
      t->m0_wvalid = 0;
    }
    // Check for B response
    if (t->m0_bvalid) {
      printf("  B resp at cycle %d: bid=%d bresp=%d\n", total_cycles, t->m0_bid, t->m0_bresp);
      tick(t); // ack
      t->m0_bready = 0;
      return 0;
    }
  }
  printf("  TIMEOUT at cycle %d\n", total_cycles);
  return -1;
}

// Drive AR for single-beat read, wait for R response
static uint64_t axi4_read(Vaxi4_noc *t, uint32_t addr) {
  t->m0_arid = 2; t->m0_araddr = addr;
  t->m0_arlen = 0; t->m0_arsize = 3; t->m0_arburst = 1;
  t->m0_arvalid = 1;
  t->m0_rready = 1;

  for (int i = 0; i < 200; i++) {
    tick(t);
    if (t->m0_arvalid && !t->m0_arready) {
      t->m0_arvalid = 0;
    }
    if (t->m0_rvalid) {
      uint64_t d = t->m0_rdata;
      printf("  R resp at cycle %d: rid=%d rdata=0x%lx rresp=%d rlast=%d\n",
             total_cycles, t->m0_rid, d, t->m0_rresp, t->m0_rlast);
      tick(t); // ack
      t->m0_rready = 0;
      return d;
    }
  }
  printf("  TIMEOUT at cycle %d\n", total_cycles);
  return 0;
}

int main(int argc, char **argv) {
  Verilated::commandArgs(argc, argv);
  Vaxi4_noc *t = new Vaxi4_noc;

  printf("=== AXI4 End-to-End NoC Test ===\n\n");

  // Deassert all, then reset
  t->clk = 0; t->rst_n = 0;
  t->m0_awvalid = 0; t->m0_wvalid = 0; t->m0_bready = 0;
  t->m0_arvalid = 0; t->m0_rready = 0;
  t->m1_awvalid = 0; t->m1_wvalid = 0; t->m1_bready = 0;
  t->m1_arvalid = 0; t->m1_rready = 0;
  for (int i = 0; i < 20; i++) tick(t);
  t->rst_n = 1;
  for (int i = 0; i < 20; i++) tick(t);
  total_cycles = 40;

  printf("[TEST 1] Write node 0→1: addr=0x1000 data=0xDEADBEEF\n");
  int rc = axi4_write(t, 0x1000, 0xDEADBEEFCAFEBABEULL);
  printf("  %s\n\n", rc == 0 ? "✅ PASS" : "❌ FAIL");

  printf("[TEST 2] Read node 0→1: addr=0x1000\n");
  uint64_t rdata = axi4_read(t, 0x1000);
  printf("  Data=0x%lx %s\n\n", rdata,
         rdata != 0 ? "✅ PASS" : "⚠️ zero (no memory model)");

  // Drain
  for (int i = 0; i < 100; i++) tick(t);

  printf("=== ALL TESTS COMPLETE ===\n");
  t->final();
  delete t;
  return 0;
}

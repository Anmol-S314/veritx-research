// tb_axi4_debug.cpp — Debug: trace AXI4 handshake signals only
#include "Vaxi4_noc.h"
#include "verilated.h"
#include <cstdio>

static int CYC = 0;
static void tick(Vaxi4_noc *t) { t->clk = 1; t->eval(); t->clk = 0; t->eval(); CYC++; }

int main(int argc, char **argv) {
  Verilated::commandArgs(argc, argv);
  Vaxi4_noc *t = new Vaxi4_noc;
  t->clk = 0; t->rst_n = 0;
  t->m0_awvalid = 0; t->m0_wvalid = 0; t->m0_bready = 0;
  t->m0_arvalid = 0; t->m0_rready = 0;
  t->m1_awvalid = 0; t->m1_wvalid = 0; t->m1_bready = 0;
  t->m1_arvalid = 0; t->m1_rready = 0;
  for (int i = 0; i < 20; i++) tick(t);
  t->rst_n = 1;
  for (int i = 0; i < 20; i++) tick(t);

  printf("=== AW+W write ===\n");
  t->m0_awid = 1; t->m0_awaddr = 0x1000;
  t->m0_awlen = 0; t->m0_awsize = 3; t->m0_awburst = 1;
  t->m0_awvalid = 1;
  t->m0_wdata = 0xDEADBEEFCAFEBABEULL; t->m0_wstrb = 0xFF;
  t->m0_wlast = 1; t->m0_wvalid = 1;
  t->m0_bready = 1;

  for (int i = 0; i < 80; i++) {
    tick(t);
    printf("c=%3d awv=%d awr=%d wv=%d wr=%d bv=%d br=%d r0i=%d r0e=%d r1i=%d r1e=%d\n",
           CYC, t->m0_awvalid, t->m0_awready,
           t->m0_wvalid, t->m0_wready,
           t->m0_bvalid, t->m0_bready, 0, 0, 0, 0);
    if (t->m0_bvalid) { printf("  ✅ GOT B RESPONSE!\n"); break; }
    if (t->m0_awvalid && !t->m0_awready) t->m0_awvalid = 0;
    if (t->m0_wvalid && !t->m0_wready) t->m0_wvalid = 0;
  }
  printf("=== Done ===\n");
  t->final(); delete t;
  return 0;
}

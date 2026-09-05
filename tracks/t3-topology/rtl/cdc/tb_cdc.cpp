// tb_cdc.cpp — Verilator testbench for cdc_fifo.
// Two independent clocks (wr 10ns, rd 7ns), edge-driven scheduling (canonical):
//   * a write attempt every T_WR unless stalled (forced stalls every 4th)
//   * a read attempt every T_RD unless stalled (forced stalls every 5th)
// Verify: NO LOSS (every accepted write is read exactly once), NO CORRUPTION
// (seq + pattern intact, in order), drains fully.
#include "Vcdc_fifo.h"
#include "verilated.h"
#include <cstdio>
#include <cstdlib>

static const unsigned long long T_WR = 10;
static const unsigned long long T_RD = 7;
static const int N = 2000;
static const unsigned long long PATTERN = 0xCAFEF00DULL;

int main(int argc, char** argv) {
  Verilated::commandArgs(argc, argv);
  Vcdc_fifo* dut = new Vcdc_fifo;

  dut->wr_clk = 0; dut->wr_rst_n = 0;
  dut->rd_clk = 0; dut->rd_rst_n = 0;
  dut->wr_en = 0; dut->rd_en = 0; dut->wr_data = 0;
  dut->eval();

  // reset: 5 write edges + 5 read edges with rst deasserted
  for (int i = 0; i < 10; i++) { dut->wr_clk = !dut->wr_clk; dut->eval(); }
  for (int i = 0; i < 10; i++) { dut->rd_clk = !dut->rd_clk; dut->eval(); }
  dut->wr_rst_n = 1; dut->rd_rst_n = 1; dut->eval();

  unsigned long long t = 0;
  unsigned long long nxt_wr = T_WR/2;       // first wr rising edge
  unsigned long long nxt_rd = 0;            // first rd rising edge (start at 0)
  unsigned long long issued = 0, accepted = 0, read = 0;
  unsigned long long next_seq = 1;
  bool mismatch = false, loss = false;
  bool pending_write = false;
  unsigned long long pending_seq = 0;
  bool rd_pending_read = false;
  uint64_t rd_captured = 0;

  // iteration cap
  while (t < 20000000ULL) {
    unsigned long long next_t = nxt_wr < nxt_rd ? nxt_wr : nxt_rd;
    t = next_t;
    if (t == nxt_wr) {
      // Pre-edge sampling: the module's FF samples (wr_en && !wr_full) with the
      // PRE-EDGE combinational values, so acceptance accounting must match.
      bool full_pre = dut->wr_full;
      if (pending_write) {
        if (!full_pre) {
          accepted++;
          pending_write = false;
        } // else: keep pending (retry next wr edge)
      } else if (issued < N) {
        // issue a write unless this is a forced-stall slot (TIME-based, never locks)
        if ((t / T_WR) % 4 != 0) {
          pending_seq = issued + 1;
          uint64_t f = ((pending_seq & 0x1FFF) << 32) | PATTERN;
          dut->wr_data = f;
          dut->wr_en = 1;
          pending_write = true;
        }
        issued++;
      }
      if (issued >= N && !pending_write) dut->wr_en = 0;
      dut->wr_clk = 1; dut->eval();            // wr rising edge
      dut->wr_clk = 0; dut->eval();            // fall for next cycle
      nxt_wr = t + T_WR;
    }
    if (t == nxt_rd) {
      // (pre-edge: clk=0, stable) account the read ARMED at the previous edge:
      // that edge consumed it iff rd_en was high and non-empty then (both true
      // by construction when armed).
      if (rd_pending_read) {
        uint64_t d = rd_captured;
        uint64_t seq = (d >> 32) & 0x1FFF;
        if (seq != next_seq) {
          printf("MISMATCH read#%llu: seq %llu expected %llu\n", read, seq, next_seq);
          mismatch = true;
        }
        if ((d & 0xFFFFFFFFULL) != PATTERN) {
          printf("CORRUPT read#%llu: %016llx\n", read, (unsigned long long)d);
          mismatch = true;
        }
        next_seq++; read++;
        rd_pending_read = false;
      }
      // schedule the NEXT consumption for this edge: capture pre-edge data and
      // assert rd_en; the module samples (rd_en && !rd_empty) at this edge.
      if (!dut->rd_empty && (t / T_RD) % 5 != 0) {
        rd_captured = dut->rd_data;
        rd_pending_read = true;
        dut->rd_en = 1;
      } else {
        dut->rd_en = 0;
      }
      dut->rd_clk = 1; dut->eval();            // rd rising edge (consumes if armed)
      dut->rd_clk = 0; dut->eval();
      nxt_rd = t + T_RD;
    }
    if (issued >= N && accepted >= N && read >= N) break;
  }

  loss = (accepted != (unsigned long long)N) || (read != (unsigned long long)N);
  bool pass = !mismatch && !loss;
  printf("\n=== CDC FIFO RESULTS ===\n");
  printf("issued=%llu accepted=%llu read=%llu next_seq=%llu\n", issued, accepted, read, next_seq);
  printf("loss/corrupt: %s\n", (loss || mismatch) ? "FAIL" : "OK (none)");
  printf("status: %s\n", pass ? "PASS" : "FAIL");
  dut->final();
  delete dut;
  return pass ? 0 : 1;
}
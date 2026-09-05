// cdc_fifo.sv — asynchronous FIFO for die-to-die / clock-domain crossings (GALS).
//
// Used at NoI/NoL boundaries where each die runs its own clock (mesochronous or
// unrelated). Standard robust design:
//   * dual-clock RAM (register array) with binary read/write pointers
//   * gray-code pointers (single-bit change per increment) + 2-flop synchronizers
//     on the OPPOSITE clock -> only ever sampling a still-valid or one-tick-old
//     pointer; full/empty are conservative (no data corruption)
//   * full compares the NEXT write pointer against the synchronized read pointer
//     (MSB-inverted gray trick); empty compares read vs synchronized write
//
// Params: DATA_W (our flit is 64b), DEPTH (power of two), STAGES (sync flops).
// Protocol (AXI-ready style): wr_en && !wr_full writes; rd_en && !rd_empty reads.
module cdc_fifo #(
  parameter int DATA_W = 64,
  parameter int DEPTH  = 8,
  parameter int STAGES = 2
) (
  input  logic              wr_clk,
  input  logic              wr_rst_n,
  input  logic              wr_en,
  input  logic [DATA_W-1:0] wr_data,
  output logic              wr_full,

  input  logic              rd_clk,
  input  logic              rd_rst_n,
  input  logic              rd_en,
  output logic [DATA_W-1:0] rd_data,
  output logic              rd_valid,   // registered: data+valid pair at edge K
                                        // = the flit consumed AT edge K
  output logic              rd_empty
);

  // Virtual depth: FULL fires at VDEPTH = DEPTH/2. The remaining DEPTH/2 slots
  // are shadow capacity that absorbs the synchronizer lag; without this margin
  // a fast writer + stalling reader lets the lagged FULL assert late and
  // overwrite unread head slots (proven lossy at 6ns-wr / 10ns-rd with DEPTH=16;
  // see experiments/cdc_gals_bridge.md).
  localparam int VDEPTH = DEPTH >> 1;
  localparam int PTR_W = $clog2(VDEPTH);   // pointer counts 0..DEPTH-1 (2*VDEPTH)
  localparam int A_W   = PTR_W + 1;        // MSB distinguishes full vs empty

  logic [DATA_W-1:0] mem [0:DEPTH-1];

  logic [A_W-1:0] wr_ptr_bin, wr_ptr_gray, wr_ptr_gray_next, wr_ptr_next;
  logic [A_W-1:0] rd_ptr_bin, rd_ptr_gray, rd_ptr_gray_next, rd_ptr_next;
  logic [A_W-1:0] rd_ptr_sync_w, wr_ptr_sync_r;   // synchronized (opposite clock)

  function automatic logic [A_W-1:0] bin2gray(input logic [A_W-1:0] b);
    return (b >> 1) ^ b;
  endfunction

  // ── Write side ──────────────────────────────────────────────────────────────
  always_comb begin
    // Unconditional +1 candidate; the FF only registers it when accepted.
    // (Full must NOT feed the next-pointer computation - comb loop.)
    wr_ptr_next      = wr_ptr_bin + 1'b1;
    wr_ptr_gray_next = bin2gray(wr_ptr_next);
  end

  always_ff @(posedge wr_clk or negedge wr_rst_n) begin
    if (!wr_rst_n) begin
      wr_ptr_bin  <= '0;
      wr_ptr_gray <= '0;
    end else if (wr_en && !wr_full) begin
      mem[wr_ptr_bin[A_W-1:0]] <= wr_data;
      wr_ptr_bin  <= wr_ptr_next;
      wr_ptr_gray <= wr_ptr_gray_next;
    end
  end

  // ── Write-side synchronizer: sample read pointer (gray) on wr_clk ───────────
  logic [A_W-1:0] rd_ptr_sync_ff [STAGES:1];
  always_ff @(posedge wr_clk or negedge wr_rst_n) begin
    if (!wr_rst_n) begin
      for (int s = 1; s <= STAGES; s++) rd_ptr_sync_ff[s] <= '0;
    end else begin
      rd_ptr_sync_ff[1] <= rd_ptr_gray;
      for (int s = 2; s <= STAGES; s++) rd_ptr_sync_ff[s] <= rd_ptr_sync_ff[s-1];
    end
  end
  assign rd_ptr_sync_w = rd_ptr_sync_ff[STAGES];

  // Conservative FULL: next write pointer equals synchronized read pointer with
  // MSB-2 inverted (gray full condition).
  assign wr_full = (wr_ptr_gray_next == {~rd_ptr_sync_w[A_W-1:A_W-2],
                                         rd_ptr_sync_w[A_W-3:0]});

  // ── Read side ───────────────────────────────────────────────────────────────
  always_comb begin
    rd_ptr_next      = rd_ptr_bin + 1'b1;
    rd_ptr_gray_next = bin2gray(rd_ptr_next);
  end

  always_ff @(posedge rd_clk or negedge rd_rst_n) begin
    if (!rd_rst_n) begin
      rd_ptr_bin  <= '0;
      rd_ptr_gray <= '0;
    end else if (rd_en && !rd_empty) begin
      rd_ptr_bin  <= rd_ptr_next;
      rd_ptr_gray <= rd_ptr_gray_next;
    end
  end

  // Registered read data + valid: at edge K, rd_data_r latches mem[pre-K head]
  // and rd_valid_r latches (rd_en && !rd_empty) -- so the (rd_valid, rd_data)
  // pair observed after edge K IS the flit consumed at edge K. No combinational
  // hazards, no pre/post-edge ambiguity for the consumer.
  logic [DATA_W-1:0] rd_data_r;
  logic rd_valid_r;
  always_ff @(posedge rd_clk or negedge rd_rst_n) begin
    if (!rd_rst_n) begin
      rd_data_r  <= '0;
      rd_valid_r <= 1'b0;
    end else begin
      rd_data_r  <= mem[rd_ptr_bin[A_W-1:0]];
      rd_valid_r <= rd_en && !rd_empty;
    end
  end
  assign rd_data  = rd_data_r;
  assign rd_valid = rd_valid_r;

  // ── Read-side synchronizer: sample write pointer (gray) on rd_clk ───────────
  logic [A_W-1:0] wr_ptr_sync_ff [STAGES:1];
  always_ff @(posedge rd_clk or negedge rd_rst_n) begin
    if (!rd_rst_n) begin
      for (int s = 1; s <= STAGES; s++) wr_ptr_sync_ff[s] <= '0;
    end else begin
      wr_ptr_sync_ff[1] <= wr_ptr_gray;
      for (int s = 2; s <= STAGES; s++) wr_ptr_sync_ff[s] <= wr_ptr_sync_ff[s-1];
    end
  end
  assign wr_ptr_sync_r = wr_ptr_sync_ff[STAGES];

  assign rd_empty = (rd_ptr_gray == wr_ptr_sync_r);

  // ── Assertions (Verilator checkable) ─────────────────────────────────────────
  // A write is never accepted when full; a read never when empty.
  // (functional assertions enforced by the TB via full/empty gating)

endmodule
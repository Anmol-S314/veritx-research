`default_nettype none

// Memory bank demux/merge for the composed family path.
//
// N memory endpoints share ONE router ejection port. The request flit carries
// a bank index; this module steers the request to that bank and merges the
// banks' responses back onto the single response port.
//
// Contract:
//   * a request goes to bank req_flit[BANK_LSB +: BANK_W]; the bank sees the
//     same flit the router delivered (the bank field is ignored by it);
//   * each bank keeps its own ordering: requests to one bank are issued in
//     arrival order, so a read observes every earlier write to that bank;
//   * the request port is head-of-line: a request for a busy bank holds the
//     port until that bank accepts it (correct, not maximum throughput);
//   * responses from different banks may return out of issue order; the
//     response flit already names its initiator and sequence, so attribution
//     does not depend on order;
//   * the response port is round-robin over banks with a valid response, and
//     once it presents a response it holds that bank until the handshake, so
//     rsp_flit/rsp_valid never change while rsp_ready is low;
//   * a bank index >= N_BANKS cannot be steered anywhere: the flit is consumed
//     so the port does not deadlock, and protocol_error latches. A correct
//     emitter never produces one, so the latch is evidence, not a feature.
module memory_banks #(
  parameter int N_BANKS = 2,
  parameter int FLIT_W = 64,
  parameter int BANK_LSB = 0,
  parameter int BANK_W = 1
) (
  input  logic clk,
  input  logic rst_n,

  input  logic [FLIT_W-1:0] req_flit,
  input  logic req_valid,
  output logic req_ready,

  output logic [FLIT_W-1:0] rsp_flit,
  output logic rsp_valid,
  input  logic rsp_ready,

  output logic [FLIT_W-1:0] bank_req_flit,
  output logic bank_req_valid [0:N_BANKS-1],
  input  logic bank_req_ready [0:N_BANKS-1],

  input  logic [FLIT_W-1:0] bank_rsp_flit [0:N_BANKS-1],
  input  logic bank_rsp_valid [0:N_BANKS-1],
  output logic bank_rsp_ready [0:N_BANKS-1],

  output logic protocol_error
);

  localparam int IDX_W = (N_BANKS > 1) ? $clog2(N_BANKS) : 1;

  logic [BANK_W-1:0] sel_w;
  logic sel_ok_w;
  assign sel_w = req_flit[BANK_LSB +: BANK_W];
  assign sel_ok_w = (int'(sel_w) < N_BANKS);
  assign bank_req_flit = req_flit;

  always_comb begin
    req_ready = !sel_ok_w;
    for (int k = 0; k < N_BANKS; k++) begin
      bank_req_valid[k] = req_valid && sel_ok_w && (int'(sel_w) == k);
      if (sel_ok_w && (int'(sel_w) == k)) req_ready = bank_req_ready[k];
    end
  end

  logic lock_q;
  logic [IDX_W-1:0] grant_q;
  logic [IDX_W-1:0] rr_q;
  logic found_w;
  logic [IDX_W-1:0] pick_w;
  logic err_q;

  always_comb begin
    found_w = 1'b0;
    pick_w = '0;
    for (int i = 0; i < N_BANKS; i++) begin
      if (!found_w && bank_rsp_valid[(int'(rr_q) + i) % N_BANKS]) begin
        found_w = 1'b1;
        pick_w = IDX_W'((int'(rr_q) + i) % N_BANKS);
      end
    end
    if (lock_q) pick_w = grant_q;
  end

  always_comb begin
    rsp_flit = '0;
    rsp_valid = 1'b0;
    for (int k = 0; k < N_BANKS; k++) begin
      bank_rsp_ready[k] = 1'b0;
      if (int'(pick_w) == k) begin
        rsp_flit = bank_rsp_flit[k];
        rsp_valid = bank_rsp_valid[k] && (lock_q || found_w);
        bank_rsp_ready[k] = rsp_ready && bank_rsp_valid[k] && (lock_q || found_w);
      end
    end
  end

  assign protocol_error = err_q;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      lock_q <= 1'b0;
      grant_q <= '0;
      rr_q <= '0;
      err_q <= 1'b0;
    end else begin
      if (req_valid && req_ready && !sel_ok_w) err_q <= 1'b1;
      if (rsp_valid && rsp_ready) begin
        lock_q <= 1'b0;
        rr_q <= (int'(pick_w) == N_BANKS - 1) ? '0 : pick_w + 1'b1;
      end else if (rsp_valid) begin
        lock_q <= 1'b1;
        grant_q <= pick_w;
      end else if (lock_q) begin
        // The locked bank dropped its response without a handshake.
        lock_q <= 1'b0;
        err_q <= 1'b1;
      end
    end
  end

endmodule

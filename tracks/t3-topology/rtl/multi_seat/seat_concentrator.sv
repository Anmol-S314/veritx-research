`default_nettype none

// Multi-seat concentrator for the composed family path.
//
// N initiator seats share ONE router local port. Each seat presents a beat;
// this module arbitrates them onto the shared wire and routes the fabric's
// response back to the seat that owns it.
//
// Contract (deliberately narrow, because the composed fabric returns one
// response per beat and carries no seat tag):
//   * at most ONE beat is outstanding across the whole concentrator, so a
//     response is attributable to exactly one seat without a tag;
//   * a multi-flit packet keeps the wire (HEAD..BODY..TAIL are not
//     interleaved with another seat's beats);
//   * arbitration between seats is strict round-robin (starvation bound
//     N_SEATS-1, service skew <= 1 when every seat is backlogged);
//   * a beat that is not the head of a packet may not start a transfer.
//
// Throughput note (honest): the wire carries one beat per fabric round trip.
// The current slice already issues one beat at a time and waits for its
// response, so this does not slow an individual seat; it does serialise
// several seats that could otherwise have beats in flight together.
module seat_concentrator #(
  parameter int N_SEATS = 2,
  parameter int FLIT_W = 64,
  parameter int TYPE_W = 2,
  parameter int TYPE_LSB = 61,
  parameter int SEAT_W = 2,
  parameter int SEQ_W = 13
) (
  input  logic clk,
  input  logic rst_n,

  input  logic [FLIT_W-1:0] in_flit [0:N_SEATS-1],
  input  logic in_valid [0:N_SEATS-1],
  output logic in_ready [0:N_SEATS-1],

  output logic [FLIT_W-1:0] out_flit,
  output logic out_valid,
  input  logic out_ready,

  input  logic [FLIT_W-1:0] rsp_flit,
  input  logic rsp_valid,
  output logic rsp_ready,

  output logic [FLIT_W-1:0] seat_rsp_flit [0:N_SEATS-1],
  output logic seat_rsp_valid [0:N_SEATS-1],
  input  logic seat_rsp_ready [0:N_SEATS-1],

  output logic [SEAT_W-1:0] grant_seat,
  output logic protocol_error
);

  localparam logic [TYPE_W-1:0] FT_HEAD = 2'd0;
  localparam logic [TYPE_W-1:0] FT_BODY = 2'd1;
  localparam logic [TYPE_W-1:0] FT_TAIL = 2'd2;
  localparam logic [TYPE_W-1:0] FT_SINGLE = 2'd3;

  function automatic logic [TYPE_W-1:0] get_type(input logic [FLIT_W-1:0] f);
    return f[TYPE_LSB +: TYPE_W];
  endfunction

  function automatic logic is_head(input logic [FLIT_W-1:0] f);
    return (get_type(f) == FT_HEAD) || (get_type(f) == FT_SINGLE);
  endfunction

  function automatic logic is_tail(input logic [FLIT_W-1:0] f);
    return (get_type(f) == FT_TAIL) || (get_type(f) == FT_SINGLE);
  endfunction

  typedef enum logic [1:0] {S_IDLE, S_SEND, S_WAIT_RSP, S_DONE} state_e;
  state_e state_q;

  logic [SEAT_W-1:0] owner_q;
  logic             lock_q;
  logic [SEAT_W-1:0] rr_q;
  logic [SEQ_W-1:0] issued_q;

  integer seat;
  integer scanned;
  logic   picked;
  logic [SEAT_W-1:0] pick_seat;

  always_comb begin
    for (seat = 0; seat < N_SEATS; seat = seat + 1) begin
      in_ready[seat] = 1'b0;
      seat_rsp_flit[seat] = '0;
      seat_rsp_valid[seat] = 1'b0;
    end
    out_flit = '0;
    out_valid = 1'b0;
    rsp_ready = 1'b0;
    grant_seat = '0;
    protocol_error = 1'b0;
    picked = 1'b0;
    pick_seat = '0;
    if (state_q == S_SEND) begin
      out_flit = in_flit[owner_q];
      out_valid = in_valid[owner_q];
      in_ready[owner_q] = out_ready;
      grant_seat = owner_q;
    end else if (state_q == S_IDLE) begin
      scanned = 0;
      for (seat = 0; seat < N_SEATS; seat = seat + 1) begin
        if (!picked && scanned < N_SEATS) begin
          if (in_valid[(rr_q + seat) % N_SEATS] &&
              is_head(in_flit[(rr_q + seat) % N_SEATS])) begin
            picked = 1'b1;
            pick_seat = (rr_q + seat) % N_SEATS;
          end
          scanned = scanned + 1;
        end
      end
      if (picked) begin
        out_flit = in_flit[pick_seat];
        out_valid = 1'b1;
        in_ready[pick_seat] = out_ready;
        grant_seat = pick_seat;
      end
    end else if (state_q == S_WAIT_RSP) begin
      seat_rsp_flit[owner_q] = rsp_flit;
      seat_rsp_valid[owner_q] = rsp_valid;
      rsp_ready = seat_rsp_ready[owner_q];
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state_q <= S_IDLE;
      owner_q <= '0;
      lock_q <= 1'b0;
      rr_q <= '0;
      issued_q <= '0;
    end else begin
      case (state_q)
        S_IDLE: begin
          if (picked && out_ready) begin
            owner_q <= pick_seat;
            issued_q <= issued_q + 1'b1;
            if (!is_tail(in_flit[pick_seat])) lock_q <= 1'b1;
            state_q <= S_WAIT_RSP;
          end
        end
        S_SEND: begin
          if (out_valid && out_ready) begin
            issued_q <= issued_q + 1'b1;
            if (is_tail(in_flit[owner_q])) lock_q <= 1'b0;
            state_q <= S_WAIT_RSP;
          end
        end
        S_WAIT_RSP: begin
          if (rsp_valid && rsp_ready) begin
            if (lock_q) begin
              state_q <= S_SEND;
            end else begin
              rr_q <= (owner_q + 1) % N_SEATS;
              state_q <= S_IDLE;
            end
          end
        end
        default: begin
          state_q <= S_IDLE;
        end
      endcase
    end
  end

endmodule

`default_nettype wire

// addr_decode_formal.sv — decode-equivalence proof harness for the emitted
// address decoder.
//
// The reference model below is written from the COMPILED CONTRACT (the
// declared window and the declared per-initiator permissions), not from the
// RTL's internals. The properties therefore state what the decoder must do,
// and the proof shows the emitted RTL does exactly that for every input.
//
// Instance under proof: the slice profile — one window HBM0
// [0x1000, 0x2000), initiator 0 read/write, no other initiator permission.
// The decoder file is the one the product emits for that profile
// (`addr_decode.sv`, address_decode_hash recorded in its header).
`default_nettype none

module addr_decode_formal #(
  // The instance under proof: the slice profile (one compute initiator and
  // one HBM seat) has two attached endpoints and targets the HBM seat.
  parameter int N_ENDPOINTS = 2,
  parameter int TARGET_INDEX = 1
);

  localparam int ADDR_W = 64;
  localparam int REQ_ID_W = 1;
  localparam int BURST_W = 16;

  (* anyconst *) logic [ADDR_W-1:0] addr;
  (* anyconst *) logic [REQ_ID_W-1:0] req_id;
  (* anyconst *) logic req_write;
  (* anyconst *) logic [REQ_ID_W-1:0] wire_req_id;
  (* anyconst *) logic [BURST_W-1:0] burst_len;

  logic [N_ENDPOINTS-1:0] target_oh;
  logic hit;
  logic miss;
  logic overlap;
  logic allow;
  logic perm_violation;
  logic wire_identity_mismatch;
  logic timing_side_channel_declared;
  logic burst_violation;

  addr_decode dut (
    .addr(addr),
    .req_id(req_id),
    .req_write(req_write),
    .wire_req_id(wire_req_id),
    .burst_len(burst_len),
    .target_oh(target_oh),
    .hit(hit),
    .miss(miss),
    .overlap(overlap),
    .allow(allow),
    .perm_violation(perm_violation),
    .wire_identity_mismatch(wire_identity_mismatch),
    .timing_side_channel_declared(timing_side_channel_declared),
    .burst_violation(burst_violation)
  );

  // Reference model, straight from the compiled contract.
  localparam logic [63:0] BASE = 64'h0000000000001000;
  localparam logic [63:0] LAST = 64'h0000000000001fff;

  wire [63:0] addr64 = addr;
  // The contract's burst length is a byte count: the last covered byte is
  // addr + (burst_len - 1), and a single-beat burst covers one byte.
  wire [63:0] burst_end = addr64 + ((burst_len == 0) ? 64'd0 : (64'(burst_len) - 64'd1));

  wire spec_hit = (addr64 >= BASE) && (addr64 <= LAST);
  wire spec_burst_ok = spec_hit
      && ((burst_len == 0) || ((burst_end >= addr64) && (burst_end <= LAST)));
  wire spec_perm_ok = (req_id == 1'd0);
  wire spec_allow = spec_hit && spec_perm_ok && spec_burst_ok;

  always @(*) begin
    // Window membership.
    assert (hit == spec_hit);
    assert (miss == !spec_hit);
    // One declared window, so two windows can never overlap.
    assert (overlap == 1'b0);
    // Permission + burst containment decide the allow.
    assert (allow == spec_allow);
    assert (perm_violation == (spec_hit && !spec_allow));
    assert (burst_violation == (spec_hit && !spec_burst_ok));
    // A denied request selects no endpoint; an allowed one selects the
    // declared target (endpoint 2 = the HBM seat).
    assert (target_oh == (spec_allow ? (3'(1) << TARGET_INDEX) : 3'b000));
    // Trusted ingress: the wire-side identity must equal the port-tied one.
    assert (wire_identity_mismatch == (wire_req_id != req_id));
  end

endmodule

`default_nettype wire

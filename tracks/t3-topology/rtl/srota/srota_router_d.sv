// srota_router_d.sv — lintable structural Plane-D router slice.
//
// This is not a complete Srota router. It uses the package's preview header
// offsets and explicit VC-R5 port map; both remain open contracts. Each input
// holds one flit and its combinationally resolved one-hot route. Generic
// allocator metadata is tied to zero because those fields are not present in
// the preview header contract. The side buffer is instantiated through the
// credit manager but loser capture/reinjection is disabled: the current
// side-buffer interface has one write port and no defined multi-loser policy.
// There is no packet/VC state, multicast handling, MECS fanout, or proof of
// full Srota compliance in this integration slice.
`default_nettype none

module srota_router_d #(
  parameter int K = 2,
  parameter int C = 2,
  parameter int P = srota_route_pkg::srota_p(C),
  parameter int W = 64,
  parameter int STAGING_DEPTH = 2,
  parameter int SB_DEPTH = 8,
  parameter int COORD_W = (K > 1) ? $clog2(K) : 1,
  parameter int TILE_W = (C > 1) ? $clog2(C) : 1,
  parameter int CREDIT_W = $clog2(STAGING_DEPTH + 1),
  parameter int PORT_W = (P > 1) ? $clog2(P) : 1,
  parameter int SB_OCC_W = $clog2(SB_DEPTH + 1)
) (
  input  logic                         clk,
  input  logic                         rst_n,
  input  logic [COORD_W-1:0]           cfg_my_x,
  input  logic [COORD_W-1:0]           cfg_my_y,
  input  logic [CREDIT_W-1:0]          cfg_max_credit,
  input  logic [P-1:0]                 credit_ret,
  input  logic [P-1:0]                 in_valid,
  output logic [P-1:0]                 in_ready,
  input  logic [P-1:0][W-1:0]          in_flit,
  output logic [P-1:0]                 out_valid,
  input  logic [P-1:0]                 out_ready,
  output logic [P-1:0][W-1:0]          out_flit
);
  import srota_route_pkg::*;

  logic [P-1:0] input_valid_q;
  logic [P-1:0][W-1:0] input_flit_q;
  logic [P-1:0][W-1:0] ingress_flit;
  logic [P-1:0] valiant_transition;
  logic [P-1:0][P-1:0] route_q;
  logic [P-1:0][P-1:0] route_d;
  logic [P-1:0] route_valid;
  logic [P-1:0] route_eject;
  logic [P-1:0] route_turn;

  logic [P-1:0][P-1:0] req_by_output;
  logic [P-1:0][P-1:0][1:0] req_slack;
  logic [P-1:0][P-1:0][3:0] req_batch;
  logic [P-1:0][P-1:0][3:0] req_golden_id;
  logic [P-1:0][P-1:0] gnt_by_output;
  logic [P-1:0] gnt_valid;
  logic [P-1:0] gnt_accept;
  logic [P-1:0][P-1:0] busy_unused;
  logic [P-1:0] credit_avail;
  logic [P-1:0] consume_input;
  logic [P-1:0][CREDIT_W-1:0] credit_count_unused;

  logic [W-1:0] sb_rd_flit_unused;
  logic [PORT_W-1:0] sb_rd_port_unused;
  logic sb_rd_vld_unused;
  logic [SB_OCC_W-1:0] sb_occ_unused;
  logic [P-1:0] sidebuf_pending_unused;
  logic [1:0] sb_state_unused;

  // Header fields use the package's PREVIEW offsets, with coordinate fields
  // narrowed to the configured mesh coordinate width.
  for (genvar i = 0; i < P; i++) begin : g_route
    always_comb begin
      ingress_flit[i] = in_flit[i];
      valiant_transition[i] =
        (in_flit[i][SROTA_HDR_PATH_SHAPE_LSB +: 2] == SROTA_VALIANT_L1) &&
        (cfg_my_x == in_flit[i][SROTA_HDR_VALIANT_X_LSB +: COORD_W]) &&
        (cfg_my_y == in_flit[i][SROTA_HDR_VALIANT_Y_LSB +: COORD_W]);
      if (valiant_transition[i])
        ingress_flit[i][SROTA_HDR_PATH_SHAPE_LSB +: 2] = SROTA_ROW_FIRST;

      // The only routing-header rewrite is guarded by the cached intermediate.
      assert (!((ingress_flit[i][SROTA_HDR_PATH_SHAPE_LSB +: 2] !=
                 in_flit[i][SROTA_HDR_PATH_SHAPE_LSB +: 2]) &&
                !valiant_transition[i]))
        else $error("Valiant shape rewrite outside cached intermediate");
    end

    srota_route_compute #(
      .K (K),
      .C (C),
      .P (P),
      .W (COORD_W)
    ) u_route_compute (
      .hdr_dest_x      (ingress_flit[i][SROTA_HDR_DEST_X_LSB +: COORD_W]),
      .hdr_dest_y      (ingress_flit[i][SROTA_HDR_DEST_Y_LSB +: COORD_W]),
      .hdr_dest_tile   (ingress_flit[i][SROTA_HDR_DEST_TILE_LSB +: TILE_W]),
      .hdr_path_shape  (srota_path_shape_e'(ingress_flit[i][SROTA_HDR_PATH_SHAPE_LSB +: 2])),
      .hdr_valiant_x   (ingress_flit[i][SROTA_HDR_VALIANT_X_LSB +: COORD_W]),
      .hdr_valiant_y   (ingress_flit[i][SROTA_HDR_VALIANT_Y_LSB +: COORD_W]),
      .cfg_my_x        (cfg_my_x),
      .cfg_my_y        (cfg_my_y),
      .rc_port_oh      (route_d[i]),
      .rc_is_eject     (route_eject[i]),
      .rc_turn_taken   (route_turn[i]),
      .rc_valid        (route_valid[i])
    );
  end

  // One generic allocator per output. The only eligible input metadata
  // available here is the resolved output request; neutral metadata makes
  // the allocator's round-robin tiebreak the effective policy.
  always_comb begin
    req_by_output = '0;
    req_slack = '0;
    req_batch = '0;
    req_golden_id = '0;
    for (int o = 0; o < P; o++) begin
      for (int i = 0; i < P; i++)
        req_by_output[o][i] = input_valid_q[i] & route_q[i][o];
    end
  end

  for (genvar o = 0; o < P; o++) begin : g_output_arb
    srota_arb #(.N(P)) u_arb (
      .clk             (clk),
      .rst_n           (rst_n),
      .req_vec         (req_by_output[o]),
      .req_slack       (req_slack[o]),
      .req_batch       (req_batch[o]),
      .req_golden_id   (req_golden_id[o]),
      .credit_avail    ({P{credit_avail[o]}}),
      .out_busy_mask   ('0),
      .prec_first      (1'b0),
      .cfg_golden_id   ('0),
      .gnt_ready       (out_ready[o]),
      .out_busy_out    (busy_unused[o]),
      .gnt_oh          (gnt_by_output[o]),
      .gnt_vld         (gnt_valid[o]),
      .rr_ptr          ()
    );
  end

  // Crossbar is a one-hot OR of the winning registered input flits.
  always_comb begin
    out_valid = gnt_valid;
    out_flit = '0;
    gnt_accept = gnt_valid & out_ready;
    consume_input = '0;
    for (int o = 0; o < P; o++) begin
      for (int i = 0; i < P; i++) begin
        if (gnt_by_output[o][i])
          out_flit[o] |= input_flit_q[i];
        if (gnt_accept[o] && gnt_by_output[o][i]) begin
          consume_input[i] = 1'b1;
        end
      end
    end
    in_ready = ~input_valid_q | consume_input;
  end

  // Input flit and target are captured together only on an ingress handshake.
  // A departing entry may be replaced in the same cycle.
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      input_valid_q <= '0;
      input_flit_q <= '0;
      route_q <= '0;
    end else begin
      for (int i = 0; i < P; i++) begin
        if (in_valid[i] & in_ready[i]) begin
          input_valid_q[i] <= route_valid[i];
          input_flit_q[i] <= ingress_flit[i];
          route_q[i] <= route_d[i];
        end else if (consume_input[i]) begin
          input_valid_q[i] <= 1'b0;
        end
      end
    end
  end

  // Plane-D credits gate each output allocator. Side-buffer ports are safely
  // quiescent until a multi-loser capture/reinjection contract is specified.
  /* verilator lint_off PINCONNECTEMPTY */
  srota_credit_mgr #(
    .P             (P),
    .STAGING_DEPTH (STAGING_DEPTH),
    .SB_DEPTH      (SB_DEPTH),
    .W             (W)
  ) u_credit_mgr (
    .clk             (clk),
    .rst_n           (rst_n),
    .credit_ret      (credit_ret),
    .gnt_oh          (gnt_accept),
    .cfg_max_credit  (cfg_max_credit),
    .credit_avail    (credit_avail),
    .credit_cnt_dbg  (credit_count_unused),
    .alloc_loss      ('0),
    .sb_wr_flit      ('0),
    .sb_wr_port      ('0),
    .sb_wr_ready     (),
    .sb_wr_accept    (),
    .sb_full         (),
    .sb_rd_flit      (sb_rd_flit_unused),
    .sb_rd_port      (sb_rd_port_unused),
    .sb_rd_vld       (sb_rd_vld_unused),
    .sb_rd_gnt       (1'b0),
    .sb_occ          (sb_occ_unused),
    .sidebuf_pending (sidebuf_pending_unused),
    .sb_state        (sb_state_unused)
  );
  /* verilator lint_on PINCONNECTEMPTY */

endmodule

`default_nettype wire

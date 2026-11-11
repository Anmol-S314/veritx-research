// srota_fiu_pathsel.sv — FIU injection-time path-shape FSM + flow-epoch cache.
// ROUTE-001 rev 0.3 §10, §5.1, §5.4. The only adaptive state in the scheme.
// cfg_* and tel_* are quasi-static relative to clk_d (§12.2); the parent owns
// their synchronization and the epoch-boundary atomicity rule (§12.4).
`default_nettype none

module srota_fiu_pathsel #(
  // IDX_W = $clog2(CACHE_ENTRIES); CACHE_ENTRIES is a power of two.
  parameter int CACHE_ENTRIES = 16,
  parameter int IDX_W = (CACHE_ENTRIES > 1) ? $clog2(CACHE_ENTRIES) : 1,
  parameter int EPOCH_W = 16,
  parameter int K_W = 4
) (
  input  logic                          clk,
  input  logic                          rst_n,
  input  logic                          pkt_valid,
  input  logic [K_W-1:0]                dest_x,
  input  logic [K_W-1:0]                dest_y,
  input  logic [IDX_W-1:0]              flow_hash,
  input  logic [EPOCH_W-1:0]            epoch_ctr,
  input  logic                          tel_vld,
  input  logic [(1 << K_W)-1:0][3:0]    tel_col_vec,
  input  logic [(1 << K_W)-1:0][3:0]    tel_row_vec,
  input  logic [2:0]                    cfg_path_en,
  input  logic [3:0]                    cfg_cong_thresh,
  // Reserved for Plane-T-weighted selection (§14.1); v1 uses uniform LFSR
  // selection in both modes, so this input is intentionally unused.
  /* verilator lint_off UNUSEDSIGNAL */
  input  logic                          cfg_valiant_mode,
  /* verilator lint_on UNUSEDSIGNAL */
  input  logic                          credit_avail,
  input  logic                          inj_done,
  output logic [1:0]                    sel_shape,
  output logic [K_W-1:0]                sel_valiant_x,
  output logic [K_W-1:0]                sel_valiant_y,
  output logic [2:0]                    state_dbg
);
  import srota_route_pkg::*;

  localparam int LFSR_W = 16;

  srota_fiu_state_e state, state_n;

  // Flow-epoch cache. Validity is lazy: compare the stored tag against the
  // current epoch counter, never flush the array (§10.3).
  logic [CACHE_ENTRIES-1:0]                cache_vld;
  logic [CACHE_ENTRIES-1:0][1:0]           cache_shape;
  logic [CACHE_ENTRIES-1:0][K_W-1:0]       cache_valiant_x;
  logic [CACHE_ENTRIES-1:0][K_W-1:0]       cache_valiant_y;
  logic [CACHE_ENTRIES-1:0][EPOCH_W-1:0]   cache_epoch_tag;

  // Packet context captured at IDLE, so the multi-cycle decision is stable.
  logic [IDX_W-1:0] idx_q;
  logic [K_W-1:0]   dest_x_q, dest_y_q;

  // Plane-T loads captured at TEL_RD, then applied in SELECT (§10.1).
  logic [3:0] col_load_q, row_load_q;

  // Chosen path held through INJECT. Never re-randomised on stall (§10.2).
  srota_path_shape_e sel_shape_q;
  logic [K_W-1:0]    sel_valiant_x_q, sel_valiant_y_q;

  // Combinational SELECT result.
  srota_path_shape_e sel_shape_c;
  logic [K_W-1:0]    sel_valiant_x_c, sel_valiant_y_c;

  logic [LFSR_W-1:0] lfsr_q;
  logic              row_cong, col_cong;
  logic              epoch_valid;

  assign epoch_valid = cache_vld[idx_q] &&
                       (cache_epoch_tag[idx_q] == epoch_ctr);

  // Candidate column/row drop-point occupancy (§5.1).
  assign row_cong = (col_load_q >= cfg_cong_thresh);
  assign col_cong = (row_load_q >= cfg_cong_thresh);

  // §5.1 selection. Row-first is the default; column-first is the fallback
  // when the row-first drop point is congested; Valiant is the last resort.
  // cfg_path_en gates each shape (§14.1). All-zero is illegal (§14.3) but
  // resolves deterministically to row-first.
  always_comb begin
    sel_shape_c = SROTA_ROW_FIRST;

    if (cfg_path_en[0] && !row_cong) begin
      sel_shape_c = SROTA_ROW_FIRST;
    end else if (cfg_path_en[1] && !col_cong) begin
      sel_shape_c = SROTA_COLUMN_FIRST;
    end else if (cfg_path_en[2]) begin
      sel_shape_c = SROTA_VALIANT_L1;
    end else if (cfg_path_en[0]) begin
      sel_shape_c = SROTA_ROW_FIRST;
    end else if (cfg_path_en[1]) begin
      sel_shape_c = SROTA_COLUMN_FIRST;
    end
  end

  // Uniform intermediate from a 16-bit maximal LFSR
  // (x^16 + x^14 + x^13 + x^11 + 1). Sampled once at SELECT and cached, so
  // every packet in the flow-epoch takes the same path (§5.4, RT-R8).
  // cfg_valiant_mode=1 is reserved for Plane-T-weighted selection (§14.1);
  // v1 keeps uniform selection in both modes.
  always_comb begin
    sel_valiant_x_c = lfsr_q[K_W-1:0];
    sel_valiant_y_c = lfsr_q[2*K_W-1:K_W];
  end

  // State transitions (§10.1). TEL_RD and INJECT are the two stall states.
  always_comb begin
    state_n = state;

    case (state)
      SROTA_FSM_IDLE: begin
        if (pkt_valid)
          state_n = SROTA_FSM_LOOKUP;
      end

      SROTA_FSM_LOOKUP: begin
        if (epoch_valid)
          state_n = SROTA_FSM_CACHED;
        else
          state_n = SROTA_FSM_TEL_RD;
      end

      SROTA_FSM_TEL_RD: begin
        if (tel_vld)
          state_n = SROTA_FSM_SELECT;
      end

      SROTA_FSM_SELECT: begin
        // shape_locked is a single cycle (§10.1).
        state_n = SROTA_FSM_INJECT;
      end

      SROTA_FSM_CACHED: begin
        // A hit was taken in LOOKUP; this is a safety re-check.
        if (epoch_valid)
          state_n = SROTA_FSM_INJECT;
        else
          state_n = SROTA_FSM_LOOKUP;
      end

      SROTA_FSM_INJECT: begin
        // Hold with the chosen shape latched while credit is unavailable.
        if (credit_avail && inj_done)
          state_n = SROTA_FSM_IDLE;
      end

      default: begin
        state_n = SROTA_FSM_IDLE;
      end
    endcase
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      state            <= SROTA_FSM_IDLE;
      cache_vld        <= '0;
      cache_shape      <= '0;
      cache_valiant_x  <= '0;
      cache_valiant_y  <= '0;
      cache_epoch_tag  <= '0;
      idx_q            <= '0;
      dest_x_q         <= '0;
      dest_y_q         <= '0;
      col_load_q       <= '0;
      row_load_q       <= '0;
      sel_shape_q      <= SROTA_ROW_FIRST;
      sel_valiant_x_q  <= '0;
      sel_valiant_y_q  <= '0;
      lfsr_q           <= 16'hACE1;
    end else begin
      state <= state_n;

      if ((state == SROTA_FSM_IDLE) && pkt_valid) begin
        idx_q    <= flow_hash;
        dest_x_q <= dest_x;
        dest_y_q <= dest_y;
      end

      if ((state == SROTA_FSM_TEL_RD) && tel_vld) begin
        col_load_q <= tel_col_vec[dest_x_q];
        row_load_q <= tel_row_vec[dest_y_q];
      end

      // SELECT writes the shape and the intermediate together (§10.4, RT-R8).
      if (state == SROTA_FSM_SELECT) begin
        cache_vld[idx_q]       <= 1'b1;
        cache_shape[idx_q]     <= sel_shape_c;
        cache_epoch_tag[idx_q] <= epoch_ctr;
        cache_valiant_x[idx_q] <= sel_valiant_x_c;
        cache_valiant_y[idx_q] <= sel_valiant_y_c;

        sel_shape_q     <= sel_shape_c;
        sel_valiant_x_q <= sel_valiant_x_c;
        sel_valiant_y_q <= sel_valiant_y_c;
      end

      // CACHED reuses the cached shape and intermediate (§10.1).
      if ((state == SROTA_FSM_CACHED) && epoch_valid) begin
        sel_shape_q     <= srota_path_shape_e'(cache_shape[idx_q]);
        sel_valiant_x_q <= cache_valiant_x[idx_q];
        sel_valiant_y_q <= cache_valiant_y[idx_q];
      end

      // Advance only on a new Valiant SELECT; INJECT stalls never re-randomise.
      if ((state == SROTA_FSM_SELECT) &&
          (sel_shape_c == SROTA_VALIANT_L1)) begin
        lfsr_q <= {lfsr_q[14:0],
                   lfsr_q[15] ^ lfsr_q[13] ^ lfsr_q[12] ^ lfsr_q[10]};
      end
    end
  end

  assign state_dbg      = state;
  assign sel_shape      = sel_shape_q;
  assign sel_valiant_x  = sel_valiant_x_q;
  assign sel_valiant_y  = sel_valiant_y_q;

endmodule

`default_nettype wire

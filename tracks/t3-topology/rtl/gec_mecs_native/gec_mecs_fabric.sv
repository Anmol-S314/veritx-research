// Connected unicast GEC-MECS fabric for the pinned gec_mecs16 instance.
// 4x4 routers, c=1, o=1, d=3, three tap-partitioned virtual channels.
// Each row/column output is one shared transmitter with three passive taps.
`timescale 1ns/1ps
`default_nettype none

module gec_mecs_router #(
  parameter int ID = 0,
  parameter int K = 4,
  parameter int W = 64,
  parameter int DEST_W = 4,
  parameter int PORTS = 7
) (
  input  logic                   clk,
  input  logic                   rst_n,
  input  logic [PORTS-1:0]       in_valid,
  output logic [PORTS-1:0]       in_ready,
  input  logic [PORTS-1:0][W-1:0] in_flit,
  output logic                   local_valid,
  input  logic                   local_ready,
  output logic [W-1:0]           local_flit,
  output logic                   row_valid,
  input  logic                   row_ready,
  output logic [W-1:0]           row_flit,
  output logic [DEST_W-1:0]      row_dest,
  output logic [1:0]             row_vc,
  output logic                   col_valid,
  input  logic                   col_ready,
  output logic [W-1:0]           col_flit,
  output logic [DEST_W-1:0]      col_dest,
  output logic [1:0]             col_vc
);
  localparam int K_W = $clog2(K);
  localparam int DEST_LSB = W - DEST_W;

  logic [PORTS-1:0] valid_q;
  logic [PORTS-1:0][W-1:0] flit_q;
  logic [PORTS-1:0] pop;
  int rr_local, rr_row, rr_col;
  int grant_local, grant_row, grant_col;
  logic found_local, found_row, found_col;
  logic [DEST_W-1:0] candidate_dest;
  logic [K_W-1:0] dest_x, dest_y;
  logic [K_W-1:0] my_x, my_y;
  logic [1:0] drop_idx;
  int scan_idx;

  assign my_x = K_W'(ID % K);
  assign my_y = K_W'(ID / K);

  always_comb begin
    grant_local = '0;
    grant_row = '0;
    grant_col = '0;
    found_local = 1'b0;
    found_row = 1'b0;
    found_col = 1'b0;
    candidate_dest = '0;
    dest_x = '0;
    dest_y = '0;
    drop_idx = '0;
    scan_idx = '0;
    local_valid = 1'b0;
    row_valid = 1'b0;
    col_valid = 1'b0;
    local_flit = '0;
    row_flit = '0;
    col_flit = '0;
    row_dest = '0;
    col_dest = '0;
    row_vc = '0;
    col_vc = '0;

    // Independent round-robin arbiters for local ejection, row wire, column wire.
    for (int offset = 0; offset < PORTS; offset++) begin
      scan_idx = (rr_local + offset) % PORTS;
      candidate_dest = flit_q[scan_idx][DEST_LSB +: DEST_W];
      if (!found_local && valid_q[scan_idx] && candidate_dest == DEST_W'(ID)) begin
        found_local = 1'b1;
        grant_local = scan_idx;
      end

      scan_idx = (rr_row + offset) % PORTS;
      candidate_dest = flit_q[scan_idx][DEST_LSB +: DEST_W];
      dest_x = K_W'(candidate_dest % K);
      if (!found_row && valid_q[scan_idx] && int'(candidate_dest) < K*K && dest_x != my_x) begin
        found_row = 1'b1;
        grant_row = scan_idx;
      end

      scan_idx = (rr_col + offset) % PORTS;
      candidate_dest = flit_q[scan_idx][DEST_LSB +: DEST_W];
      dest_x = K_W'(candidate_dest % K);
      dest_y = K_W'(candidate_dest / K);
      if (!found_col && valid_q[scan_idx] && int'(candidate_dest) < K*K &&
          dest_x == my_x && dest_y != my_y) begin
        found_col = 1'b1;
        grant_col = scan_idx;
      end
    end

    if (found_local) begin
      local_valid = 1'b1;
      local_flit = flit_q[grant_local];
    end

    if (found_row) begin
      row_valid = 1'b1;
      row_flit = flit_q[grant_row];
      row_dest = flit_q[grant_row][DEST_LSB +: DEST_W];
      dest_x = K_W'(row_dest % K);
      // _PeerIndex order is ascending peer coordinate with self skipped.
      drop_idx = 2'((int'(dest_x) < int'(my_x)) ? int'(dest_x) : int'(dest_x) - 1);
      row_vc = 2'(drop_idx); // gec_mecs16 has num_vcs=d=3, one VC per tap.
    end

    if (found_col) begin
      col_valid = 1'b1;
      col_flit = flit_q[grant_col];
      col_dest = flit_q[grant_col][DEST_LSB +: DEST_W];
      dest_y = K_W'(col_dest / K);
      drop_idx = 2'((int'(dest_y) < int'(my_y)) ? int'(dest_y) : int'(dest_y) - 1);
      col_vc = 2'(drop_idx);
    end
  end

  always_comb begin
    pop = '0;
    if (found_local && local_ready) pop[grant_local] = 1'b1;
    if (found_row && row_ready) pop[grant_row] = 1'b1;
    if (found_col && col_ready) pop[grant_col] = 1'b1;
  end

  assign in_ready = ~valid_q;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      valid_q <= '0;
      rr_local <= '0;
      rr_row <= '0;
      rr_col <= '0;
    end else begin
      for (int p = 0; p < PORTS; p++) begin
        if (in_valid[p] && in_ready[p]) begin
          valid_q[p] <= 1'b1;
          flit_q[p] <= in_flit[p];
        end else if (pop[p]) begin
          valid_q[p] <= 1'b0;
        end
      end
      if (found_local && local_ready) rr_local <= (grant_local + 1) % PORTS;
      if (found_row && row_ready) rr_row <= (grant_row + 1) % PORTS;
      if (found_col && col_ready) rr_col <= (grant_col + 1) % PORTS;
    end
  end

  initial begin
    if (K != 4 || ID >= K*K || PORTS != 1 + 2*(K-1) || DEST_W != 4)
      $fatal(1, "gec_mecs16 router parameter contract violated");
  end
endmodule

module gec_mecs16_fabric #(
  parameter int K = 4,
  parameter int W = 64,
  parameter int N = K*K,
  parameter int PORTS = 1 + 2*(K-1),
  parameter int DEST_W = 4
) (
  input  logic                    clk,
  input  logic                    rst_n,
  input  logic [N-1:0]            ep_in_valid,
  output logic [N-1:0]            ep_in_ready,
  input  logic [N-1:0][W-1:0]     ep_in_flit,
  output logic [N-1:0]            ep_out_valid,
  input  logic [N-1:0]            ep_out_ready,
  output logic [N-1:0][W-1:0]     ep_out_flit
);
  logic [N-1:0][PORTS-1:0] node_in_valid, node_in_ready;
  logic [N-1:0][PORTS-1:0][W-1:0] node_in_flit;
  logic [N-1:0] local_valid, row_valid, row_ready, col_valid, col_ready;
  logic [N-1:0][W-1:0] local_flit, row_flit, col_flit;
  logic [N-1:0][DEST_W-1:0] row_dest, col_dest;
  logic [N-1:0][1:0] row_vc, col_vc;

  function automatic int row_tap(input int src, input int dst);
    return (src % K < dst % K) ? src % K : src % K - 1;
  endfunction

  function automatic int col_tap(input int src, input int dst);
    return (src / K < dst / K) ? src / K : src / K - 1;
  endfunction

  always_comb begin
    node_in_valid = '0;
    node_in_flit = '0;
    for (int n = 0; n < N; n++) begin
      node_in_valid[n][0] = ep_in_valid[n];
      node_in_flit[n][0] = ep_in_flit[n];
    end

    // Each row/column output is a single transmitter; its destination field
    // selects exactly one tap using BookSim's ascending-peer tap numbering.
    for (int src = 0; src < N; src++) begin
      for (int dst = 0; dst < N; dst++) begin
        if ((src / K) == (dst / K) && src != dst && int'(row_dest[src]) % K == dst % K) begin
          node_in_valid[dst][1 + row_tap(src, dst)] = row_valid[src];
          node_in_flit[dst][1 + row_tap(src, dst)] = row_flit[src];
        end
        if ((src % K) == (dst % K) && src != dst && int'(col_dest[src]) / K == dst / K) begin
          node_in_valid[dst][1 + (K-1) + col_tap(src, dst)] = col_valid[src];
          node_in_flit[dst][1 + (K-1) + col_tap(src, dst)] = col_flit[src];
        end
      end
    end
  end

  always_comb begin
    row_ready = '0;
    col_ready = '0;
    for (int src = 0; src < N; src++) begin
      for (int dst = 0; dst < N; dst++) begin
        if ((src / K) == (dst / K) && src != dst && int'(row_dest[src]) % K == dst % K)
          row_ready[src] = node_in_ready[dst][1 + row_tap(src, dst)];
        if ((src % K) == (dst % K) && src != dst && int'(col_dest[src]) / K == dst / K)
          col_ready[src] = node_in_ready[dst][1 + (K-1) + col_tap(src, dst)];
      end
    end
  end

  assign ep_out_valid = local_valid;
  assign ep_out_flit = local_flit;

  for (genvar n = 0; n < N; n++) begin : g_router
    assign ep_in_ready[n] = node_in_ready[n][0];
    gec_mecs_router #(.ID(n), .K(K), .W(W), .DEST_W(DEST_W), .PORTS(PORTS)) u_router (
      .clk(clk), .rst_n(rst_n),
      .in_valid(node_in_valid[n]), .in_ready(node_in_ready[n]), .in_flit(node_in_flit[n]),
      .local_valid(local_valid[n]), .local_ready(ep_out_ready[n]), .local_flit(local_flit[n]),
      .row_valid(row_valid[n]), .row_ready(row_ready[n]), .row_flit(row_flit[n]),
      .row_dest(row_dest[n]), .row_vc(row_vc[n]),
      .col_valid(col_valid[n]), .col_ready(col_ready[n]), .col_flit(col_flit[n]),
      .col_dest(col_dest[n]), .col_vc(col_vc[n])
    );
  end
endmodule
`default_nettype wire

// srota_top.sv — smoke top exposing the structural Plane-D slice.
//
// The port count is the package's explicit preview map (P = 2*C + 8), not a
// claim that VC-R5 has finalized the router port contract. See srota_router_d
// for integration assumptions and open items.
`default_nettype none

module srota_top #(
  parameter int K = 2,
  parameter int C = 2,
  parameter int P = srota_route_pkg::srota_p(C),
  parameter int W = 64,
  parameter int STAGING_DEPTH = 2,
  parameter int SB_DEPTH = 8,
  parameter int COORD_W = (K > 1) ? $clog2(K) : 1,
  parameter int CREDIT_W = $clog2(STAGING_DEPTH + 1)
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
  srota_router_d #(
    .K             (K),
    .C             (C),
    .P             (P),
    .W             (W),
    .STAGING_DEPTH (STAGING_DEPTH),
    .SB_DEPTH      (SB_DEPTH),
    .COORD_W       (COORD_W),
    .CREDIT_W      (CREDIT_W)
  ) u_router_d (
    .clk            (clk),
    .rst_n          (rst_n),
    .cfg_my_x       (cfg_my_x),
    .cfg_my_y       (cfg_my_y),
    .cfg_max_credit (cfg_max_credit),
    .credit_ret     (credit_ret),
    .in_valid       (in_valid),
    .in_ready       (in_ready),
    .in_flit        (in_flit),
    .out_valid      (out_valid),
    .out_ready      (out_ready),
    .out_flit       (out_flit)
  );
endmodule

`default_nettype wire

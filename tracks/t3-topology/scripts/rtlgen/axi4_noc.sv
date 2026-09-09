// axi4_noc.sv — AXI4 end-to-end NoC wrapper
// Connects two AXI4 masters through a configurable NoC.
// Each master gets an axi4_flit mapper + a router.
// Used for verifying AXI4 protocol over the NoC fabric.
`include "noc_pkg.sv"

module axi4_noc #(
  parameter int N_ROUTERS = 2,
  parameter int BUF_DEPTH = 8,
  parameter int NUM_VCS   = 2
) (
  input  logic clk,
  input  logic rst_n,

  // ── Node 0: AXI4 Master 0 ──
  input  logic [3:0]   m0_awid,
  input  logic [31:0]  m0_awaddr,
  input  logic [7:0]   m0_awlen,
  input  logic [2:0]   m0_awsize,
  input  logic [1:0]   m0_awburst,
  input  logic         m0_awvalid,
  output logic         m0_awready,

  input  logic [63:0]  m0_wdata,
  input  logic [7:0]   m0_wstrb,
  input  logic         m0_wlast,
  input  logic         m0_wvalid,
  output logic         m0_wready,

  output logic [3:0]   m0_bid,
  output logic [1:0]   m0_bresp,
  output logic         m0_bvalid,
  input  logic         m0_bready,

  input  logic [3:0]   m0_arid,
  input  logic [31:0]  m0_araddr,
  input  logic [7:0]   m0_arlen,
  input  logic [2:0]   m0_arsize,
  input  logic [1:0]   m0_arburst,
  input  logic         m0_arvalid,
  output logic         m0_arready,

  output logic [3:0]   m0_rid,
  output logic [63:0]  m0_rdata,
  output logic [1:0]   m0_rresp,
  output logic         m0_rlast,
  output logic         m0_rvalid,
  input  logic         m0_rready,

  // ── Node 1: AXI4 Master 1 ──
  input  logic [3:0]   m1_awid,
  input  logic [31:0]  m1_awaddr,
  input  logic [7:0]   m1_awlen,
  input  logic [2:0]   m1_awsize,
  input  logic [1:0]   m1_awburst,
  input  logic         m1_awvalid,
  output logic         m1_awready,

  input  logic [63:0]  m1_wdata,
  input  logic [7:0]   m1_wstrb,
  input  logic         m1_wlast,
  input  logic         m1_wvalid,
  output logic         m1_wready,

  output logic [3:0]   m1_bid,
  output logic [1:0]   m1_bresp,
  output logic         m1_bvalid,
  input  logic         m1_bready,

  input  logic [3:0]   m1_arid,
  input  logic [31:0]  m1_araddr,
  input  logic [7:0]   m1_arlen,
  input  logic [2:0]   m1_arsize,
  input  logic [1:0]   m1_arburst,
  input  logic         m1_arvalid,
  output logic         m1_arready,

  output logic [3:0]   m1_rid,
  output logic [63:0]  m1_rdata,
  output logic [1:0]   m1_rresp,
  output logic         m1_rlast,
  output logic         m1_rvalid,
  input  logic         m1_rready
);

  // ── NoC Wires ──
  // Router 0 → Router 1
  noc_pkg::flit_raw_t link_01_flit;
  logic               link_01_valid;
  logic               link_01_ready;
  // Router 1 → Router 0
  noc_pkg::flit_raw_t link_10_flit;
  logic               link_10_valid;
  logic               link_10_ready;

  // ── Node 0: AXI4 Flit Mapper ──
  noc_pkg::flit_raw_t n0_tx_flit, n0_rx_flit;
  logic               n0_tx_valid, n0_tx_ready;
  logic               n0_rx_valid, n0_rx_ready;

  axi4_flit #(
    .N_ROUTERS(N_ROUTERS),
    .MY_ID(4'd0)
  ) u_axi4_node0 (
    .clk(clk), .rst_n(rst_n),
    // AXI4 from master 0
    .s_axi_awid(m0_awid), .s_axi_awaddr(m0_awaddr),
    .s_axi_awlen(m0_awlen), .s_axi_awsize(m0_awsize),
    .s_axi_awburst(m0_awburst),
    .s_axi_awvalid(m0_awvalid), .s_axi_awready(m0_awready),
    .s_axi_wdata(m0_wdata), .s_axi_wstrb(m0_wstrb),
    .s_axi_wlast(m0_wlast),
    .s_axi_wvalid(m0_wvalid), .s_axi_wready(m0_wready),
    .s_axi_bid(m0_bid), .s_axi_bresp(m0_bresp),
    .s_axi_bvalid(m0_bvalid), .s_axi_bready(m0_bready),
    .s_axi_arid(m0_arid), .s_axi_araddr(m0_araddr),
    .s_axi_arlen(m0_arlen), .s_axi_arsize(m0_arsize),
    .s_axi_arburst(m0_arburst),
    .s_axi_arvalid(m0_arvalid), .s_axi_arready(m0_arready),
    .s_axi_rid(m0_rid), .s_axi_rdata(m0_rdata),
    .s_axi_rresp(m0_rresp), .s_axi_rlast(m0_rlast),
    .s_axi_rvalid(m0_rvalid), .s_axi_rready(m0_rready),
    // NoC TX/RX
    .noc_tx_flit(n0_tx_flit), .noc_tx_valid(n0_tx_valid),
    .noc_tx_ready(n0_tx_ready),
    .noc_rx_flit(n0_rx_flit), .noc_rx_valid(n0_rx_valid),
    .noc_rx_ready(n0_rx_ready),
    // Config
    .target_id(4'd1)
  );

  // ── Node 1: AXI4 Flit Mapper ──
  noc_pkg::flit_raw_t n1_tx_flit, n1_rx_flit;
  logic               n1_tx_valid, n1_tx_ready;
  logic               n1_rx_valid, n1_rx_ready;

  axi4_flit #(
    .N_ROUTERS(N_ROUTERS),
    .MY_ID(4'd1)
  ) u_axi4_node1 (
    .clk(clk), .rst_n(rst_n),
    // AXI4 from master 1
    .s_axi_awid(m1_awid), .s_axi_awaddr(m1_awaddr),
    .s_axi_awlen(m1_awlen), .s_axi_awsize(m1_awsize),
    .s_axi_awburst(m1_awburst),
    .s_axi_awvalid(m1_awvalid), .s_axi_awready(m1_awready),
    .s_axi_wdata(m1_wdata), .s_axi_wstrb(m1_wstrb),
    .s_axi_wlast(m1_wlast),
    .s_axi_wvalid(m1_wvalid), .s_axi_wready(m1_wready),
    .s_axi_bid(m1_bid), .s_axi_bresp(m1_bresp),
    .s_axi_bvalid(m1_bvalid), .s_axi_bready(m1_bready),
    .s_axi_arid(m1_arid), .s_axi_araddr(m1_araddr),
    .s_axi_arlen(m1_arlen), .s_axi_arsize(m1_arsize),
    .s_axi_arburst(m1_arburst),
    .s_axi_arvalid(m1_arvalid), .s_axi_arready(m1_arready),
    .s_axi_rid(m1_rid), .s_axi_rdata(m1_rdata),
    .s_axi_rresp(m1_rresp), .s_axi_rlast(m1_rlast),
    .s_axi_rvalid(m1_rvalid), .s_axi_rready(m1_rready),
    // NoC TX/RX
    .noc_tx_flit(n1_tx_flit), .noc_tx_valid(n1_tx_valid),
    .noc_tx_ready(n1_tx_ready),
    .noc_rx_flit(n1_rx_flit), .noc_rx_valid(n1_rx_valid),
    .noc_rx_ready(n1_rx_ready),
    // Config
    .target_id(4'd0)
  );

  // ── Router 0 (node 0) ──
  noc_pkg::flit_raw_t r0_n_in_flit, r0_n_out_flit;
  logic               r0_n_in_valid, r0_n_out_valid;
  logic               r0_n_in_ready, r0_n_out_ready;

  // Minimal route table: 0→1 via port0, 1→0 via port0
  router #(
    .ID(0), .DEG(1),
    // Pack: {dst1, dst0}. dst0→LOCAL(port1), dst1→port0(→r1)
    .RT_MIN({1'd0, 1'd1}),
    .RT_ESC({1'd0, 1'd1})
  ) u_router0 (
    .clk(clk), .rst_n(rst_n),
    // Network port 0 → router 1
    .n_in_flit({r0_n_in_flit}), .n_in_valid({r0_n_in_valid}),
    .n_in_ready({r0_n_in_ready}),
    .n_out_flit({r0_n_out_flit}), .n_out_valid({r0_n_out_valid}),
    .n_out_ready({r0_n_out_ready}),
    // Local: AXI4 flit mapper 0
    .local_in_flit(n0_tx_flit), .local_in_valid(n0_tx_valid),
    .local_in_ready(n0_tx_ready),
    .local_out_flit(n0_rx_flit), .local_out_valid(n0_rx_valid),
    .local_out_ready(n0_rx_ready)
  );

  // ── Router 1 (node 1) ──
  noc_pkg::flit_raw_t r1_n_in_flit, r1_n_out_flit;
  logic               r1_n_in_valid, r1_n_out_valid;
  logic               r1_n_in_ready, r1_n_out_ready;

  router #(
    .ID(1), .DEG(1),
    // Pack: {dst1, dst0}. dst0→port0(→r0), dst1→LOCAL(port1)
    .RT_MIN({1'd1, 1'd0}),
    .RT_ESC({1'd1, 1'd0})
  ) u_router1 (
    .clk(clk), .rst_n(rst_n),
    // Network port 0 → router 0
    .n_in_flit({r1_n_in_flit}), .n_in_valid({r1_n_in_valid}),
    .n_in_ready({r1_n_in_ready}),
    .n_out_flit({r1_n_out_flit}), .n_out_valid({r1_n_out_valid}),
    .n_out_ready({r1_n_out_ready}),
    // Local: AXI4 flit mapper 1
    .local_in_flit(n1_tx_flit), .local_in_valid(n1_tx_valid),
    .local_in_ready(n1_tx_ready),
    .local_out_flit(n1_rx_flit), .local_out_valid(n1_rx_valid),
    .local_out_ready(n1_rx_ready)
  );

  // ── Cross-connect network links ──
  // Router 0 port 0 → Router 1 port 0
  assign r1_n_in_flit   = r0_n_out_flit;
  assign r1_n_in_valid  = r0_n_out_valid;
  assign r0_n_out_ready = r1_n_in_ready;

  // Router 1 port 0 → Router 0 port 0
  assign r0_n_in_flit   = r1_n_out_flit;
  assign r0_n_in_valid  = r1_n_out_valid;
  assign r1_n_out_ready = r0_n_in_ready;

endmodule

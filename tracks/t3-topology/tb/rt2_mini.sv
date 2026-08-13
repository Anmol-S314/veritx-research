`timescale 1ns/1ps

// 2-router mini-TB: (0,0) -> channel -> (1,0), eject to "NIC" links.
// Inject a 1-flit packet at local of (0,0); watch it appear at (1,0) local.
// Pin down the +6 latency on the first-ever network hop.

module rt2_mini;
  import noc_pkg::*;
  localparam int VCS = 4;

  logic clk = 1'b0;
  always #5 clk = ~clk;
  logic rst_n = 1'b0;

  link_f_t flit_in [2][NUM_PORTS];
  link_c_t credit_in[2][NUM_PORTS];
  link_f_t flit_out[2][NUM_PORTS];
  link_c_t credit_out[2][NUM_PORTS];
  logic [31:0] tick [2];

  noc_router #(.VCS(VCS), .X(0), .Y(0), .X_DIM(4), .Y_DIM(4)) u_r0 (
    .clk(clk), .rst_n(rst_n),
    .flit_in(flit_in[0]), .credit_in(credit_in[0]),
    .flit_out(flit_out[0]), .credit_out(credit_out[0]),
    .tick(tick[0]), .recv_cnt(), .send_cnt(), .pop_cnt()
  );
  noc_router #(.VCS(VCS), .X(1), .Y(0), .X_DIM(4), .Y_DIM(4)) u_r1 (
    .clk(clk), .rst_n(rst_n),
    .flit_in(flit_in[1]), .credit_in(credit_in[1]),
    .flit_out(flit_out[1]), .credit_out(credit_out[1]),
    .tick(tick[1]), .recv_cnt(), .send_cnt(), .pop_cnt()
  );

  // channel (0,0) E -> (1,0) W (2-stage), flit + credit
  link_f_t ch_f[1:0];
  logic ch_cv;
  logic [2:0] ch_cvc;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      ch_f[0] <= '0; ch_f[1] <= '0;
      ch_cv <= 1'b0; ch_cvc <= '0;
    end else begin
      ch_f[0] <= flit_out[0][PORT_E];
      ch_f[1] <= ch_f[0];
      ch_cv <= credit_out[1][PORT_W].valid;
      ch_cvc <= credit_out[1][PORT_W].vc;
    end
  end
  always_comb begin
    flit_in[1][PORT_W] = ch_f[1];
    credit_in[0][PORT_E].valid = ch_cv;
    credit_in[0][PORT_E].vc    = ch_cvc;
  end

  initial begin
    for (int r = 0; r < 2; r++)
      for (int p = 0; p < NUM_PORTS; p++) begin
        flit_in[r][p].valid = 1'b0; flit_in[r][p].flit = '0;
        credit_in[r][p].valid = 1'b0; credit_in[r][p].vc = '0;
      end
    repeat (4) @(posedge clk);
    rst_n = 1'b1;
    repeat (6) @(posedge clk);

    $display("t=%0d inject flit dst=1 -> E of r0", tick[0]);
    flit_in[0][PORT_L].valid = 1'b1;
    flit_in[0][PORT_L].flit.head  = 1'b1;
    flit_in[0][PORT_L].flit.tail  = 1'b1;
    flit_in[0][PORT_L].flit.vc    = 3'd0;
    flit_in[0][PORT_L].flit.dst   = 8'd1;
    @(posedge clk);
    flit_in[0][PORT_L].valid = 1'b0;

    for (int i = 0; i < 25; i++) begin
      @(posedge clk);
      if (flit_out[1][PORT_L].valid)
        $display("t=%0d r1 L_OUT valid dst=%0d itime=%0d", tick[1],
                 flit_out[1][PORT_L].flit.dst, flit_out[1][PORT_L].flit.itime);
    end
    $finish;
  end
endmodule

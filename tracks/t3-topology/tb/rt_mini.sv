`timescale 1ns/1ps

// Mini-TB: ONE router, drive a 1-flit packet into the local port, watch the
// E output. Debug harness for Gate R0 failures (network-bound flits stuck).

module rt_mini;
  import noc_pkg::*;
  localparam int VCS = 4;

  logic clk = 1'b0;
  always #5 clk = ~clk;
  logic rst_n = 1'b0;

  link_f_t flit_in[NUM_PORTS];
  link_c_t credit_in[NUM_PORTS];
  link_f_t flit_out[NUM_PORTS];
  link_c_t credit_out[NUM_PORTS];
  logic [31:0] tick, recv_cnt[NUM_PORTS], send_cnt[NUM_PORTS], pop_cnt[NUM_PORTS];

  noc_router #(.VCS(VCS), .X(0), .Y(0), .X_DIM(4), .Y_DIM(4)) u_rt (
    .clk(clk), .rst_n(rst_n),
    .flit_in(flit_in), .credit_in(credit_in),
    .flit_out(flit_out), .credit_out(credit_out),
    .tick(tick), .recv_cnt(recv_cnt), .send_cnt(send_cnt), .pop_cnt(pop_cnt)
  );

  initial begin
    for (int p = 0; p < NUM_PORTS; p++) begin
      flit_in[p].valid = 1'b0; flit_in[p].flit = '0;
      credit_in[p].valid = 1'b0; credit_in[p].vc = '0;
    end
    repeat (4) @(posedge clk);
    rst_n = 1'b1;
    repeat (2) @(posedge clk);

    // inject a 1-flit packet (head+tail, dst=1 -> PORT_E) at tick 10
    repeat (4) @(posedge clk);   // now tick == 10
    flit_in[PORT_L].valid = 1'b1;
    flit_in[PORT_L].flit.data  = '0;
    flit_in[PORT_L].flit.head  = 1'b1;
    flit_in[PORT_L].flit.tail  = 1'b1;
    flit_in[PORT_L].flit.vc    = 3'd0;
    flit_in[PORT_L].flit.dst   = 8'd1;
    @(posedge clk);
    flit_in[PORT_L].valid = 1'b0;

    // run to tick 30, dumping the E output + local pops
    for (int i = 0; i < 20; i++) begin
      @(posedge clk);
      if (flit_out[PORT_E].valid)
        $display("t=%0d E_OUT valid flit dst=%0d vc=%0d head=%0d tail=%0d",
                 tick, flit_out[PORT_E].flit.dst, flit_out[PORT_E].flit.vc,
                 flit_out[PORT_E].flit.head, flit_out[PORT_E].flit.tail);
    end
    $display("SUMMARY tick=%0d pop E=%0d pop L=%0d send E=%0d",
             tick, pop_cnt[PORT_E], pop_cnt[PORT_L], send_cnt[PORT_E]);
    $finish;
  end
endmodule

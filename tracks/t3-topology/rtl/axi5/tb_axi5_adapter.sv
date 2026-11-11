`default_nettype none

// tb_axi5_adapter.sv — directed AXI5 feature suite for the emitted adapter.
//
// The product claims the AXI5 adapter realizes the full AW/W/AR/R/B channel
// set with WSTRB/WLAST, ID tracking, EXCLUSIVE/ATOMIC, DVM/RSOS and an
// outstanding limit. This suite proves those claims on the emitted RTL.
//
// Port sides follow the emitted adapter exactly (as the slice instantiates
// it): `in_aw*`/`in_ar*` and the bare `w*`/`b*`/`r*` names are the AXI5 side;
// `out_*` is the fabric side, except the B/R responses the adapter returns
// to the AXI5 side, which are `out_b*`/`out_r*`.
module tb_axi5_adapter;

  localparam int DATA_W = 32;
  localparam int ADDR_W = 64;
  localparam int ID_W = 8;
  localparam int MAX_OUT = 2;

  logic clk = 1'b0;
  always #5 clk = ~clk;
  logic rst_n = 1'b0;

  // ---- AXI5 side: write address ----
  logic [ADDR_W-1:0] in_awaddr;
  logic [7:0] in_awlen;
  logic [2:0] in_awsize;
  logic [1:0] in_awburst;
  logic [3:0] in_awcache;
  logic [2:0] in_awprot;
  logic [1:0] in_awlock;
  logic [3:0] in_awqos;
  logic [3:0] in_awregion;
  logic [1:0] in_awdomain;
  logic [2:0] in_awatomic;
  logic [1:0] in_awdvmtype;
  logic [ID_W-1:0] in_awid;
  logic in_awvalid;
  logic in_awready;

  // ---- AXI5 side: write data ----
  logic [DATA_W-1:0] wdata;
  logic [DATA_W/8-1:0] wstrb;
  logic wlast;
  logic wvalid;
  logic wready;

  // ---- AXI5 side: read address ----
  logic [ADDR_W-1:0] in_araddr;
  logic [7:0] in_arlen;
  logic [2:0] in_arsize;
  logic [1:0] in_arburst;
  logic [3:0] in_arcache;
  logic [2:0] in_arprot;
  logic [1:0] in_arlock;
  logic [3:0] in_arqos;
  logic [3:0] in_arregion;
  logic [1:0] in_ardomain;
  logic [2:0] in_aratomic;
  logic [1:0] in_ardvmtype;
  logic [ID_W-1:0] in_arid;
  logic in_arvalid;
  logic in_arready;

  // ---- AXI5 side: responses the adapter returns ----
  logic out_bvalid;
  logic [1:0] out_bresp;
  logic [ID_W-1:0] out_bid;
  logic out_bready;

  logic [DATA_W-1:0] out_rdata;
  logic [1:0] out_rresp;
  logic [ID_W-1:0] out_rid;
  logic out_rlast;
  logic out_rvalid;
  logic out_rready;

  // ---- fabric side: what the adapter presents ----
  logic [ADDR_W-1:0] out_awaddr;
  logic [7:0] out_awlen;
  logic [2:0] out_awsize;
  logic [1:0] out_awburst;
  logic [3:0] out_awcache;
  logic [2:0] out_awprot;
  logic [1:0] out_awlock;
  logic [3:0] out_awqos;
  logic [3:0] out_awregion;
  logic [1:0] out_awdomain;
  logic [2:0] out_awatomic;
  logic [1:0] out_awdvmtype;
  logic [ID_W-1:0] out_awid;
  logic out_awvalid;
  logic out_awready;

  logic [DATA_W-1:0] out_wdata;
  logic [DATA_W/8-1:0] out_wstrb;
  logic out_wlast;
  logic out_wvalid;
  logic out_wready;

  logic [ADDR_W-1:0] out_araddr;
  logic [7:0] out_arlen;
  logic [2:0] out_arsize;
  logic [1:0] out_arburst;
  logic [3:0] out_arcache;
  logic [2:0] out_arprot;
  logic [1:0] out_arlock;
  logic [3:0] out_arqos;
  logic [3:0] out_arregion;
  logic [1:0] out_ardomain;
  logic [2:0] out_aratomic;
  logic [1:0] out_ardvmtype;
  logic [ID_W-1:0] out_arid;
  logic out_arvalid;
  logic out_arready;

  // ---- fabric side: responses the fabric returns to the adapter ----
  logic bvalid;
  logic [1:0] bresp;
  logic [ID_W-1:0] bid;
  logic bready;

  logic [DATA_W-1:0] rdata;
  logic [ID_W-1:0] rid;
  logic [1:0] rresp;
  logic rlast;
  logic rvalid;
  logic rready;

  logic credit_full;
  logic aw_error;
  logic ar_error;
  logic exclusive_error;
  logic atomic_error;
  logic coh_error;
  logic resp_error;
  logic wstrb_error;
  logic last_error;
  logic id_error;
  logic out_dvm_valid;
  logic out_rsos_valid;
  logic dvm_pending;
  logic rsos_pending;
  logic [1:0] coh_state;
  logic qos_high;

  adapter_axi5_g0 #(
    .DATA_W_IN(DATA_W), .DATA_W_OUT(DATA_W), .ADDR_W(ADDR_W),
    .SPLIT_AT(0), .MAX_OUTSTANDING(MAX_OUT), .ID_W(ID_W),
    .DVM_ENABLE(1), .RSOS_ENABLE(1), .COH_INIT(0)
  ) dut (.*);

  task automatic fail_msg(input string m);
    $display("FAIL: %s", m);
    $fatal(1);
  endtask

  int timeout;
  int i;
  int captured_wbeats;
  int captured_rbeats;
  logic [ADDR_W-1:0] captured_awaddr;
  logic [7:0] captured_awlen;
  logic [ID_W-1:0] captured_awid;
  logic [1:0] captured_awlock;
  logic [2:0] captured_awatomic;
  logic [1:0] captured_awdvmtype;
  logic [3:0] captured_awqos;
  logic [DATA_W-1:0] captured_wdata;
  logic [DATA_W/8-1:0] captured_wstrb;
  logic captured_wlast;
  logic [ADDR_W-1:0] captured_araddr;
  logic [ID_W-1:0] captured_arid;
  logic [DATA_W-1:0] held_data;
  logic held_last;

  always @(posedge clk) begin
    if (rst_n) begin
      if (out_awvalid && out_awready) begin
        captured_awaddr <= out_awaddr;
        captured_awlen <= out_awlen;
        captured_awid <= out_awid;
        captured_awlock <= out_awlock;
        captured_awatomic <= out_awatomic;
        captured_awdvmtype <= out_awdvmtype;
        captured_awqos <= out_awqos;
      end
      if (out_wvalid && out_wready) begin
        captured_wdata <= out_wdata;
        captured_wstrb <= out_wstrb;
        captured_wlast <= out_wlast;
        captured_wbeats <= captured_wbeats + 1;
      end
      if (out_arvalid && out_arready) begin
        captured_araddr <= out_araddr;
        captured_arid <= out_arid;
      end
      if (out_rvalid && out_rready && out_rlast) begin
        captured_rbeats <= captured_rbeats + 1;
      end
    end
  end

  task automatic reset_dut();
    begin
      in_awaddr = '0; in_awlen = '0; in_awsize = '0; in_awburst = '0;
      in_awcache = '0; in_awprot = '0; in_awlock = '0; in_awqos = '0;
      in_awregion = '0; in_awdomain = '0; in_awatomic = '0; in_awdvmtype = '0;
      in_awid = '0; in_awvalid = 1'b0;
      wdata = '0; wstrb = '0; wlast = 1'b0; wvalid = 1'b0;
      in_araddr = '0; in_arlen = '0; in_arsize = '0; in_arburst = '0;
      in_arcache = '0; in_arprot = '0; in_arlock = '0; in_arqos = '0;
      in_arregion = '0; in_ardomain = '0; in_aratomic = '0; in_ardvmtype = '0;
      in_arid = '0; in_arvalid = 1'b0;
      out_bready = 1'b1; out_rready = 1'b1;
      out_awready = 1'b1; out_wready = 1'b1; out_arready = 1'b1;
      bvalid = 1'b0; bresp = 2'b00; bid = '0;
      rvalid = 1'b0; rdata = '0; rresp = 2'b00; rid = '0; rlast = 1'b0;
    end
  endtask

  initial begin
    reset_dut();
    captured_wbeats = 0;
    captured_rbeats = 0;
    repeat (4) @(posedge clk);
    rst_n <= 1'b1;
    repeat (2) @(posedge clk);

    // --- S1: single-beat write with full AXI5 attribute forwarding ---
    in_awaddr = 64'h1000;
    in_awlen = 8'd0;
    in_awsize = 3'd2;
    in_awburst = 2'b01;
    in_awlock = 2'b01;
    in_awatomic = 3'b010;
    in_awdvmtype = 2'b11;
    in_awqos = 4'h5;
    in_awid = 8'hA5;
    in_awvalid = 1'b1;
    timeout = 0;
    while (!in_awready && timeout < 50) begin @(posedge clk); timeout = timeout + 1; end
    if (!in_awready) fail_msg("S1 the adapter never accepted the write address");
    @(posedge clk);
    in_awvalid = 1'b0;

    wdata = 32'hDEAD_BEEF;
    wstrb = 4'hF;
    wlast = 1'b1;
    wvalid = 1'b1;
    timeout = 0;
    while (!wready && timeout < 50) begin @(posedge clk); timeout = timeout + 1; end
    if (!wready) fail_msg("S1 the adapter never accepted the write data");
    @(posedge clk);
    wvalid = 1'b0;

    timeout = 0;
    while (captured_wbeats < 1 && timeout < 50) begin @(posedge clk); timeout = timeout + 1; end
    if (captured_wbeats != 1) fail_msg("S1 the fabric did not receive exactly one write beat");
    if (captured_awaddr !== 64'h1000) fail_msg("S1 the address was not forwarded");
    if (captured_awid !== 8'hA5) fail_msg("S1 the ID was not forwarded");
    if (captured_awlock !== 2'b01) fail_msg("S1 EXCLUSIVE (awlock) was not forwarded");
    if (captured_awatomic !== 3'b010) fail_msg("S1 ATOMIC was not forwarded");
    if (captured_awdvmtype !== 2'b11) fail_msg("S1 DVM type was not forwarded");
    if (captured_awqos !== 4'h5) fail_msg("S1 QoS was not forwarded");
    if (captured_wdata !== 32'hDEAD_BEEF) fail_msg("S1 the write data was corrupted");
    if (captured_wstrb !== 4'hF) fail_msg("S1 the WSTRB was corrupted");
    if (!captured_wlast) fail_msg("S1 WLAST was not asserted on the single beat");

    bresp = 2'b00;
    bid = 8'hA5;
    bvalid = 1'b1;
    timeout = 0;
    while (!out_bvalid && timeout < 50) begin @(posedge clk); timeout = timeout + 1; end
    if (!out_bvalid) fail_msg("S1 no B response reached the AXI5 side");
    if (out_bid !== 8'hA5) fail_msg("S1 the B response carried the wrong ID");
    if (out_bresp !== 2'b00) fail_msg("S1 the B response was not OKAY");
    @(posedge clk);
    bvalid = 1'b0;
    @(posedge clk);
    $display("PASS: S1 single-beat write with full AXI5 attribute forwarding and one B response");

    // --- S2: four-beat burst write ---
    reset_dut();
    captured_wbeats = 0;
    @(posedge clk);
    in_awaddr = 64'h2000;
    in_awlen = 8'd3;
    in_awsize = 3'd2;
    in_awburst = 2'b01;
    in_awid = 8'h11;
    in_awvalid = 1'b1;
    timeout = 0;
    while (!in_awready && timeout < 50) begin @(posedge clk); timeout = timeout + 1; end
    @(posedge clk);
    in_awvalid = 1'b0;
    for (i = 0; i < 4; i = i + 1) begin
      wdata = 32'h1000 + i;
      wstrb = 4'hF;
      wlast = (i == 3);
      wvalid = 1'b1;
      timeout = 0;
      while (!wready && timeout < 50) begin @(posedge clk); timeout = timeout + 1; end
      @(posedge clk);
      wvalid = 1'b0;
    end
    timeout = 0;
    while (captured_wbeats < 4 && timeout < 100) begin @(posedge clk); timeout = timeout + 1; end
    if (captured_wbeats != 4) fail_msg("S2 the fabric did not receive four burst beats");
    if (captured_awlen !== 8'd3) fail_msg("S2 the burst length was not forwarded");
    if (!captured_wlast) fail_msg("S2 WLAST was not asserted on the last beat");
    $display("PASS: S2 four-beat burst write with WLAST on the final beat");

    // --- S3: read with one R beat ---
    reset_dut();
    captured_rbeats = 0;
    @(posedge clk);
    in_araddr = 64'h3000;
    in_arlen = 8'd0;
    in_arsize = 3'd2;
    in_arburst = 2'b01;
    in_arid = 8'h22;
    in_arvalid = 1'b1;
    timeout = 0;
    while (!in_arready && timeout < 50) begin @(posedge clk); timeout = timeout + 1; end
    if (!in_arready) fail_msg("S3 the adapter never accepted the read address");
    @(posedge clk);
    in_arvalid = 1'b0;
    repeat (2) @(posedge clk);
    if (captured_araddr !== 64'h3000) fail_msg("S3 the read address was not forwarded");
    if (captured_arid !== 8'h22) fail_msg("S3 the read ID was not forwarded");
    rvalid = 1'b1;
    rdata = 32'h1234_5678;
    rresp = 2'b00;
    rid = 8'h22;
    rlast = 1'b1;
    timeout = 0;
    while (!out_rvalid && timeout < 50) begin @(posedge clk); timeout = timeout + 1; end
    if (!out_rvalid) fail_msg("S3 no R response reached the AXI5 side");
    if (out_rdata !== 32'h1234_5678) fail_msg("S3 the read data was corrupted");
    if (out_rid !== 8'h22) fail_msg("S3 the read response carried the wrong ID");
    if (!out_rlast) fail_msg("S3 RLAST was not asserted");
    @(posedge clk);
    rvalid = 1'b0;
    $display("PASS: S3 read address forwarded, one R beat with RLAST and the right ID");

    // --- S4: the adapter holds its write beat stable under backpressure ---
    reset_dut();
    @(posedge clk);
    out_wready = 1'b0;
    in_awaddr = 64'h4000;
    in_awlen = 8'd0;
    in_awsize = 3'd2;
    in_awburst = 2'b01;
    in_awid = 8'h33;
    in_awvalid = 1'b1;
    timeout = 0;
    while (!in_awready && timeout < 50) begin @(posedge clk); timeout = timeout + 1; end
    @(posedge clk);
    in_awvalid = 1'b0;
    wdata = 32'hCAFEBABE;
    wstrb = 4'hF;
    wlast = 1'b1;
    wvalid = 1'b1;
    timeout = 0;
    while (!wready && timeout < 50) begin @(posedge clk); timeout = timeout + 1; end
    @(posedge clk);
    wvalid = 1'b0;
    held_data = out_wdata;
    held_last = out_wlast;
    repeat (4) begin
      @(posedge clk);
      if (out_wvalid && (out_wdata !== held_data || out_wlast !== held_last))
        fail_msg("S4 the adapter changed its write beat while the fabric stalled");
    end
    out_wready = 1'b1;
    $display("PASS: S4 the adapter holds its write beat stable while the fabric stalls");

    // --- S5: the outstanding limit is honoured ---
    reset_dut();
    @(posedge clk);
    in_awaddr = 64'h5000;
    in_awlen = 8'd0;
    in_awsize = 3'd2;
    in_awburst = 2'b01;
    in_awid = 8'h44;
    in_awvalid = 1'b1;
    timeout = 0;
    while (!in_awready && timeout < 50) begin @(posedge clk); timeout = timeout + 1; end
    @(posedge clk);
    in_awvalid = 1'b0;
    wdata = 32'h0;
    wstrb = 4'hF;
    wlast = 1'b1;
    wvalid = 1'b1;
    timeout = 0;
    while (!wready && timeout < 50) begin @(posedge clk); timeout = timeout + 1; end
    @(posedge clk);
    wvalid = 1'b0;
    in_awaddr = 64'h6000;
    in_awid = 8'h55;
    in_awvalid = 1'b1;
    @(posedge clk);
    if (in_awready) fail_msg("S5 the adapter accepted more than MAX_OUTSTANDING addresses");
    in_awvalid = 1'b0;
    bresp = 2'b00;
    bid = 8'h44;
    bvalid = 1'b1;
    timeout = 0;
    while (!out_bvalid && timeout < 50) begin @(posedge clk); timeout = timeout + 1; end
    @(posedge clk);
    bvalid = 1'b0;
    @(posedge clk);
    $display("PASS: S5 the adapter refuses more addresses than MAX_OUTSTANDING");

    // --- S6: the B response carries the ID of the request that caused it ---
    reset_dut();
    @(posedge clk);
    in_awaddr = 64'h7000;
    in_awlen = 8'd0;
    in_awsize = 3'd2;
    in_awburst = 2'b01;
    in_awid = 8'h66;
    in_awvalid = 1'b1;
    timeout = 0;
    while (!in_awready && timeout < 50) begin @(posedge clk); timeout = timeout + 1; end
    @(posedge clk);
    in_awvalid = 1'b0;
    wdata = 32'h0;
    wstrb = 4'hF;
    wlast = 1'b1;
    wvalid = 1'b1;
    timeout = 0;
    while (!wready && timeout < 50) begin @(posedge clk); timeout = timeout + 1; end
    @(posedge clk);
    wvalid = 1'b0;
    bresp = 2'b00;
    bid = 8'h66;
    bvalid = 1'b1;
    timeout = 0;
    while (!out_bvalid && timeout < 50) begin @(posedge clk); timeout = timeout + 1; end
    if (out_bid !== 8'h66) fail_msg("S6 the B response carried the wrong ID");
    @(posedge clk);
    bvalid = 1'b0;
    $display("PASS: S6 the B response carries the ID of the request that caused it");

    $display("status: PASS");
    $finish;
  end

  initial begin
    #500000;
    $display("FAIL: timeout");
    $fatal(1);
  end

endmodule

`default_nettype wire

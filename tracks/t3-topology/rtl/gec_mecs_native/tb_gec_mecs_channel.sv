`timescale 1ns/1ps
module tb_gec_mecs_channel;
  localparam integer K=4, W=16;
  logic clk=0, rst_n=0, tx_valid;
  logic [W-1:0] tx_payload;
  logic [1:0] tx_dst_idx;
  logic [K-1:0] tx_mcast_bitmap, tap_credit;
  wire tx_credit_ok;
  wire [K-1:0] tap_valid;
  wire [K-1:0][W-1:0] tap_payload;
  always #5 clk=~clk;
  gec_mecs_channel #(.K(K),.W(W)) dut(.*);

  task tick; begin @(posedge clk); #1; end endtask
  task check(input logic cond, input string msg); begin
    if (!cond) begin $display("FAIL: %s",msg); $fatal(1); end
  end endtask
  integer i;
  initial begin
    tx_valid=0; tx_payload=0; tx_dst_idx=0; tx_mcast_bitmap=0; tap_credit='1;
    tick(); rst_n=1; tick();
    check(tap_valid=='0,"reset/no phantom transfer");

    // Zero bitmap selects exactly the decoded unicast tap.
    tx_valid=1; tx_dst_idx=2; tx_payload=16'h1234; tx_mcast_bitmap=0; tap_credit='1;
    tick(); check(tap_valid==4'b0100,"zero bitmap unicast selector");
    check(tap_payload[2]==16'h1234,"unicast payload");
    check(tap_valid[0]==0 && tap_valid[1]==0 && tap_valid[3]==0,"unselected taps idle");

    // Every selected tap independently denies the entire multicast transfer.
    tx_mcast_bitmap=4'b1011; tx_dst_idx=2; tx_payload=16'h5678;
    for (i=0;i<K;i=i+1) begin
      tap_credit='1; tap_credit[i]=0;
      if (i==2) begin
        #1; check(tx_credit_ok,"unselected credit masked");
        tick(); check(tap_valid==4'b1011,"unselected denial does not block multicast");
      end else begin
        #1; check(!tx_credit_ok,"selected credit denial");
        tick(); check(tap_valid=='0,"denied multicast has no partial taps");
      end
    end

    tap_credit='1; #1; check(tx_credit_ok,"all selected credits available");
    tick(); check(tap_valid==4'b1011,"exact multicast bitmap");
    for (i=0;i<K;i=i+1) if (tap_valid[i]) check(tap_payload[i]==16'h5678,"multicast payload");

    // A nonzero bitmap overrides dst_idx, including when dst points elsewhere.
    tx_dst_idx=2; tx_mcast_bitmap=4'b0001; tx_payload=16'h9abc;
    tick(); check(tap_valid==4'b0001,"bitmap overrides destination index");
    tx_valid=0; tick(); check(tap_valid=='0,"no phantom transfer when invalid");
    $display("PASS: GEC MECS shared-channel directed tests"); $finish;
  end
endmodule

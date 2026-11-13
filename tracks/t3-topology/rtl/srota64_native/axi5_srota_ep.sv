`default_nettype none
`timescale 1ns/1ps
// AXI5 endpoint bridge for the SROTA64 native fabric.
//
// The fabric carries one 80-bit packet per transfer and its egress has no
// ingress identity, so every packet names its destination router (flit bits
// 79:74, driven from the address by the requester) plus its source endpoint,
// transaction id and operation inside the opaque 74-bit payload. A delivery is
// therefore self-describing, and a responder can answer the requester directly.
//
// Payload map (flit[73:18]):
//   [73:72] op        00 WRITE, 01 WRITE_ACK, 10 READ_REQ, 11 READ_RSP
//   [71:66] peer      endpoint that must receive the reply
//   [65:58] id        AXI transaction id, returned unchanged on B and R
//   [57:54] word      word index inside the endpoint's 64-byte region
//   [53:50] wstrb     byte strobes, honoured per lane on WRITE
//   [49:18] data      32-bit write data, or read data on READ_RSP
//
// Address contract: bits [11:6] select the destination router, bits [5:2]
// select the word inside that router's 16-word region.
//
// Scope: one beat per transaction (awlen/arlen must be zero), one outstanding
// write and one outstanding read per endpoint, in-order replies. Not a full
// AXI5 implementation: no bursts, no exclusive or atomic access, no cache,
// domain or QoS semantics, no write-completion reordering.
module axi5_srota_ep #(
  parameter int EP = 0,
  parameter int W = 80,
  parameter int WORDS = 16
) (
  input logic clk,
  input logic rst_n,

  input  logic [63:0] awaddr,
  input  logic [7:0]  awid,
  input  logic        awvalid,
  output logic        awready,
  input  logic [31:0] wdata,
  input  logic [3:0]  wstrb,
  input  logic        wlast,
  input  logic        wvalid,
  output logic        wready,
  output logic [7:0]  bid,
  output logic        bvalid,
  input  logic        bready,
  input  logic [63:0] araddr,
  input  logic [7:0]  arid,
  input  logic        arvalid,
  output logic        arready,
  output logic [7:0]  rid,
  output logic [31:0] rdata,
  output logic        rvalid,
  input  logic        rready,

  output logic        inj_valid,
  input  logic        inj_ready,
  output logic [W-1:0] inj_flit,
  input  logic        eject_valid,
  output logic        eject_ready,
  input  logic [W-1:0] eject_flit
);

  localparam int OP_WRITE = 2'b00;
  localparam int OP_ACK   = 2'b01;
  localparam int OP_RDREQ = 2'b10;
  localparam int OP_RDRSP = 2'b11;
  localparam int PQ_DEPTH = 8;
  localparam int EP6 = EP;

  logic [31:0] mem [WORDS];

  logic        aw_have, w_have, wr_sent, rd_sent;
  logic [63:0] aw_addr;
  logic [7:0]  aw_id;
  logic [31:0] w_dat;
  logic [3:0]  w_strb;

  logic         wr_pkt_have, rd_pkt_have;
  logic [W-1:0] wr_pkt, rd_pkt;

  logic [W-1:0] pq [PQ_DEPTH];
  logic [3:0]   pq_head, pq_tail, pq_count;

  logic        b_hold, r_hold;
  logic [7:0]  b_hold_id, r_hold_id;
  logic [31:0] r_hold_data;

  // Incoming delivery decode (combinational).
  logic [1:0]  rx_op;
  logic [5:0]  rx_dst, rx_peer;
  logic [7:0]  rx_id;
  logic [3:0]  rx_word, rx_strb;
  logic [31:0] rx_data;
  logic [31:0] rx_merged;

  assign rx_op   = eject_flit[73:72];
  assign rx_dst  = eject_flit[79:74];
  assign rx_peer = eject_flit[71:66];
  assign rx_id   = eject_flit[65:58];
  assign rx_word = eject_flit[57:54];
  assign rx_strb = eject_flit[53:50];
  assign rx_data = eject_flit[49:18];

  always @(*) begin
    rx_merged = mem[rx_word];
    if (rx_strb[0]) rx_merged[7:0]   = rx_data[7:0];
    if (rx_strb[1]) rx_merged[15:8]  = rx_data[15:8];
    if (rx_strb[2]) rx_merged[23:16] = rx_data[23:16];
    if (rx_strb[3]) rx_merged[31:24] = rx_data[31:24];
  end

  function automatic logic [W-1:0] payload_pkt(
    input logic [1:0]  op,
    input logic [5:0]  dst,
    input logic [5:0]  peer,
    input logic [7:0]  id,
    input logic [3:0]  word,
    input logic [3:0]  strb,
    input logic [31:0] data
  );
    logic [W-1:0] f;
    f        = '0;
    f[79:74] = dst;
    f[73:72] = op;
    f[71:66] = peer;
    f[65:58] = id;
    f[57:54] = word;
    f[53:50] = strb;
    f[49:18] = data;
    // Function-name assignment rather than `return`, so synthesizers that do not
    // implement the SystemVerilog return statement can read this file too.
    payload_pkt = f;
  endfunction

  // The responder never stalls: it owns one word of memory and one ordered
  // reply queue. Fabric-side backpressure is exercised by the fabric itself.
  assign eject_ready = 1'b1;

  assign awready = rst_n && !aw_have && !wr_sent && !wr_pkt_have;
  assign wready  = rst_n && !w_have  && !wr_sent && !wr_pkt_have;
  assign arready = rst_n && !rd_sent && !rd_pkt_have;

  assign bid    = b_hold_id;
  assign bvalid = b_hold;
  assign rid    = r_hold_id;
  assign rdata  = r_hold_data;
  assign rvalid = r_hold;

  logic        pq_pop;
  logic        pq_push;
  logic [W-1:0] pq_push_data;

  assign pq_pop = inj_valid && inj_ready && (pq_count != 4'd0);
  assign pq_push = eject_valid && (rx_op == OP_WRITE || rx_op == OP_RDREQ);
  assign pq_push_data = (rx_op == OP_WRITE)
      ? payload_pkt(OP_ACK,   rx_peer, EP6[5:0], rx_id, rx_word, 4'h0, 32'h0)
      : payload_pkt(OP_RDRSP, rx_peer, EP6[5:0], rx_id, rx_word, 4'h0, mem[rx_word]);

  always @(*) begin
    inj_valid = 1'b0;
    inj_flit  = '0;
    if (pq_count != 4'd0) begin
      inj_valid = 1'b1;
      inj_flit  = pq[pq_head];
    end else if (rd_pkt_have) begin
      inj_valid = 1'b1;
      inj_flit  = rd_pkt;
    end else if (wr_pkt_have) begin
      inj_valid = 1'b1;
      inj_flit  = wr_pkt;
    end
  end

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      aw_have <= 1'b0; w_have <= 1'b0;
      wr_sent <= 1'b0; rd_sent <= 1'b0;
      aw_addr <= '0; aw_id <= '0; w_dat <= '0; w_strb <= '0;
      wr_pkt_have <= 1'b0; rd_pkt_have <= 1'b0; wr_pkt <= '0; rd_pkt <= '0;
      pq_head <= '0; pq_tail <= '0; pq_count <= '0;
      b_hold <= 1'b0; r_hold <= 1'b0;
      b_hold_id <= '0; r_hold_id <= '0; r_hold_data <= '0;
      for (int i = 0; i < WORDS; i++) mem[i] <= '0;
      for (int i = 0; i < PQ_DEPTH; i++) pq[i] <= '0;
    end else begin
      // --- AXI request capture -------------------------------------------
      if (awvalid && awready) begin
        aw_have <= 1'b1; aw_addr <= awaddr; aw_id <= awid;
      end
      if (wvalid && wready) begin
        w_have <= 1'b1; w_dat <= wdata; w_strb <= wstrb;
      end
      if (aw_have && w_have && !wr_pkt_have && !wr_sent) begin
        wr_pkt <= payload_pkt(OP_WRITE, aw_addr[11:6], EP6[5:0], aw_id,
                              aw_addr[5:2], w_strb, w_dat);
        wr_pkt_have <= 1'b1;
        wr_sent <= 1'b1;
        aw_have <= 1'b0; w_have <= 1'b0;
      end
      if (arvalid && arready) begin
        rd_pkt <= payload_pkt(OP_RDREQ, araddr[11:6], EP6[5:0], arid,
                              araddr[5:2], 4'h0, 32'h0);
        rd_pkt_have <= 1'b1;
        rd_sent <= 1'b1;
      end

      // --- request packet accepted by the fabric -------------------------
      if (inj_valid && inj_ready) begin
        if (pq_count == 4'd0 && rd_pkt_have) rd_pkt_have <= 1'b0;
        else if (pq_count == 4'd0 && !rd_pkt_have && wr_pkt_have) wr_pkt_have <= 1'b0;
      end

      // --- fabric delivery -------------------------------------------------
      if (eject_valid) begin
        if (rx_op == OP_WRITE) begin
          mem[rx_word] <= rx_merged;
        end else if (rx_op == OP_ACK) begin
          b_hold <= 1'b1;
          b_hold_id <= rx_id;
          wr_sent <= 1'b0;
        end else if (rx_op == OP_RDRSP) begin
          r_hold <= 1'b1;
          r_hold_id <= rx_id;
          r_hold_data <= rx_data;
          rd_sent <= 1'b0;
        end
      end

      // --- reply queue -----------------------------------------------------
      if (pq_push && !pq_pop) begin
        pq[pq_tail] <= pq_push_data;
        pq_tail <= pq_tail + 4'd1;
        pq_count <= pq_count + 4'd1;
      end else if (!pq_push && pq_pop) begin
        pq_head <= pq_head + 4'd1;
        pq_count <= pq_count - 4'd1;
      end else if (pq_push && pq_pop) begin
        pq[pq_tail] <= pq_push_data;
        pq_tail <= pq_tail + 4'd1;
        pq_head <= pq_head + 4'd1;
      end

      // --- AXI reply handshakes --------------------------------------------
      if (b_hold && bready) b_hold <= 1'b0;
      if (r_hold && rready) r_hold <= 1'b0;
    end
  end

endmodule
`default_nettype wire

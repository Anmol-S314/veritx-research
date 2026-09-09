// axi4_flit.sv — AXI4 protocol flit mapper for NoC (router-compatible)
//
// Flit format matches noc_pkg convention:
//   [63]         = esc bit (0 = free class)
//   [62:61]      = type: HEAD=0 BODY=1 TAIL=2 SINGLE=3
//   [DST_W-1+48:48] = destination router ID
//   [47:44]      = source router ID (4 bits, for 16-node)
//   [43:32]      = AXI4 metadata: [43:41]=channel, [40:37]=axi_id,
//                  [36:33]=burst_len, [32]=last
//   [31:0]       = payload (address or 32-bit data half)
//
// Multi-flit burst encoding:
//   AW/AR: SINGLE flit with address + burst params
//   W:     HEAD (first beat) + BODY (middle) + TAIL (last beat)
//          Each beat carries 32 bits of 64-bit data (2 flits per beat)
//   R:     HEAD + BODY + TAIL carrying read data back
//   B:     SINGLE flit with write response
//
// TX/RX share a single NoC inject port via priority mux:
//   TX has priority (request path); RX drives when TX is IDLE (response path).
`include "noc_pkg.sv"

module axi4_flit #(
  parameter int N_ROUTERS = 16,
  parameter int MY_ID     = 0
) (
  input  logic clk,
  input  logic rst_n,

  // ── AXI4 Master Interface (from core/memory) ──
  input  logic [3:0]             s_axi_awid,
  input  logic [31:0]            s_axi_awaddr,
  input  logic [7:0]             s_axi_awlen,
  input  logic [2:0]             s_axi_awsize,
  input  logic [1:0]             s_axi_awburst,
  input  logic                   s_axi_awvalid,
  output logic                   s_axi_awready,

  input  logic [63:0]            s_axi_wdata,
  input  logic [7:0]             s_axi_wstrb,
  input  logic                   s_axi_wlast,
  input  logic                   s_axi_wvalid,
  output logic                   s_axi_wready,

  output logic [3:0]             s_axi_bid,
  output logic [1:0]             s_axi_bresp,
  output logic                   s_axi_bvalid,
  input  logic                   s_axi_bready,

  input  logic [3:0]             s_axi_arid,
  input  logic [31:0]            s_axi_araddr,
  input  logic [7:0]             s_axi_arlen,
  input  logic [2:0]             s_axi_arsize,
  input  logic [1:0]             s_axi_arburst,
  input  logic                   s_axi_arvalid,
  output logic                   s_axi_arready,

  output logic [3:0]             s_axi_rid,
  output logic [63:0]            s_axi_rdata,
  output logic [1:0]             s_axi_rresp,
  output logic                   s_axi_rlast,
  output logic                   s_axi_rvalid,
  input  logic                   s_axi_rready,

  // ── NoC TX Interface (to router LOCAL port) ──
  output logic [63:0]            noc_tx_flit,
  output logic                   noc_tx_valid,
  input  logic                   noc_tx_ready,

  // ── NoC RX Interface (from router LOCAL port) ──
  input  logic [63:0]            noc_rx_flit,
  input  logic                   noc_rx_valid,
  output logic                   noc_rx_ready,

  // ── Configuration ──
  input  logic [3:0]             target_id
);

  // ── AXI4 Channel Encoding ──
  localparam logic [2:0] CH_AW = 3'd0, CH_W = 3'd1, CH_B = 3'd2,
                         CH_AR = 3'd3, CH_R = 3'd4;

  // ── Flit type helpers ──
  localparam logic [1:0] FT_HEAD = 2'd0, FT_BODY = 2'd1,
                         FT_TAIL = 2'd2, FT_SINGLE = 2'd3;

  // ── Flit assembly helpers ──
  function automatic logic [11:0] make_meta(
    input logic [2:0] ch, input logic [3:0] id,
    input logic [7:0] bval, input logic last);
    return {ch, id, bval[3:0], last};
  endfunction

  function automatic logic [63:0] make_flit(
    input logic [1:0] typ, input logic [3:0] dst,
    input logic [11:0] meta, input logic [31:0] payload);
    logic [63:0] f;
    f[63]    = 1'b0;
    f[62:61] = typ;
    f[51:48] = dst;
    f[47:44] = MY_ID[3:0];
    f[43:32] = meta;
    f[31:0]  = payload;
    return f;
  endfunction

  // ── TX State Machine ──
  typedef enum logic [3:0] {
    TX_IDLE, TX_AW_SEND, TX_AR_SEND,
    TX_WDATA_SEND, TX_WDATA_HALF, TX_WAIT_RESP
  } tx_state_t;
  tx_state_t tx_state;

  logic [3:0]  tx_axi_id;
  logic [31:0] tx_addr;
  logic [7:0]  tx_axi_len, tx_beat_cnt;
  logic [2:0]  tx_axi_size;
  logic [1:0]  tx_axi_burst;
  logic        tx_half;
  logic [63:0] tx_wdata_latch;

  // TX drives these intermediate signals (NOT directly to noc_tx)
  logic [63:0] tx_noc_flit;
  logic        tx_noc_valid;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      tx_state      <= TX_IDLE;
      tx_noc_valid  <= 1'b0;
      tx_noc_flit   <= '0;
      s_axi_awready <= 1'b1;
      s_axi_wready  <= 1'b0;
      s_axi_arready <= 1'b1;
      tx_beat_cnt   <= '0;
      tx_half       <= 1'b0;
    end else begin
      case (tx_state)
        TX_IDLE: begin
          tx_noc_valid <= 1'b0;
          s_axi_awready <= 1'b1;
          s_axi_arready <= 1'b1;
          s_axi_wready  <= 1'b0;
          if (s_axi_awvalid && s_axi_awready) begin
            tx_axi_id    <= s_axi_awid;
            tx_addr      <= s_axi_awaddr;
            tx_axi_len   <= s_axi_awlen;
            tx_axi_size  <= s_axi_awsize;
            tx_axi_burst <= s_axi_awburst;
            tx_beat_cnt  <= '0;
            tx_half      <= 1'b0;
            tx_noc_flit  <= make_flit(FT_SINGLE, target_id,
                            make_meta(CH_AW, s_axi_awid, 8'd0, 1'b1),
                            {8'd0, s_axi_awburst, s_axi_awsize, s_axi_awlen,
                             s_axi_awaddr[31:0]});
            tx_noc_valid <= 1'b1;
            s_axi_awready <= 1'b0;
            s_axi_arready <= 1'b0;
            tx_state     <= TX_AW_SEND;
          end else if (s_axi_arvalid && s_axi_arready) begin
            tx_axi_id    <= s_axi_arid;
            tx_addr      <= s_axi_araddr;
            tx_axi_len   <= s_axi_arlen;
            tx_axi_size  <= s_axi_arsize;
            tx_axi_burst <= s_axi_arburst;
            tx_beat_cnt  <= '0;
            tx_half      <= 1'b0;
            tx_noc_flit  <= make_flit(FT_SINGLE, target_id,
                            make_meta(CH_AR, s_axi_arid, 8'd0, 1'b1),
                            {8'd0, s_axi_arburst, s_axi_arsize, s_axi_arlen,
                             s_axi_araddr[31:0]});
            tx_noc_valid <= 1'b1;
            s_axi_awready <= 1'b0;
            s_axi_arready <= 1'b0;
            tx_state     <= TX_AR_SEND;
          end
        end

        TX_AW_SEND: begin
          if (tx_noc_valid && noc_tx_ready) begin
            tx_noc_valid <= 1'b0;
            s_axi_wready <= 1'b1;
            tx_state     <= TX_WDATA_SEND;
          end
        end

        TX_AR_SEND: begin
          if (tx_noc_valid && noc_tx_ready) begin
            tx_noc_valid <= 1'b0;
            tx_state     <= TX_WAIT_RESP;
          end
        end

        TX_WDATA_SEND: begin
          if (s_axi_wvalid && s_axi_wready) begin
            tx_wdata_latch <= s_axi_wdata;
            if (tx_axi_len == 8'd0) begin
              tx_noc_flit  <= make_flit(FT_HEAD, target_id,
                              make_meta(CH_W, tx_axi_id, tx_beat_cnt, 1'b0),
                              s_axi_wdata[31:0]);
              tx_noc_valid <= 1'b1;
              tx_half      <= 1'b1;
              tx_state     <= TX_WDATA_HALF;
            end else begin
              logic [1:0] wdata_typ;
              wdata_typ = (tx_beat_cnt == 8'd0) ? FT_HEAD : FT_BODY;
              tx_noc_flit  <= make_flit(wdata_typ, target_id,
                              make_meta(CH_W, tx_axi_id, tx_beat_cnt, 1'b0),
                              s_axi_wdata[31:0]);
              tx_noc_valid <= 1'b1;
              tx_half      <= 1'b1;
              tx_state     <= TX_WDATA_HALF;
            end
            s_axi_wready <= 1'b0;
          end
        end

        TX_WDATA_HALF: begin
          if (tx_noc_valid && noc_tx_ready) begin
            logic is_last_beat_h;
            is_last_beat_h = (tx_beat_cnt == {1'b0, tx_axi_len});
            tx_noc_flit  <= make_flit(is_last_beat_h ? FT_TAIL : FT_BODY, target_id,
                            make_meta(CH_W, tx_axi_id, tx_beat_cnt, is_last_beat_h),
                            tx_wdata_latch[63:32]);
            tx_noc_valid <= 1'b1;
            tx_half      <= 1'b0;
            if (is_last_beat_h) begin
              s_axi_wready <= 1'b0;
              tx_state     <= TX_WAIT_RESP;
            end else begin
              tx_beat_cnt  <= tx_beat_cnt + 8'd1;
              tx_state     <= TX_WDATA_SEND;
            end
          end
        end

        TX_WAIT_RESP: begin
          if (tx_noc_valid && noc_tx_ready)
            tx_noc_valid <= 1'b0;
          s_axi_wready  <= 1'b0;
          s_axi_awready <= 1'b0;
          s_axi_arready <= 1'b0;
          if (!tx_noc_valid || noc_tx_ready)
            tx_state <= TX_IDLE;
        end

        default: tx_state <= TX_IDLE;
      endcase
    end
  end

  // ── RX State Machine ──
  typedef enum logic [2:0] {
    RX_IDLE, RX_RCV_BODY, RX_SEND_B, RX_SEND_R
  } rx_state_t;
  rx_state_t rx_state;

  logic [63:0] rx_data_reg;

  // RX drives these intermediate signals
  logic [63:0] rx_noc_flit;
  logic        rx_noc_valid;

  function automatic logic [2:0] flit_ch(input logic [63:0] f);
    return f[43:41];
  endfunction
  function automatic logic [3:0] flit_id(input logic [63:0] f);
    return f[40:37];
  endfunction
  function automatic logic flit_last(input logic [63:0] f);
    return f[32];
  endfunction

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rx_state      <= RX_IDLE;
      noc_rx_ready  <= 1'b0;
      s_axi_bvalid  <= 1'b0;
      s_axi_rvalid  <= 1'b0;
      rx_noc_valid  <= 1'b0;
      rx_noc_flit   <= '0;
    end else begin
      case (rx_state)
        RX_IDLE: begin
          noc_rx_ready <= 1'b1;
          s_axi_bvalid <= 1'b0;
          s_axi_rvalid <= 1'b0;
          rx_noc_valid <= 1'b0;
          if (noc_rx_valid && noc_rx_ready) begin
            noc_rx_ready <= 1'b0;
            case (flit_ch(noc_rx_flit))
              CH_AW: begin
                s_axi_bid    <= flit_id(noc_rx_flit);
                s_axi_bresp  <= 2'b00;
                s_axi_bvalid <= 1'b1;
                rx_noc_flit  <= make_flit(FT_SINGLE, noc_rx_flit[51:48],
                                make_meta(CH_B, flit_id(noc_rx_flit), 8'd0, 1'b1),
                                {30'd0, 2'b00});
                rx_state     <= RX_SEND_B;
              end
              CH_AR: begin
                s_axi_rid    <= flit_id(noc_rx_flit);
                s_axi_rdata  <= 64'hCAFE_BABE_DEAD_BEEF;
                s_axi_rresp  <= 2'b00;
                s_axi_rlast  <= 1'b1;
                s_axi_rvalid <= 1'b1;
                rx_noc_flit  <= make_flit(FT_SINGLE, noc_rx_flit[51:48],
                                make_meta(CH_R, flit_id(noc_rx_flit), 8'd0, 1'b1),
                                32'hCAFE_BABE);
                rx_state     <= RX_SEND_R;
              end
              CH_B: begin
                // Received write response — deliver to AXI4, no NoC response needed
                s_axi_bid    <= flit_id(noc_rx_flit);
                s_axi_bresp  <= noc_rx_flit[1:0];
                s_axi_bvalid <= 1'b1;
                rx_state     <= RX_IDLE;  // NOT RX_SEND_B (it's a response, not a request)
              end
              CH_R: begin
                // Received read data — deliver to AXI4, no NoC response needed
                s_axi_rid    <= flit_id(noc_rx_flit);
                s_axi_rdata  <= {32'd0, noc_rx_flit[31:0]};
                s_axi_rresp  <= 2'b00;
                s_axi_rlast  <= flit_last(noc_rx_flit);
                s_axi_rvalid <= 1'b1;
                rx_data_reg  <= noc_rx_flit;
                if (flit_last(noc_rx_flit))
                  rx_state <= RX_IDLE;
                else
                  rx_state <= RX_RCV_BODY;
              end
              default: rx_state <= RX_IDLE;
            endcase
          end
        end

        RX_RCV_BODY: begin
          noc_rx_ready <= 1'b1;
          if (noc_rx_valid && noc_rx_ready) begin
            s_axi_rdata  <= {noc_rx_flit[31:0], rx_data_reg[31:0]};
            s_axi_rlast  <= flit_last(noc_rx_flit);
            s_axi_rvalid <= 1'b1;
            if (flit_last(noc_rx_flit))
              rx_state <= RX_IDLE;
          end
        end

        RX_SEND_B: begin
          // Drive response flit to NoC (only when TX is idle)
          if (tx_state == TX_IDLE) begin
            rx_noc_valid <= 1'b1;
            if (rx_noc_valid && noc_tx_ready) begin
              rx_noc_valid <= 1'b0;
              if (s_axi_bvalid && s_axi_bready)
                s_axi_bvalid <= 1'b0;
              rx_state <= RX_IDLE;
            end
          end
        end

        RX_SEND_R: begin
          if (tx_state == TX_IDLE) begin
            rx_noc_valid <= 1'b1;
            if (rx_noc_valid && noc_tx_ready) begin
              rx_noc_valid <= 1'b0;
              if (s_axi_rvalid && s_axi_rready)
                s_axi_rvalid <= 1'b0;
              rx_state <= RX_IDLE;
            end
          end
        end

        default: rx_state <= RX_IDLE;
      endcase
    end
  end

  // ── TX/RX Priority Mux: TX drives when active, RX when TX idle ──
  assign noc_tx_flit  = (tx_state != TX_IDLE) ? tx_noc_flit  : rx_noc_flit;
  assign noc_tx_valid = (tx_state != TX_IDLE) ? tx_noc_valid : rx_noc_valid;

endmodule

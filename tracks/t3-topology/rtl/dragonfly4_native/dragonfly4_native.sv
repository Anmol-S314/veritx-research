`default_nettype none

// Exact dragonfly_graph(radix=2, group_count=2): routers 0,1 are group 0,
// routers 2,3 group 1. Local links are 0-1 and 2-3. Canonical global links
// are 0-2 and 1-3, from the source-group mapping (a+src_group)%radix.
// One-entry-per-router single-flit prototype, with endpoint/router IDs equal.
module dragonfly4_native #(
  parameter int DATA_W=32, ID_W=2
)(
  input logic clk, rst,
  input logic [3:0] inject_valid,
  output logic [3:0] inject_ready,
  input logic [3:0][DATA_W-1:0] inject_data,
  input logic [3:0][ID_W-1:0] inject_dest,
  output logic [3:0] eject_valid,
  input logic [3:0] eject_ready,
  output logic [3:0][DATA_W-1:0] eject_data,
  output logic [3:0][ID_W-1:0] eject_dest
);
  logic [3:0] valid_q;
  logic [3:0][DATA_W-1:0] data_q;
  logic [3:0][ID_W-1:0] dest_q;
  logic [3:0] move;
  logic [3:0][1:0] next_hop;

  always_comb begin
    move='0; next_hop='0;
    for (int r=0;r<4;r++) begin
      case (r)
        0: next_hop[r]=(dest_q[r]==2'd1)?2'd1:2'd2;
        1: next_hop[r]=(dest_q[r]==2'd0)?2'd0:2'd3;
        2: next_hop[r]=(dest_q[r]==2'd0)?2'd0:2'd3;
        3: next_hop[r]=(dest_q[r]==2'd1)?2'd1:2'd2;
      endcase
      if (valid_q[r] && dest_q[r]!=ID_W'(r) && !valid_q[next_hop[r]]) move[r]=1'b1;
    end
  end

  // Directed ready/valid transfers use free slots at each edge's destination.

  always_comb begin
    inject_ready = ~valid_q;
    eject_valid = '0;
    eject_data = '0;
    eject_dest = '0;
    for (int r=0; r<4; r++) begin
      if (valid_q[r] && dest_q[r] == ID_W'(r)) begin
        eject_valid[r]=1'b1;
        eject_data[r]=data_q[r];
        eject_dest[r]=dest_q[r];
      end
    end
  end

  always_ff @(posedge clk) begin
    if (rst) begin
      valid_q <= '0;
    end else begin
      for (int r=0; r<4; r++) begin
        if (valid_q[r] && dest_q[r] == ID_W'(r) && eject_ready[r])
          valid_q[r] <= 1'b0;
      end
      // Move only when the next router has a free slot; fields remain stored
      // during backpressure. The checked routes are direct single-edge paths.
      for (int r=0;r<4;r++) if (move[r]) begin
        valid_q[r]<=1'b0;
        valid_q[next_hop[r]]<=1'b1;
        data_q[next_hop[r]]<=data_q[r];
        dest_q[next_hop[r]]<=dest_q[r];
      end
      for (int r=0; r<4; r++) begin
        if (inject_valid[r] && inject_ready[r]) begin
          valid_q[r]<=1'b1;
          data_q[r]<=inject_data[r];
          dest_q[r]<=inject_dest[r];
        end
      end
    end
  end
endmodule

`default_nettype wire

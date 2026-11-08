`timescale 1ns/1ps
`default_nettype none

// BookSim dragonflynew k=2,n=1: 9 groups, 4 routers/group, 2 terminals/router.
// This topology-specific single-flit model follows BookSim's minimal dragonfly_port
// path over the exact group clique/global-link graph. It is not a packet-level
// replacement for BookSim's router/VC implementation.
module dragonflynew_native #(
  parameter int DATA_W = 32,
  parameter int ROUTERS = 36,
  parameter int TERMINALS = 72
) (
  input  logic clk,
  input  logic rst,
  input  logic [TERMINALS-1:0] inject_valid,
  output logic [TERMINALS-1:0] inject_ready,
  input  logic [TERMINALS-1:0][DATA_W-1:0] inject_data,
  input  logic [TERMINALS-1:0][6:0] inject_dest,
  output logic [TERMINALS-1:0] eject_valid,
  input  logic [TERMINALS-1:0] eject_ready,
  output logic [TERMINALS-1:0][DATA_W-1:0] eject_data,
  output logic [TERMINALS-1:0][6:0] eject_dest
);
  localparam int GROUPS = 9;
  localparam int ROUTERS_PER_GROUP = 4;
  localparam int TERMINALS_PER_ROUTER = 2;

  logic [ROUTERS-1:0] valid_q;
  logic [ROUTERS-1:0][DATA_W-1:0] data_q;
  logic [ROUTERS-1:0][6:0] dest_q;
  logic [ROUTERS-1:0][5:0] next_router;
  logic [ROUTERS-1:0] move;
  logic [ROUTERS-1:0] ejected;
  logic [ROUTERS-1:0] incoming_reserved;

  function automatic int route_next(input int router_id, input int terminal_dest);
    int src_group;
    int dst_group;
    int dst_router;
    int rank;
    int gateway;
    begin
      src_group = router_id / ROUTERS_PER_GROUP;
      dst_group = terminal_dest / 8;
      dst_router = terminal_dest / TERMINALS_PER_ROUTER;
      if (src_group == dst_group) begin
        route_next = dst_router;
      end else if (router_id != (src_group * ROUTERS_PER_GROUP +
                     ((dst_group < src_group ? dst_group : dst_group - 1) / 2))) begin
        rank = dst_group < src_group ? dst_group : dst_group - 1;
        gateway = src_group * ROUTERS_PER_GROUP + rank / 2;
        route_next = gateway;
      end else begin
        rank = src_group < dst_group ? src_group : src_group - 1;
        gateway = dst_group * ROUTERS_PER_GROUP + rank / 2;
        if (router_id != gateway)
          route_next = gateway;
        else
          route_next = dst_router;
      end
    end
  endfunction

  always_comb begin : route_and_arbitrate
    logic [ROUTERS-1:0] reserved;
    int target;
    int terminal;
    target = 0;
    terminal = 0;
    move = '0;
    ejected = '0;
    incoming_reserved = '0;
    reserved = '0;
    next_router = '0;
    inject_ready = '0;
    eject_valid = '0;
    eject_data = '0;
    eject_dest = '0;

    for (int r = 0; r < ROUTERS; r++) begin
      if (valid_q[r]) begin
        terminal = int'(dest_q[r]);
        if ((terminal / TERMINALS_PER_ROUTER) == r) begin
          ejected[r] = 1'b1;
          eject_valid[terminal] = 1'b1;
          eject_data[terminal] = data_q[r];
          eject_dest[terminal] = dest_q[r];
        end else begin
          target = route_next(r, terminal);
          next_router[r] = 6'(target);
          if (!valid_q[target] && !reserved[target]) begin
            move[r] = 1'b1;
            reserved[target] = 1'b1;
            incoming_reserved[target] = 1'b1;
          end
        end
      end
    end

    // One injection grant per router. Terminal 2*r has priority if both are valid.
    for (int r = 0; r < ROUTERS; r++) begin
      if (!valid_q[r] && !incoming_reserved[r]) begin
        inject_ready[2*r] = 1'b1;
        inject_ready[2*r+1] = !inject_valid[2*r];
      end
    end
  end

  always_ff @(posedge clk) begin
    if (rst) begin
      valid_q <= '0;
    end else begin
      for (int r = 0; r < ROUTERS; r++) begin
        int terminal;
        terminal = int'(dest_q[r]);
        if (valid_q[r] && ejected[r] && eject_ready[terminal])
          valid_q[r] <= 1'b0;
        if (move[r])
          valid_q[r] <= 1'b0;
      end
      for (int r = 0; r < ROUTERS; r++) begin
        if (move[r]) begin
          valid_q[next_router[r]] <= 1'b1;
          data_q[next_router[r]] <= data_q[r];
          dest_q[next_router[r]] <= dest_q[r];
        end
      end
      for (int r = 0; r < ROUTERS; r++) begin
        if (inject_valid[2*r] && inject_ready[2*r]) begin
          valid_q[r] <= 1'b1;
          data_q[r] <= inject_data[2*r];
          dest_q[r] <= inject_dest[2*r];
        end else if (inject_valid[2*r+1] && inject_ready[2*r+1]) begin
          valid_q[r] <= 1'b1;
          data_q[r] <= inject_data[2*r+1];
          dest_q[r] <= inject_dest[2*r+1];
        end
      end
    end
  end

  initial begin
    if (ROUTERS != GROUPS * ROUTERS_PER_GROUP ||
        TERMINALS != ROUTERS * TERMINALS_PER_ROUTER)
      $error("dragonflynew_native is fixed to BookSim k=2,n=1: 36 routers/72 terminals");
  end
endmodule

`default_nettype wire

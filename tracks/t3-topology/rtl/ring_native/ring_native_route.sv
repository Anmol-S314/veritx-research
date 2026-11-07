`default_nettype none

// Native 1-D ring route decision, matching ring_net.py and ring_projection.py.
// Port 0 is always +1, port 1 always -1. VC half is flow-stable and is
// supplied by the source/destination comparison on every hop.
module ring_native_route #(
  parameter int N = 64,
  parameter int ID_W = $clog2(N)
) (
  input  logic [ID_W-1:0] router_id,
  input  logic [ID_W-1:0] destination,
  input  logic [ID_W-1:0] source,
  input  logic           tie_choice, // 0: +1 face, 1: -1 face at antipode
  output logic           eject,
  output logic [1:0]     legal_ports,
  output logic           out_port,
  output logic           vc_half
);
  integer forward_distance;
  always_comb begin
    eject = (router_id == destination);
    forward_distance = (int'(destination) + N - int'(router_id)) % N;
    legal_ports = 2'b00;
    out_port = 1'b0;
    vc_half = (source > destination);
    if (!eject) begin
      if ((N % 2 == 0) && (forward_distance == N/2)) begin
        legal_ports = 2'b11;
        out_port = tie_choice;
      end else if (forward_distance < (N+1)/2) begin
        legal_ports = 2'b01;
        out_port = 1'b0;
      end else begin
        legal_ports = 2'b10;
        out_port = 1'b1;
      end
    end
  end
endmodule

`default_nettype wire

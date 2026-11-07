`timescale 1ns/1ps
module tb_ring_native_fabric;
  localparam int N=64;
  logic clk=0, rst=1;
  logic [N-1:0] inject_valid, inject_ready, inject_vc;
  logic [N-1:0][31:0] inject_data;
  logic [N-1:0][5:0] inject_dest;
  logic [N-1:0] eject_valid, eject_ready;
  logic [N-1:0][31:0] eject_data;
  int next_dest [N];
  bit seen [N][N];
  int received=0;
  int cycles=0;
  int accepted=0;
  int source_id, destination_id;
  wire [2:0][1:0] valid_debug [N];
  wire [2:0][1:0][5:0] dest_debug [N];

  always #5 clk=~clk;

  ring_native_fabric #(.N(N), .DATA_W(32), .ID_W(6)) dut (.*);

  for (genvar node=0;node<N;node++) begin: debug_taps
    assign valid_debug[node]=dut.routers[node].u_router.valid_q;
    assign dest_debug[node]=dut.routers[node].u_router.dest_q;
  end

  initial begin
    inject_valid='0;
    inject_data='0;
    inject_dest='0;
    inject_vc='0;
    eject_ready='0;
    for (int s=0;s<N;s++) next_dest[s]=0;
    repeat (3) @(negedge clk);
    rst=0;

    while (received < N*N && cycles < 10000) begin
      @(negedge clk);
      cycles++;
      inject_valid='0;
      for (int s=0;s<N;s++) begin
        if (next_dest[s] < N) begin
          inject_valid[s]=1'b1;
          inject_dest[s]=next_dest[s][5:0];
          inject_vc[s]=(s > next_dest[s]);
          inject_data[s]={s[5:0], next_dest[s][5:0], 20'(s*N+next_dest[s])};
        end
      end
      // Deterministic staggered backpressure at every endpoint.
      for (int t=0;t<N;t++) eject_ready[t]=(((cycles*13+t*7)%11)!=0);
      #1;
      for (int s=0;s<N;s++) begin
        if (inject_valid[s] && inject_ready[s]) begin
          next_dest[s]++;
          accepted++;
        end
      end
      for (int t=0;t<N;t++) begin
        if (eject_valid[t] && eject_ready[t]) begin
          source_id=eject_data[t][31:26];
          destination_id=eject_data[t][25:20];
          if (destination_id != t) $fatal(1,"wrong terminal: src=%0d encoded-dst=%0d actual=%0d",source_id,destination_id,t);
          if (source_id >= N || seen[source_id][destination_id]) $fatal(1,"duplicate/invalid packet src=%0d dst=%0d",source_id,destination_id);
          if (eject_data[t][19:0] != (source_id*N+destination_id)) $fatal(1,"payload corruption");
          seen[source_id][destination_id]=1'b1;
          received++;
        end
      end
      if (cycles%10000==0) $display("PROGRESS cycles=%0d accepted=%0d received=%0d",cycles,accepted,received);
      @(posedge clk);
    end

    if (received != N*N || accepted != N*N) begin
      $display("DEADLOCK-DUMP accepted=%0d received=%0d",accepted,received);
      for (int node=0;node<N;node++) begin
        for (int in_port=0;in_port<3;in_port++) begin
          for (int vc=0;vc<2;vc++) begin
            if (valid_debug[node][in_port][vc]) begin
              int dst, forward, port, next_node, next_input;
              dst=dest_debug[node][in_port][vc];
              forward=(dst-node+N)%N;
              if (dst==node) port=2;
              else if (forward==N/2) port=(vc!=0)?1:0;
              else if (forward<N/2) port=0;
              else port=1;
              next_node=(port==0)?(node+1)%N:(node+N-1)%N;
              next_input=(port==0)?0:1;
              $display("HEAD node=%0d in=%0d vc=%0d dest=%0d out=%0d downstream_full=%b",node,in_port,vc,dst,port,
                (port==2)?1'b0:valid_debug[next_node][next_input][vc]);
            end
          end
        end
      end
      $fatal(1,"did not drain received=%0d accepted=%0d cycles=%0d",received,accepted,cycles);
    end
    for (int s=0;s<N;s++) for (int d=0;d<N;d++) if (!seen[s][d]) $fatal(1,"missing packet src=%0d dst=%0d",s,d);
    $display("PASS ring_native packets=%0d accepted=%0d cycles=%0d destinations=all-pairs wrap=covered vc=two-classes backpressure=deterministic drained",received,accepted,cycles);
    $finish;
  end

  initial begin
    #3000000;
    $fatal(1,"simulation timeout");
  end
endmodule

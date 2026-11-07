`timescale 1ns/1ps
`default_nettype none
module tb_tree4_native;
  logic clk=0, rst=1;
  always #5 clk=~clk;
  logic [63:0] inject_valid,inject_ready,eject_valid,eject_ready;
  logic [63:0][31:0] inject_data,eject_data;
  logic [63:0][5:0] inject_dest;
  tree4_native_fabric dut(.*);
  bit [63:0][63:0] delivered;
  bit [63:0] sent;
  int accepted=0,received=0,cycles=0;
  int unsigned payload[0:63][0:63];

  always @(negedge clk) if (!rst)
    for (int t=0;t<64;t++) eject_ready[t]=((cycles+t*3)%11 != 0);

  always @(posedge clk) if (!rst) begin
    cycles++;
    for (int t=0;t<64;t++) if (eject_valid[t] && eject_ready[t]) begin
      int src,dst;
      src=int'(eject_data[t][31:16]); dst=int'(eject_data[t][15:0]);
      if (src>=64 || dst!=t) $fatal(1,"wrong destination payload src=%0d dst=%0d seat=%0d",src,dst,t);
      if (delivered[src][dst]) $fatal(1,"duplicate delivery %0d->%0d",src,dst);
      if (payload[src][dst]!=eject_data[t]) $fatal(1,"payload corruption");
      delivered[src][dst]=1; received++;
    end
  end

  function automatic int expected_route(int r,int t,int inport);
    int level,pos,group_id,leaf_id;
    begin
      level=(r<4)?0:((r<12)?1:2);
      pos=(level==0)?r:((level==1)?r-4:r-12);
      group_id=t/16; leaf_id=t/4;
      if(level==0) expected_route=2*group_id+((inport+t)%2);
      else if(level==1) expected_route=(group_id==pos/2)?((t/4)-4*(pos/2)):(4+((inport+t)%4));
      else expected_route=(leaf_id==pos)?t%4:(4+((inport+t)%2));
    end
  endfunction

  task automatic tick;
    @(posedge clk); #1; cycles++;
  endtask

  initial begin
    inject_valid='0; inject_ready='0; inject_data='0; inject_dest='0; eject_ready='0;
    repeat(3) tick(); rst=0;
    // All 28*64 pairs. Check exact legal choice union at every visited router.
    for(int s=0;s<64;s++) for(int d=0;d<64;d++) begin
      int router,leaf,group_id,port,next_router,source_leaf,source_mid;
      router=12+s/4; source_leaf=s/4; source_mid=4+2*(source_leaf/4);
      leaf=d/4; group_id=d/16;
      for(int hop=0;hop<6;hop++) begin
        int level,pos,expected;
        level=(router<4)?0:((router<12)?1:2);
        pos=(level==0)?router:((level==1)?router-4:router-12);
        expected=expected_route(router,d,(hop==0)?s%4:(router<4?4+(router/2):router<12?4+((router-4)/2):4+(router-12)%2));
        if(level==0) begin
          if(expected<2*group_id || expected>2*group_id+1) $fatal(1,"root choice outside union");
          next_router=4+expected;
        end else if(level==1) begin
          if(group_id==pos/2) begin
            if(expected!=(d/4-4*(pos/2))) $fatal(1,"middle down route mismatch");
            next_router=12+4*(pos/2)+expected;
          end else begin
            if(expected<4 || expected>7) $fatal(1,"middle upward choice outside four-root union");
            next_router=expected-4;
          end
        end else if(leaf==pos) begin
          if(expected!=d%4) $fatal(1,"leaf seat mismatch");
          next_router=-1;
        end else begin
          if(expected<4 || expected>5) $fatal(1,"leaf parent outside union");
          next_router=4+2*(pos/4)+(expected-4);
        end
        if(next_router==-1) begin
          if(4*pos+expected!=d) $fatal(1,"wrong terminal ejection");
          break;
        end
        if(hop==5) $fatal(1,"route did not terminate %0d->%0d",s,d);
        router=next_router;
      end
      if(source_leaf<0 || source_mid<4) $fatal(1,"unreachable");
    end
    $display("ROUTE PASS routers=28 terminals=64 pairs=1792 legal_union=checked");

    // Drive one uniquely tagged packet for each of 4096 terminal pairs.
    for(int s=0;s<64;s++) for(int d=0;d<64;d++) begin
      inject_valid[s]=1; inject_dest[s]=d; inject_data[s]=(s<<16)|d; payload[s][d]=(s<<16)|d;
      begin
        int wait_cycles;
        bit handshake;
        wait_cycles=0;
        handshake=0;
        while(!handshake && wait_cycles<5000) begin
          @(posedge clk);
          if (inject_ready[s]) begin
            accepted++;
            handshake=1;
          end
          @(negedge clk);
          wait_cycles++;
        end
        if(!handshake) $fatal(1,"injection timeout source=%0d dest=%0d accepted=%0d received=%0d",s,d,accepted,received);
      end
      inject_valid[s]=0;
    end
    eject_ready='1;
    while(received<accepted && cycles<50000) begin
      tick();
    end
    if(received!=4096) $fatal(1,"conservation failure accepted=%0d received=%0d",accepted,received);
    for(int s=0;s<64;s++) for(int d=0;d<64;d++) if(!delivered[s][d]) $fatal(1,"missing pair %0d->%0d",s,d);
    repeat(20) begin
      tick();
      if(|eject_valid) $fatal(1,"fabric not drained");
    end
    $display("TRAFFIC PASS packets=%0d delivered=%0d wrong=0 duplicate=0 outstanding=0 cycles=%0d",accepted,received,cycles);
    $finish;
  end
endmodule
`default_nettype wire

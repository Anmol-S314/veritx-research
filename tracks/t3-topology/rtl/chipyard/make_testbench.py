"""Generate a self-checking Verilator testbench from the frozen compiled contract."""
import json
from pathlib import Path
import sys


def render(contract):
    endpoints = contract['endpoint_routers']
    n = len(endpoints)
    packet = contract['packet_format']
    width = packet['flit_width_bits']
    fields = {f['name']: (f['lsb'], f['width']) for f in packet['fields']}
    dest_lsb, dest_width = fields['destination_endpoint']
    src_lsb, _ = fields['source_endpoint']
    type_lsb, _ = fields['flit_type']
    vc_lsb, vc_width = fields['vc_id']
    max_packets = n*n + 4*n + 1
    ports = ['.clock(clk)', '.reset(reset)']
    for i in range(n):
        ports += [f'.io_ingress_{i}_valid(in_valid[{i}])', f'.io_ingress_{i}_ready(in_ready[{i}])',
                  f'.io_ingress_{i}_bits(in_bits[{i}])', f'.io_egress_{i}_valid(out_valid[{i}])',
                  f'.io_egress_{i}_ready(out_ready[{i}])', f'.io_egress_{i}_bits(out_bits[{i}])']
    final_vc = []
    for src in range(n):
        row = []
        for dst in range(n):
            cur, v = endpoints[src], 0
            while cur != endpoints[dst]:
                _, cur, v = contract['route_table'][cur][endpoints[dst]]
            row.append(v)
        final_vc.append(row)
    init = '\n'.join(f'    final_vc[{s}][{d}] = {v};' for s, row in enumerate(final_vc) for d, v in enumerate(row))
    return f'''`timescale 1ns/1ps
module tb_compiled_gec;
  localparam int N={n}, W={width}, MAX={max_packets};
  logic clk=0, reset=1;
  always #5 clk=~clk;
  logic [N-1:0] in_valid='0, in_ready, out_valid, out_ready='0;
  logic [W-1:0] in_bits [N], out_bits [N];
  logic [W-1:0] expected [MAX];
  bit admitted [MAX], seen [MAX];
  int expected_dest [MAX], final_vc [N][N];
  int accepted=0, delivered=0, stall_checks=0;
  CompiledGecPreview dut({','.join(ports)});
  function automatic logic [W-1:0] packet(input int s, d, id);
    logic [W-1:0] f;
    f=W'(id);
    f[{src_lsb} +: {fields['source_endpoint'][1]}]={fields['source_endpoint'][1]}'(s);
    f[{dest_lsb} +: {dest_width}]={dest_width}'(d);
    f[{type_lsb} +: 2]=2'd3;
    return f;
  endfunction
  task automatic register_packet(input int s, d, id);
    expected[id]=packet(s,d,id);
    expected[id][{vc_lsb} +: {vc_width}]={vc_width}'(final_vc[s][d]);
    expected_dest[id]=d;
  endtask
  always @(posedge clk) if (!reset) begin
    for (int e=0;e<N;e++) begin
      if (in_valid[e] && in_ready[e]) begin
        int id;
        id=int'(in_bits[e][31:0]);
        if (id<=0 || id>=MAX || admitted[id]) $fatal(1,"bad/duplicate admission id=%0d",id);
        admitted[id]=1;
        accepted++;
      end
      if (out_valid[e] && out_ready[e]) begin
        int id;
        id=int'(out_bits[e][31:0]);
        if (id<=0 || id>=MAX) $fatal(1,"bad output id=%0d",id);
        if (!admitted[id] || seen[id]) $fatal(1,"lost association/duplicate id=%0d",id);
        if (expected_dest[id]!=e || out_bits[e]!==expected[id])
          $fatal(1,"payload/VC/destination mismatch id=%0d endpoint=%0d got=%h expected=%h",id,e,out_bits[e],expected[id]);
        seen[id]=1;
        delivered++;
      end
    end
  end
  task automatic drain(input int target);
    int cycles;
    cycles=0;
    while (delivered<target && cycles<20000) begin
      @(negedge clk); cycles++;
    end
    if (delivered!=target) $fatal(1,"drain timeout accepted=%0d delivered=%0d target=%0d",accepted,delivered,target);
  endtask
  initial begin
    for(int e=0;e<N;e++) in_bits[e]='0;
{init}
    repeat(4) @(negedge clk);
    reset=0; out_ready='1;
    for(int s=0;s<N;s++) for(int d=0;d<N;d++) begin
      int id, cycles;
      id=1+s*N+d;
      register_packet(s,d,id);
      in_valid[s]=1; in_bits[s]=packet(s,d,id);
      cycles=0;
      do begin @(posedge clk); cycles++; end while (!in_ready[s] && cycles<1000);
      if (!in_ready[s]) $fatal(1,"injection timeout");
      @(negedge clk); in_valid[s]=0;
      drain(id);
    end
    // Every source targets one egress concurrently, then the sink stalls.
    out_ready='0;
    for(int round=0;round<4;round++) begin
      bit [N-1:0] pending;
      int cycles;
      pending='1;
      for(int s=0;s<N;s++) begin
        int id;
        id=1+N*N+round*N+s;
        register_packet(s,N-1,id);
        in_valid[s]=1; in_bits[s]=packet(s,N-1,id);
      end
      cycles=0;
      while(pending!='0 && cycles<2000) begin
        @(posedge clk);
        for(int s=0;s<N;s++) if(in_valid[s] && in_ready[s]) pending[s]=0;
        @(negedge clk); in_valid=pending; cycles++;
      end
      if(pending!='0) $fatal(1,"concurrent injection timeout");
    end
    repeat(100) @(negedge clk);
    if(!out_valid[N-1]) $fatal(1,"stalled sink never received a flit");
    begin
      logic [W-1:0] held;
      held=out_bits[N-1];
      repeat(8) begin
        @(negedge clk);
        if(!out_valid[N-1] || out_bits[N-1]!==held) $fatal(1,"unstable stalled output");
        stall_checks++;
      end
    end
    out_ready='1;
    drain(N*N+4*N);
    repeat(20) @(negedge clk);
    if(out_valid!='0 || accepted!=delivered) $fatal(1,"conservation/drain failure");
    $display("PASS compiled_gec endpoints=%0d all_pairs=%0d accepted=%0d delivered=%0d stall_checks=%0d drained=1",N,N*N,accepted,delivered,stall_checks);
    begin
      int report;
      report=$fopen("simulation-pass.txt","w");
      if(!report) $fatal(1,"cannot write simulation report");
      $fdisplay(report,"PASS compiled_gec endpoints=%0d all_pairs=%0d accepted=%0d delivered=%0d stall_checks=%0d drained=1",N,N*N,accepted,delivered,stall_checks);
      $fclose(report);
    end
    $finish;
  end
  initial begin #20000000; $fatal(1,"watchdog"); end
endmodule
'''


if __name__ == '__main__':
    contract = json.loads(Path(sys.argv[1]).read_text())
    Path(sys.argv[2]).write_text(render(contract))

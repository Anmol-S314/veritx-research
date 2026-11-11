#!/usr/bin/env python3
"""Prepare an actual-cell, 64-router Icarus smoke witness without changing inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def testbench(header):
    ports = re.findall(r'^\s*(input|output)\s+(\[\d+:\d+\])?\s*(\w+)\b', header, re.M)
    names = {name for _, _, name in ports}
    required = {'clock', 'reset'}
    for i in range(64):
        for prefix, fields in [('ingress', ['ready', 'valid', 'bits_head', 'bits_tail', 'bits_route_tag', 'bits_payload', 'bits_egress_id']),
                               ('egress', ['ready', 'valid', 'bits_head', 'bits_tail', 'bits_route_tag', 'bits_payload', 'bits_ingress_id'])]:
            required.update(f'io_{prefix}_{i}_flit_{field}' for field in fields)
    if names != required or len(ports) != len(required):
        raise ValueError('full actual top terminal interface mismatch')
    lines = ['`timescale 1ns/1ps', 'module tb_srota_actual;']
    lines += [f'{"reg" if d == "input" else "wire"} {w} {n};' for d, w, n in ports]
    lines += ['CandidateNoCTop dut(' + ','.join(f'.{n}({n})' for _, _, n in ports) + ');',
              'always #5 clock=~clock;', 'integer age; integer accepted=0; integer delivered=0;',
              'reg [127:0] held_payload; reg [1:0] held_tag;',
              'always @(posedge clock) if (!reset) begin',
              'if (io_ingress_0_flit_valid && io_ingress_0_flit_ready) accepted <= accepted+1;']
    for i in range(64):
        lines += [f'if (io_egress_{i}_flit_valid && io_egress_{i}_flit_ready) begin']
        if i != 63:
            lines += [f'$fatal(1,"unexpected sink {i}");']
        else:
            lines += ['delivered <= delivered+1;',
                      "if (io_egress_63_flit_bits_payload !== 128'h0123456789abcdef_fedcba9876543210 || io_egress_63_flit_bits_head !== 1'b1 || io_egress_63_flit_bits_tail !== 1'b1 || io_egress_63_flit_bits_ingress_id !== 6'd0) $fatal(1,\"packet corruption\");"]
        lines += ['end']
    lines += ['end', 'initial begin']
    lines += [f'{n}=0;' for d, _, n in ports if d == 'input']
    lines += [f'io_egress_{i}_flit_ready=1;' for i in range(63)]
    lines += ['reset=1; repeat(8) @(negedge clock); reset=0; repeat(32) @(negedge clock);',
              "io_ingress_0_flit_bits_head=1; io_ingress_0_flit_bits_tail=1; io_ingress_0_flit_bits_egress_id=63; io_ingress_0_flit_bits_payload=128'h0123456789abcdef_fedcba9876543210; io_ingress_0_flit_valid=1;",
              'age=0; do begin @(posedge clock); age=age+1; if(age>1000) $fatal(1,"ingress timeout"); end while(io_ingress_0_flit_ready !== 1\'b1);',
              '@(negedge clock); io_ingress_0_flit_valid=0; age=0;',
              'while(io_egress_63_flit_valid !== 1\'b1) begin @(negedge clock); age=age+1; if(age>10000) $fatal(1,"egress timeout"); end',
              'held_payload=io_egress_63_flit_bits_payload; held_tag=io_egress_63_flit_bits_route_tag;',
              'repeat(5) begin @(negedge clock); if(io_egress_63_flit_valid !== 1\'b1 || io_egress_63_flit_bits_payload !== held_payload || io_egress_63_flit_bits_route_tag !== held_tag || io_egress_63_flit_bits_head !== 1\'b1 || io_egress_63_flit_bits_tail !== 1\'b1 || io_egress_63_flit_bits_ingress_id !== 6\'d0) $fatal(1,"stall stability"); end',
              'io_egress_63_flit_ready=1; repeat(64) @(negedge clock);',
              'if(accepted!=1 || delivered!=1) $fatal(1,"conservation accepted=%0d delivered=%0d",accepted,delivered);',
              '$display("SROTA_ACTUAL_64_ROUTER_SMOKE_PASS accepted=1 delivered=1 stalls=5"); $finish;',
              'end', 'initial begin #200000; $fatal(1,"test deadline"); end', 'endmodule']
    return '\n'.join(lines) + '\n'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', type=Path)
    p.add_argument('corrected_top', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    original = a.root / 'top/CandidateNoCTop.v'
    assembled = a.root / 'assembled-v3/CandidateNoCTop.v'
    raw, corrected, joined = original.read_bytes(), a.corrected_top.read_bytes(), assembled.read_bytes()
    if not joined.startswith(raw + b'\n'):
        raise ValueError('assembled top does not start with pinned original top')
    text = corrected.decode()
    start = text.index('module CandidateNoCTop(')
    tb = testbench(text[start:text.index(');', start) + 2])
    a.output.mkdir(parents=True, exist_ok=False)
    rtl = a.output / 'CandidateNoCTop.v'
    rtl.write_bytes(corrected + joined[len(raw):])
    tb_path = a.output / 'tb_srota_actual.sv'
    tb_path.write_text(tb)
    record = {'qualified': False, 'scope': 'one packet with stalls in actual full 64-router design; not workload qualification',
              'inputs': {str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in [original, a.corrected_top, assembled]},
              'outputs': {str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in [rtl, tb_path]}}
    (a.output / 'input-manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    print('actual_router_cells=64 terminal_ports=898 output=' + str(a.output))


if __name__ == '__main__':
    main()

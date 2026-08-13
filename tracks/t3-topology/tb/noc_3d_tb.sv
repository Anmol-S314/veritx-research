`timescale 1ns/1ps

// VeritX Research — 3D NoC Verilator Testbench (noc_3d_tb.sv)
// Empirically measures cycle-by-cycle latencies for 3D TSV vertical vs 2D horizontal links

import noc_3d_pkg::*;

module noc_3d_tb;

  logic clk = 1'b0;
  always #5 clk = ~clk;
  logic rst_n = 1'b0;

  // 3D Mesh Wiring across 4x4x2 (32 nodes)
  link_f_t inject_flit  [Z_DIM][Y_DIM][X_DIM];
  link_c_t eject_credit [Z_DIM][Y_DIM][X_DIM];
  link_f_t eject_flit   [Z_DIM][Y_DIM][X_DIM];
  link_c_t inject_credit[Z_DIM][Y_DIM][X_DIM];

  mesh_3d #(.VCS(1)) u_mesh_3d (
    .clk(clk),
    .rst_n(rst_n),
    .inject_flit(inject_flit),
    .eject_credit(eject_credit),
    .eject_flit(eject_flit),
    .inject_credit(inject_credit)
  );

  int tick_cnt = 0;
  always_ff @(posedge clk) begin
    tick_cnt <= tick_cnt + 1;
  end

  // Tracking measurements
  int packets_sent = 0;
  int packets_received = 0;

  initial begin
    // Clear inputs
    for (int z = 0; z < Z_DIM; z++) begin
      for (int y = 0; y < Y_DIM; y++) begin
        for (int x = 0; x < X_DIM; x++) begin
          inject_flit[z][y][x] <= '0;
          eject_credit[z][y][x] <= '0;
        end
      end
    end

    // Reset sequence
    #20;
    rst_n = 1'b1;
    #20;

    $display("=== 3D NoC EMPIRICAL MEASUREMENT RUN ===");

    // Test 1: Inject 3D Vertical TSV Packet from Node (0,0,0) to Node (0,0,1)
    $display("[T=%0d] Injecting 3D Vertical TSV packet: Node (0,0,0) -> Node (0,0,1) [Target Node ID 16]", tick_cnt);
    inject_flit[0][0][0].valid <= 1'b1;
    inject_flit[0][0][0].flit.head <= 1'b1;
    inject_flit[0][0][0].flit.tail <= 1'b1;
    inject_flit[0][0][0].flit.src <= 8'd0;   // (0,0,0)
    inject_flit[0][0][0].flit.dst <= 8'd16;  // (0,0,1) = 16
    inject_flit[0][0][0].flit.pid <= 16'h1001;
    inject_flit[0][0][0].flit.itime <= tick_cnt;
    packets_sent++;

    #10;
    inject_flit[0][0][0].valid <= 1'b0;

    // Wait for ejection at Node (0,0,1)
    while (packets_received < 1 && tick_cnt < 200) begin
      #10;
      if (eject_flit[1][0][0].valid) begin
        int lat = tick_cnt - eject_flit[1][0][0].flit.itime;
        $display("[T=%0d] SUCCESS: 3D Vertical TSV Packet Ejected at Node (0,0,1)! Latency = %0d cycles (PID=0x%0h)",
                 tick_cnt, lat, eject_flit[1][0][0].flit.pid);
        packets_received++;
        eject_credit[1][0][0].valid <= 1'b1;
        #10;
        eject_credit[1][0][0].valid <= 1'b0;
      end
    end

    // Test 2: Inject 3D Diagonal Multi-hop Packet from Node (0,0,0) to Node (3,3,1)
    $display("\n[T=%0d] Injecting 3D Multi-Hop Diagonal packet: Node (0,0,0) -> Node (3,3,1) [Target Node ID 31]", tick_cnt);
    inject_flit[0][0][0].valid <= 1'b1;
    inject_flit[0][0][0].flit.head <= 1'b1;
    inject_flit[0][0][0].flit.tail <= 1'b1;
    inject_flit[0][0][0].flit.src <= 8'd0;   // (0,0,0)
    inject_flit[0][0][0].flit.dst <= 8'd31;  // (3,3,1) = 1*16 + 3*4 + 3 = 31
    inject_flit[0][0][0].flit.pid <= 16'h2002;
    inject_flit[0][0][0].flit.itime <= tick_cnt;
    packets_sent++;

    #10;
    inject_flit[0][0][0].valid <= 1'b0;

    // Wait for ejection at Node (3,3,1)
    while (packets_received < 2 && tick_cnt < 500) begin
      #10;
      if (eject_flit[1][3][3].valid) begin
        int lat = tick_cnt - eject_flit[1][3][3].flit.itime;
        $display("[T=%0d] SUCCESS: 3D Multi-Hop Diagonal Packet Ejected at Node (3,3,1)! Latency = %0d cycles (PID=0x%0h)",
                 tick_cnt, lat, eject_flit[1][3][3].flit.pid);
        packets_received++;
        eject_credit[1][3][3].valid <= 1'b1;
        #10;
        eject_credit[1][3][3].valid <= 1'b0;
      end
    end

    if (packets_received == 2) begin
      $display("\n=== 3D NoC HARDWARE VERIFICATION PASSED (ALL 3D FLITS RETIRED) ===");
      $finish;
    end else begin
      $display("\n❌ ERROR: 3D NoC Packet delivery timed out!");
      $fatal;
    end
  end

endmodule

`timescale 1ns/1ps

// Gate R0 selfchecks (PLAN.md / PITFALLS.md discipline):
//   S1 zero-traffic event sanity (no injection/ejection with generators off)
//   S2 single-packet calibration vs the BookSim cycle model:
//        latency(d) = 7 + 5d  (local loopback 7, each network hop +5)
//   S3 3-flit burst cadence (flits eject 1/cycle)
//   S4 LFSR smoke: bursts + control, everything drains, latency sanity
// Failure => $fatal. Pass => "GATE R0: ALL CHECKS PASSED".

module noc_tb;
  import noc_pkg::*;

  // Parameters (overridable via verilator -G for the Gate R1 sweep grid:
  // VCS x {1,2,4} on the 8x8 mesh; defaults keep the R0 selfchecks at 4x4/4VC).
  parameter int VCS   = 4;
  parameter int X_DIM = 4;
  parameter int Y_DIM = 4;
  // 2-die bridge mode: two X_DIM x Y_DIM meshes joined by one bridge link at
  // (Y_DIM-1, BRIDGE_COL) -> (BRIDGE_ROW, BRIDGE_COL). Nodes 0..N-1 = die A,
  // N..2N-1 = die B (die = index / N). Injection arrays gain a die dimension.
  parameter int TWO_DIE    = 0;
  parameter int BRIDGE_COL = 0;
  parameter int BRIDGE_ROW = 0;
  localparam int N     = X_DIM * Y_DIM;
  localparam int ND    = TWO_DIE ? 2 : 1;

  logic clk = 1'b0;
  always #5 clk = ~clk;
  logic rst_n = 1'b0;

  // mesh wiring
  link_f_t inj  [ND][Y_DIM][X_DIM];
  link_c_t injc [ND][Y_DIM][X_DIM];
  link_c_t injce [ND][Y_DIM][X_DIM];
  link_f_t ej   [ND][Y_DIM][X_DIM];
  link_c_t ejc  [ND][Y_DIM][X_DIM];
  logic [31:0] rpop [ND][Y_DIM][X_DIM][NUM_PORTS];
  logic [31:0] rrecv [ND][Y_DIM][X_DIM][NUM_PORTS];
  dbg_router_t rdbg [ND][Y_DIM][X_DIM];

  generate
    if (TWO_DIE) begin : gen_2die
      noc_2die #(.VCS(VCS), .X_DIM(X_DIM), .Y_DIM(Y_DIM),
                 .BRIDGE_COL(BRIDGE_COL), .BRIDGE_ROW(BRIDGE_ROW)) u_noc (
        .clk(clk), .rst_n(rst_n),
        .inject(inj), .inject_credit(injc), .inject_credit_early(injce),
        .eject(ej), .eject_credit(ejc)
      );
    end else begin : gen_mesh
      noc_mesh #(.VCS(VCS), .X_DIM(X_DIM), .Y_DIM(Y_DIM)) u_mesh (
        .clk(clk), .rst_n(rst_n),
        .inject(inj[0]), .inject_credit(injc[0]), .inject_credit_early(injce[0]),
        .eject(ej[0]), .eject_credit(ejc[0]),
        .router_pop(rpop[0]),
        .router_recv(rrecv[0]),
        .router_dbg(rdbg[0])
      );
    end
  endgenerate

  // per-node NIC control + counters (ND*N nodes in 2-die mode)
  logic [1:0]  gmode[ND * N];
  logic [31:0] blen[ND * N], r0[ND * N], r1[ND * N], sd[ND * N];
  logic       tw[ND * N];
  logic [10:0] ta[ND * N];
  logic [63:0] td[ND * N];
  logic [31:0] tck[ND * N], injc_[ND * N], ejc_[ND * N];
  logic [31:0] lsum[ND * N][4], lcnt[ND * N][4];
  logic [63:0] dbg_trace0[ND * N];
  logic [31:0] dbg_tptr[ND * N];
  logic        dbg_pending[ND * N];

`ifdef R1_MODE
  // Gate R1: per-NIC trace BRAM contents loaded from hex files (trace_n%d.hex),
  // one entry per packet start, format {cycle[63:32], cl[31:24], dst[23:16], size[15:0]}.
  // The eject stream is dumped to rtl_flits.txt as "atime cl src dst pid itime".
  // T_DEPTH is a build-time parameter (default 2048 = the full-cell depth).
  // Small cells override with -GT_DEPTH=<n> to skip the ND*N*T_DEPTH pump —
  // at 2048 that's 262K cycles per NIC before replay starts (minutes of sim).
  // T_W must match: clog2(T_DEPTH) (11 for 2048).
  parameter int T_DEPTH = 2048;
  localparam int T_W    = T_DEPTH > 2048 ? 12 : T_DEPTH > 1024 ? 11 : T_DEPTH > 512 ? 10 :
                           T_DEPTH > 256 ? 9 : T_DEPTH > 128 ? 8 : T_DEPTH > 64 ? 7 :
                           T_DEPTH > 32 ? 6 : T_DEPTH > 16 ? 5 : 4;
  // cap for the post-replay drain loop: run_cycles covers the trace window,
  // the drain loop absorbs the tail (and a stalled network burns through
  // this cap before the totals check below FAILs it)
  localparam int DRAIN_MAX = 32768;
  logic [63:0] tmem [ND * N * T_DEPTH];
  integer fd;
  integer RUN_CYCLES = 1000;
`endif

  for (genvar d = 0; d < ND; d++) begin : gen_nic_die
    for (genvar y = 0; y < Y_DIM; y++) begin : gen_nic_row
      for (genvar x = 0; x < X_DIM; x++) begin : gen_nic_col
        localparam int n = d * N + y * X_DIM + x;
        noc_nic #(
          .VCS(VCS), .X(x), .Y(y), .X_DIM(X_DIM), .Y_DIM(Y_DIM),
          .DIE_BASE(d * N),
`ifdef R1_MODE
          .T_DEPTH(T_DEPTH), .T_W(T_W)
`else
          .T_DEPTH(16), .T_W(4)
`endif
        ) u_nic (
          .clk(clk), .rst_n(rst_n),
          .inject(inj[d][y][x]), .inject_credit(injc[d][y][x]),
          .inject_credit_early(injce[d][y][x]),
          .eject(ej[d][y][x]), .eject_credit(ejc[d][y][x]),
          .gen_mode(gmode[n]), .burst_len(blen[n]),
          .rate0(r0[n]), .rate1(r1[n]), .seed(sd[n]),
          .trace_we(tw[n]), .trace_addr(ta[n]), .trace_data(td[n]),
          .tick(tck[n]), .injected_cnt(injc_[n]), .ejected_cnt(ejc_[n]),
          .lat_sum(lsum[n]), .lat_cnt(lcnt[n]),
          .dbg_trace0(dbg_trace0[n]), .dbg_tptr(dbg_tptr[n]),
          .dbg_pending(dbg_pending[n])
        );
      end
    end
  end

  integer errs = 0;
  longint replay_base;
  longint fdelta;

  task chk(input string name, input longint unsigned got,
              input longint unsigned expected);
    if (got !== expected) begin
      $display("FAIL %-40s got %0d expected %0d", name, got, expected);
      errs = errs + 1;
    end else begin
      $display("PASS %s", name);
    end
  endtask

  task automatic load_trace(input int n, input int addr, input longint unsigned entry);
    @(posedge clk);
    tw[n] = 1'b1; ta[n] = addr[3:0]; td[n] = entry[63:0];
    @(posedge clk);
    tw[n] = 1'b0;
  endtask

  initial begin
`ifdef R1_MODE
    // ---- Gate R1: BookSim-captured trace replay, eject stream dump ----
    // reset + idle config
    for (int n = 0; n < ND * N; n++) begin
      gmode[n] = 2'd0; blen[n] = '0; r0[n] = '0; r1[n] = '0; sd[n] = 32'hDEADBEEF;
      tw[n] = 1'b0; ta[n] = '0; td[n] = '0;
    end
    repeat (4) @(posedge clk);
    rst_n = 1'b1;
    repeat (2) @(posedge clk);

    // load per-NIC traces from trace_n%d.hex (generated from BookSim's trace_out)
    for (int n = 0; n < ND * N; n++) begin
      for (int i = 0; i < T_DEPTH; i++) tmem[n * T_DEPTH + i] = '1;
      $readmemh($sformatf("trace_n%0d.hex", n), tmem, n * T_DEPTH);
    end

    // pre-shift each loaded entry's cycle field by the replay base (the
    // tick at the end of the pump: N*T_DEPTH cycles after the current
    // tick), because the NIC's fire check uses an absolute tick_r; the
    // dump normalization below cancels the shift for BookSim time base 0.
    // A mcast range word (cycle==0, non-'1) must NOT be shifted: the NIC
    // identifies it by its zero cycle field.
    replay_base = tck[0] + ND * N * T_DEPTH;
    for (int n = 0; n < ND * N; n++) begin
      for (int i = 0; i < T_DEPTH; i++)
        if (tmem[n * T_DEPTH + i] != '1 &&
            tmem[n * T_DEPTH + i][63:32] != '0)
          tmem[n * T_DEPTH + i] =
            {tmem[n * T_DEPTH + i][63:32] + replay_base,
             tmem[n * T_DEPTH + i][31:0]};
    end
    // pump shifted entries into each NIC's trace BRAM (1 entry/cycle)
    for (int n = 0; n < ND * N; n++) begin
      for (int i = 0; i < T_DEPTH; i++) begin
        tw[n] = 1'b1; ta[n] = i[10:0]; td[n] = tmem[n * T_DEPTH + i];
        @(posedge clk);
      end
      tw[n] = 1'b0;
    end

    // fork delta: expected ejected = injected + sum(hi-lo+1) over mcast
    // range words in the trace hex (read before the drain loop uses it)
    begin
      longint fdelta_ = 0;
      for (int n = 0; n < ND * N; n++) begin
        string fn;
        int fd2;
        fn.itoa(n);
        fd2 = $fopen({"trace_n", fn, ".hex"}, "r");
        if (fd2 != 0) begin
          logic [63:0] w;
          int nread;
          do begin
            nread = $fscanf(fd2, "%h", w);
            if (nread == 1 && w[63:32] == '0 && w != '1)
              fdelta_ += w[23:16] - w[31:24] + 1;   // (hi - lo + 1) copies
          end while (nread == 1);
          $fclose(fd2);
        end
      end
      fdelta = fdelta_;
      $display("R1 fork delta: %0d (expected ejected = injected + delta)",
               fdelta);
    end

    fd = $fopen("rtl_flits.txt", "w");
    if (fd == 0) begin
      $display("FAIL R1 cannot open rtl_flits.txt");
      $fatal(1, "R1 dump open failed");
    end

    // replay: all NICs in trace mode, run the full window + drain
    if (!$value$plusargs("run_cycles=%0d", RUN_CYCLES)) RUN_CYCLES = 1000;
    $display("R1 replay: %0d NICs, %0d cycles", ND * N, RUN_CYCLES);
    for (int n = 0; n < ND * N; n++) gmode[n] = 2'd2;
    for (int t = 0; t < RUN_CYCLES; t++) begin
      for (int n = 0; n < ND * N; n++) begin
        if (ej[n / N][(n % N) / X_DIM][(n % N) % X_DIM].valid) begin
          $fwrite(fd, "%0d %0d %0d %0d %0d %0d\n",
                  tck[n] - replay_base,
                  ej[n / N][(n % N) / X_DIM][(n % N) % X_DIM].flit.cl,
                  ej[n / N][(n % N) / X_DIM][(n % N) % X_DIM].flit.src,
                  ej[n / N][(n % N) / X_DIM][(n % N) % X_DIM].flit.dst,
                  ej[n / N][(n % N) / X_DIM][(n % N) % X_DIM].flit.pid,
                  ej[n / N][(n % N) / X_DIM][(n % N) % X_DIM].flit.itime - replay_base);
        end
      end
      if (t % 500 == 0) begin
        longint tot;
        tot = 0;
        for (int n = 0; n < ND * N; n++) tot += ejc_[n];
        $display("PROG t=%0d ej=%0d", t, tot);
      end
      @(posedge clk);
    end

    // drain: keep ticking until every injected flit has ejected (the trace
    // window plus in-flight transit), so run_cycles only needs to cover the
    // injection window; a network that stops making progress burns through
    // DRAIN_MAX and the totals check below FAILs it
    for (int d = 0; d < DRAIN_MAX; d++) begin
      longint dinj, deje;
      dinj = 0; deje = 0;
      for (int n = 0; n < ND * N; n++) begin
        dinj += injc_[n];
        deje += ejc_[n];
      end
      // fork runs: ejected = injected + fork delta, so break when the
      // expected total has drained (avoids burning DRAIN_MAX every run)
      if (deje >= dinj + fdelta) break;
      for (int n = 0; n < ND * N; n++) begin
        if (ej[n / N][(n % N) / X_DIM][(n % N) % X_DIM].valid) begin
          $fwrite(fd, "%0d %0d %0d %0d %0d %0d\n",
                  tck[n] - replay_base,
                  ej[n / N][(n % N) / X_DIM][(n % N) % X_DIM].flit.cl,
                  ej[n / N][(n % N) / X_DIM][(n % N) % X_DIM].flit.src,
                  ej[n / N][(n % N) / X_DIM][(n % N) % X_DIM].flit.dst,
                  ej[n / N][(n % N) / X_DIM][(n % N) % X_DIM].flit.pid,
                  ej[n / N][(n % N) / X_DIM][(n % N) % X_DIM].flit.itime - replay_base);
        end
      end
      if ((RUN_CYCLES + d) % 500 == 0) begin
        longint tot;
        tot = 0;
        for (int n = 0; n < ND * N; n++) tot += ejc_[n];
        $display("DRAIN t=%0d ej=%0d", RUN_CYCLES + d, tot);
      end
      @(posedge clk);
    end
    $fflush(fd); $fclose(fd);

    begin
      longint tinj, tej;
      for (int n = 0; n < ND * N; n++) begin
        tinj += injc_[n];
        tej  += ejc_[n];
        $display("DBG2 n%0d inj=%0d ej=%0d pend=%0d tptr=%0d", n,
                 injc_[n], ejc_[n], dbg_pending[n], dbg_tptr[n]);
      end
      $display("DBG3 router occupancy (recv-pop) ports 0=local 1=E 2=W 3=N 4=S");
      for (int d = 0; d < ND; d++)
        for (int y = 0; y < Y_DIM; y++)
          for (int x = 0; x < X_DIM; x++) begin
            for (int p = 0; p < NUM_PORTS; p++) begin
              int o;
              o = rrecv[d][y][x][p] - rpop[d][y][x][p];
              $display("DBG3 D%0d R%0d,%0d port%0d occ=%0d recv=%0d pop=%0d",
                       d, x, y, p, o, rrecv[d][y][x][p], rpop[d][y][x][p]);
              for (int v = 0; v < VCS; v++)
                $display("DBG4 D%0d R%0d,%0d i%0d v%0d st=%0d op=%0d ov=%0d cf=%0d iu=%0d oc=%0d",
                         d, x, y, p, v, rdbg[d][y][x].st[p][v], rdbg[d][y][x].out_port[p][v],
                         rdbg[d][y][x].out_vc[p][v], rdbg[d][y][x].credit_free[p][v],
                         rdbg[d][y][x].in_use[p][v], rdbg[d][y][x].occ[p][v]);
            end
            $display("DBG5 D%0d R%0d,%0d cfE%0d cfW%0d cfN%0d cfS%0d cfL%0d iuE%0d iuW%0d iuN%0d iuS%0d iuL%0d",
                     d, x, y, rdbg[d][y][x].credit_free[0][0], rdbg[d][y][x].credit_free[1][0],
                     rdbg[d][y][x].credit_free[2][0], rdbg[d][y][x].credit_free[3][0],
                     rdbg[d][y][x].credit_free[4][0], rdbg[d][y][x].in_use[0][0],
                     rdbg[d][y][x].in_use[1][0], rdbg[d][y][x].in_use[2][0],
                     rdbg[d][y][x].in_use[3][0], rdbg[d][y][x].in_use[4][0]);
          end
      $display("DBG5 credit audit (cf + pops - acks == 8)");
      for (int d = 0; d < ND; d++)
        for (int y = 0; y < Y_DIM; y++)
          for (int x = 0; x < X_DIM; x++)
            for (int p = 0; p < NUM_PORTS; p++)
              for (int v = 0; v < VCS; v++) begin
                longint audit;
                audit = int'(rdbg[d][y][x].credit_free[p][v])
                      + int'(rdbg[d][y][x].pop_o[p][v])
                      - int'(rdbg[d][y][x].ack_o[p][v]);
                if (audit != 8)
                  $display("DBG5 D%0d R%0d,%0d o%0d v%0d cf=%0d pops=%0d acks=%0d audit=%0d !",
                           d, x, y, p, v, rdbg[d][y][x].credit_free[p][v],
                           rdbg[d][y][x].pop_o[p][v], rdbg[d][y][x].ack_o[p][v], audit);
              end
      $display("R1 totals: injected=%0d ejected=%0d", tinj, tej);
      $fflush();
      // fork gate: one injected stream -> 1 + (copy_hi - copy_lo + 1)
      // deliveries. The drain invariant is ejected == injected + fork_delta;
      // the delta is read from the same hex the NIC replays.
      begin
        if (tej !== tinj + fdelta) begin
          $display("FAIL R1 ejected != injected + fork delta (flits lost)");
          $fatal(1, "R1 drain check failed");
        end
      end
    end
    $display("R1 SIM COMPLETE: %0d cycles simulated", RUN_CYCLES);
    $finish;
`else
    // ---- reset + idle config
    for (int n = 0; n < ND * N; n++) begin
      gmode[n] = 2'd0; blen[n] = '0; r0[n] = '0; r1[n] = '0; sd[n] = 32'hDEADBEEF;
      tw[n] = 1'b0; ta[n] = '0; td[n] = '0;
    end
    repeat (4) @(posedge clk);
    rst_n = 1'b1;
    repeat (2) @(posedge clk);

    // ---- load trace entries into NIC 0 (all done before gmode=2)
    // entry format: {cycle[31:0], cl[7:0], dst[7:0], size[15:0]}
    load_trace(0, 0, (64'd10 << 32) | (1 << 16) | 1);   // wire@11 -> eject@23 NIC1, lat 12
    load_trace(0, 1, (64'd30 << 32) | (15 << 16) | 3);  // wire@31..33 -> eject@68..70 NIC15, lat 37
    load_trace(0, 2, (64'd40 << 32) | (0 << 16) | 2);   // wire@41..42 -> eject@48..49 NIC0, lat 7
    load_trace(0, 3, (64'd50 << 32) | (0 << 16) | 1);   // wire@51 -> eject@58 NIC0, lat 7

    // ---- S1: zero-traffic event sanity (generators still off)
    repeat (6) @(posedge clk);
    for (int n = 0; n < N; n++)
      if ((injc_[n] != 0) || (ejc_[n] != 0)) begin
        $display("FAIL zero-traffic: NIC %0d injected/ejected while idle", n);
        errs = errs + 1;
      end
    $display("PASS S1 zero-traffic: no injection/ejection while idle");

    // ---- S2/S3: trace replay (packet at tick 10)
    gmode[0] = 2'd2;

    // S2a: single 1-flit packet, 1 network hop (0,0)->(1,0): lat 12
    // S2b: loopback (0,0)->(0,0): 2-flit (tail lat 7) + 1-flit (tail lat 7)
    // S3: 3-flit burst (0,0)->(3,3): tail lat 37 (7+5*6), ejected 1/cycle
    repeat (120) @(posedge clk);
    chk("S2a 1-hop latency sum (NIC1 cl0)", lsum[1][0], 12);
    chk("S2a 1-hop packet count", lcnt[1][0], 1);
    chk("S2b loopback latency sum (NIC0, tails 7+7)", lsum[0][0], 14);
    chk("S2b loopback packet count", lcnt[0][0], 2);
    chk("S3 burst tail latency (NIC15, 7+5*6)", lsum[15][0], 37);
    chk("S3 packet count", lcnt[15][0], 1);
    chk("S2/S3 flits injected by NIC0", injc_[0], 7);
    chk("S3 flits ejected by NIC15", ejc_[15], 3);
    chk("S2a flits ejected by NIC1", ejc_[1], 1);
    chk("S2b flits ejected by NIC0 (loopback)", ejc_[0], 3);
    $display("PASS S2/S3 calibration + burst cadence (latency 7+5d, flits 1/cycle)");

    // ---- S4: LFSR smoke: bursts (B=5, rate 0.02) + control (rate 0.005)
    gmode[0] = 2'd0;
    repeat (10) @(posedge clk);
    blen[0] = 5;
    r0[0]   = 32'd335544;   // 0.02 * 2^24
    r1[0]   = 32'd83886;    // 0.005 * 2^24
    sd[0]   = 42;
    gmode[0] = 2'd1;
    repeat (400) @(posedge clk);
    gmode[0] = 2'd0;
    repeat (300) @(posedge clk);   // drain

    begin
      int tinj, tej;
      for (int n = 0; n < N; n++) begin
        tinj += injc_[n];
        tej  += ejc_[n];
      end
      chk("S4 total injected == total ejected (network drains)", tinj, tej);
    end
    begin
      int tcnt, tsum;
      for (int n = 0; n < N; n++) begin
        tcnt += lcnt[n][0];
        tsum += lsum[n][0];
      end
      if (tcnt == 0) begin
        $display("FAIL S4 no class-0 packets completed");
        errs = errs + 1;
      end else if (tsum / tcnt > 100) begin
        $display("FAIL S4 class-0 avg latency %0d > 100 (contention unexpected)",
                 tsum / tcnt);
        errs = errs + 1;
      end else begin
        $display("PASS S4 class-0 avg latency %0d (sanity < 100)",
                 tsum / tcnt);
      end
    end
    $display("PASS S4 LFSR smoke: all flits drained, latency sane");

    // ---- summary table (debug) ----
    for (int n = 0; n < N; n++) begin
      if (injc_[n] != 0)
        $display("  NIC%2d inj=%0d ej=%0d | cl0: cnt=%0d sum=%0d  cl1: cnt=%0d sum=%0d",
                 n, injc_[n], ejc_[n], lcnt[n][0], lsum[n][0], lcnt[n][1], lsum[n][1]);
    end

    // ---- verdict
    if (errs != 0) begin
      $display("GATE R0: %0d CHECK(S) FAILED", errs);
      $fatal(1, "gate R0 failed");
    end else begin
      $display("GATE R0: ALL CHECKS PASSED");
      $finish;
    end
`endif
  end

endmodule

`ifndef NOC_PKG_SV
`define NOC_PKG_SV

// T3 RTL leg — BookSim-faithful mesh NoC (see RTL-ARC.md §3 for the contract).

package noc_pkg;

  localparam int FLIT_BITS  = 64;   // data width (sideband carried in flit_t)
  localparam int NUM_PORTS  = 5;    // E W N S L
  localparam int PORT_E     = 0;
  localparam int PORT_W     = 1;
  localparam int PORT_N     = 2;
  localparam int PORT_S     = 3;
  localparam int PORT_L     = 4;

  localparam int MAX_VC     = 4;
  localparam int VC_BUF_DEF = 8;

  localparam int X_DIM      = 4;
  localparam int Y_DIM      = 4;

  localparam int CH_LAT     = 2;

  typedef struct packed {
    logic [FLIT_BITS-1:0] data;
    logic                 head;
    logic                 tail;
    logic [2:0]           vc;
    logic [2:0]           cl;
    logic [7:0]           src;
    logic [7:0]           dst;
    logic [15:0]          pid;
    logic [31:0]          itime;
    logic                 mcast;    // VeritX multicast stream: this flit is a stream whose
                                    // copies eject at every node id in [copy_lo, copy_hi]
                                    // (BookSim mcast_k row-multicast, bridge offset form).
    logic [7:0]           copy_lo;  // copy range, inclusive (copy at node n has
    logic [7:0]           copy_hi;  //   pid = stream.pid + (n - copy_lo) + 1)
  } flit_t;

  typedef struct packed {
    logic valid;
    flit_t flit;
  } link_f_t;

  typedef struct packed {
    logic        valid;
    logic [2:0]  vc;
  } link_c_t;

  // Router debug readout (Gate R1 deadlock tracing).
  // VC dimension is [7:0] (8) — the max VCS any build uses. The router's
  // debug assigns index v in [0, VCS); at VCS=8 the old hardcoded [3:0]
  // (4-VC) struct overflowed, and verilator 5.032 generated runtime-shifted
  // LHS writes for the out-of-bounds element -> "lvalue required" compile
  // error (the "VCS>=8 build wall"). Upper indices are unused at VCS<8.
  typedef struct packed {
    logic [4:0][7:0][2:0]  st;
    logic [4:0][7:0][2:0]  out_port;
    logic [4:0][7:0][2:0]  out_vc;
    logic [4:0][7:0][3:0]  credit_free;
    logic [4:0][7:0]       in_use;
    logic [4:0][7:0][3:0]  occ;
    logic [4:0][7:0][31:0] pop_o;
    logic [4:0][7:0][31:0] ack_o;
  } dbg_router_t;

endpackage

`endif

`ifndef NOC_4D_PKG_SV
`define NOC_4D_PKG_SV

// VeritX Research — 4D Hypercube / 4D Mesh NoC Package (X, Y, Z, W)
// 9-Port Router: +X (East), -X (West), +Y (North), -Y (South), +Z (Up), -Z (Down), +W (Hyper-Up), -W (Hyper-Down), Local

package noc_4d_pkg;

  localparam int FLIT_BITS  = 64;   // Data width
  localparam int NUM_PORTS  = 9;    // E, W, N, S, U, D, W4, E4, L (9 ports total)
  
  localparam int PORT_E     = 0;    // +X
  localparam int PORT_W     = 1;    // -X
  localparam int PORT_N     = 2;    // +Y
  localparam int PORT_S     = 3;    // -Y
  localparam int PORT_U     = 4;    // +Z
  localparam int PORT_D     = 5;    // -Z
  localparam int PORT_W4    = 6;    // +W (4th Dimension / Optical / Hypercube Link)
  localparam int PORT_E4    = 7;    // -W (4th Dimension / Optical / Hypercube Link)
  localparam int PORT_L     = 8;    // Local (NIC)

  localparam int MAX_VC     = 4;
  localparam int VC_BUF_DEF = 8;

  // 4D Topology: 2x2x2x2 = 16 nodes (or 4x4x4x4 = 256 nodes)
  localparam int X_DIM      = 2;
  localparam int Y_DIM      = 2;
  localparam int Z_DIM      = 2;
  localparam int W_DIM      = 2;

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
  } flit_t;

  typedef struct packed {
    logic valid;
    flit_t flit;
  } link_f_t;

  typedef struct packed {
    logic        valid;
    logic [2:0]  vc;
  } link_c_t;

endpackage

`endif

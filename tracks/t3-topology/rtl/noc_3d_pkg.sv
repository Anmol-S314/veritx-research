`ifndef NOC_3D_PKG_SV
`define NOC_3D_PKG_SV

// VeritX Research — 3D Mesh NoC Package (3D TSV / Vertical Interconnect)
// 7-Port Router: East, West, North, South, Up (+Z TSV), Down (-Z TSV), Local

package noc_3d_pkg;

  localparam int FLIT_BITS  = 64;   // Data width
  localparam int NUM_PORTS  = 7;    // E, W, N, S, U, D, L (7 ports total)
  
  localparam int PORT_E     = 0;    // +X (East)
  localparam int PORT_W     = 1;    // -X (West)
  localparam int PORT_N     = 2;    // +Y (North)
  localparam int PORT_S     = 3;    // -Y (South)
  localparam int PORT_U     = 4;    // +Z (Up / Vertical TSV)
  localparam int PORT_D     = 5;    // -Z (Down / Vertical TSV)
  localparam int PORT_L     = 6;    // Local (NIC)

  localparam int MAX_VC     = 4;
  localparam int VC_BUF_DEF = 8;    // 8 flits per VC buffer

  localparam int X_DIM      = 4;    // 4x4x2 3D Stacked Die Topology (32 nodes)
  localparam int Y_DIM      = 4;
  localparam int Z_DIM      = 2;    // 2 stacked dies (Logic layer 0 + Logic/Memory layer 1)

  localparam int CH_LAT_2D  = 2;    // Horizontal 2D channel latency (2 cycles)
  localparam int CH_LAT_3D  = 1;    // 3D TSV channel latency (1 cycle - ultra-short vertical wire)

  typedef struct packed {
    logic [FLIT_BITS-1:0] data;
    logic                 head;
    logic                 tail;
    logic [2:0]           vc;       // Input VC
    logic [2:0]           cl;       // Class (0 = DMA/KV-Cache, 1 = Control)
    logic [7:0]           src;
    logic [7:0]           dst;
    logic [15:0]          pid;      // Packet ID
    logic [31:0]          itime;    // Injection time
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

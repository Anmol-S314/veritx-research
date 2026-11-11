// srota_route_pkg.sv — shared enums, header layout and port map.
//
// Extracted from SSM-UARCH-ROUTE-001 rev 0.3 (§8, §10, §11) and
// SSM-UARCH-TOPO-003 rev 0.3 (§10). The header layout is a PREVIEW layout:
// the final field offsets belong to SSM-UARCH-PKT-008 and must replace these
// constants when #8 lands. The port map is ONE explicit reading of VC-R5:
// per-tile local injection/ejection + four mesh neighbours + four MECS drop
// ports. VC-R5 is still open; do not present this map as the final P.
`default_nettype none

package srota_route_pkg;

  typedef enum logic [1:0] {
    SROTA_ROW_FIRST    = 2'b00,
    SROTA_COLUMN_FIRST = 2'b01,
    SROTA_VALIANT_L1   = 2'b10,
    SROTA_RESERVED     = 2'b11
  } srota_path_shape_e;

  typedef enum logic [2:0] {
    SROTA_FSM_IDLE    = 3'b000,
    SROTA_FSM_LOOKUP  = 3'b001,
    SROTA_FSM_TEL_RD  = 3'b010,
    SROTA_FSM_SELECT  = 3'b011,
    SROTA_FSM_CACHED  = 3'b100,
    SROTA_FSM_INJECT  = 3'b101
  } srota_fiu_state_e;

  /* verilator lint_off UNUSEDPARAM */
  localparam int SROTA_MAX_K = 32;
  localparam int SROTA_MAX_C = 8;
  localparam int SROTA_MAX_P = 2 * SROTA_MAX_C + 8; // 24 at c=8

  // Preview flit/header layout. Bits above SROTA_HDR_USED_BITS are payload.
  localparam int SROTA_HDR_DEST_X_LSB      = 0;
  localparam int SROTA_HDR_DEST_Y_LSB      = 8;
  localparam int SROTA_HDR_DEST_TILE_LSB   = 16;
  localparam int SROTA_HDR_PATH_SHAPE_LSB  = 24;
  localparam int SROTA_HDR_VALIANT_X_LSB   = 26;
  localparam int SROTA_HDR_VALIANT_Y_LSB   = 34;
  localparam int SROTA_HDR_USED_BITS       = 42;
  /* verilator lint_on UNUSEDPARAM */

  // One explicit VC-R5 reading: P = 2*c + 8.
  //   0 .. c-1          local injection
  //   c .. 2c-1         local ejection
  //   2c .. 2c+3        mesh N/S/E/W
  //   2c+4 / 2c+5       MECS row drop out / in
  //   2c+6 / 2c+7       MECS column drop out / in
  function automatic int srota_p(input int c);
    return 2 * c + 8;
  endfunction

  function automatic int srota_local_inj_port(input int tile);
    return tile;
  endfunction

  function automatic int srota_local_eject_port(input int tile, input int c);
    return c + tile;
  endfunction

  function automatic int srota_mesh_base(input int c);
    return 2 * c;
  endfunction

  function automatic int srota_row_out_port(input int c);
    return 2 * c + 4;
  endfunction

  function automatic int srota_row_in_port(input int c);
    return 2 * c + 5;
  endfunction

  function automatic int srota_col_out_port(input int c);
    return 2 * c + 6;
  endfunction

  function automatic int srota_col_in_port(input int c);
    return 2 * c + 7;
  endfunction

  function automatic int srota_clog2(input int value);
    int v;
    v = value;
    srota_clog2 = 0;
    while (v > 1) begin
      v = (v + 1) >> 1;
      srota_clog2++;
    end
  endfunction

endpackage

`default_nettype wire

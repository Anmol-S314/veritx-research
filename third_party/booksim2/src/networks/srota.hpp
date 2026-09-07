// ----------------------------------------------------------------------
//
//  Srota NoC -- concentrated mesh + MECS express layer, with O1TURN-XY
//  routing and an injection-time telemetry-adaptive overlay.
//
//  Implements the Plane D data plane described by:
//
//    SSM-UARCH-TOPO-003  rev 0.3  Topology / MECS
//    SSM-UARCH-ROUTE-001 rev 0.3  Routing Algorithm
//    SSM-UARCH-VC-002    rev 0.3  VC Mapping / Allocation   (buffer model)
//    SSM-UARCH-TEL-004   rev 0.3  Telemetry                 (Plane T model)
//    SSM-UARCH-PKT-008   rev 0.3  Packet Protocol           (header fields)
//
//  Everything below names the section of the spec it implements, so a
//  reviewer can check the model against the document rather than against
//  this file's own commentary. Where the model deliberately departs from
//  the spec -- because BookSim cannot represent something, or because the
//  spec has an open item that has not been decided -- it says so under
//  "MODELING DEPARTURES" at the end of this note.
//
// ======================================================================
//  1. TOPOLOGY  (TOPO-003 sections 2, 3, 5, 10)
// ======================================================================
//
//  k x k concentrator routers, c tiles behind each (TOPO-003 section 2.1:
//  1024 tiles as 16x16 at c=4). Router (x,y) has id y*k + x, matching the
//  {router_y, router_x, tile_within_group} coordinate scheme of
//  TOPO-003 section 10.1; terminal t of router n is n*c + t, so
//  tile_within_group == dest % c exactly as section 10.1 specifies.
//
//  MECS express layer (TOPO-003 section 3.1): "each concentrator drives
//  one multidrop express channel per dimension per direction: a single-
//  driver wire bundle spanning the row or column with drop-off points at
//  every router along that span."
//
//  That sentence is implemented literally. Router (x,y) drives up to four
//  MultiDropChannels:
//
//     XPOS  tapped by (x+1,y) .. (k-1,y)     k-1-x drops
//     XNEG  tapped by (x-1,y) .. (0,y)       x     drops
//     YPOS  tapped by (x,y+1) .. (x,k-1)     k-1-y drops
//     YNEG  tapped by (x,y-1) .. (x,0)       y     drops
//
//  A direction exists iff at least one router lies that way, so boundary
//  routers simply have fewer express ports. Out-degree is c + 4 in the
//  interior and never depends on k -- which is TOPO-003 section 3.2's
//  "O(k) channels per dimension versus O(k^2) for a flattened butterfly."
//  In-degree is c + 2*(k-1) because every router is a passive tap on
//  every other router's channel in its row and column; that in/out
//  asymmetry (cheap passive taps, expensive active drivers) is the point
//  of MECS, not a modeling artifact.
//
//  Why per-DIRECTION channels and not one per dimension. TOPO-003
//  section 7.3's count table says "express channels = 2K", i.e. one per
//  row plus one per column, while section 7.2 requires "exactly one
//  driver per segment per direction" and ROUTE-001 section 4.2 builds
//  its CDG with "one node per MECS row-segment and column-segment." The
//  two reconcile if srota_mecs_row[y] is read as the row's express
//  LAYER, containing one driven segment per router per direction, rather
//  than as a single wire that all k routers somehow drive. Modeling it
//  per-direction is what preserves the single-driver property (F1's
//  premise) and gives an east-bound and a west-bound flit independent
//  wires, which one shared bidirectional channel per dimension would
//  not. See MODELING DEPARTURES note 1.
//
//  MECS may be disabled per dimension (TOPO-003 section 5, "Off reverts
//  to a plain concentrated mesh -- the ablation baseline"). A dimension
//  with express off gets ordinary point-to-point nearest-neighbour links
//  instead, and routing walks it one step at a time.
//
//  PORT MAP -- the single contract _BuildNet and srota_o1turn share.
//  Output ports of router (x,y):
//
//     [0, c)                local terminal (ejection) ports
//     [c, c + ndirs)        dimension ports, in the fixed order
//                           XNEG, XPOS, YNEG, YPOS, counting only the
//                           directions present at this (x,y).
//
//  PortOffset() below computes that offset and is the ONLY place the
//  order is written down; both the builder and the routing function call
//  it, so they cannot drift apart. This is the same discipline
//  GEC::MeshPortOffset already uses. Presence is identical in express
//  and mesh mode (a direction is present iff some router lies that way),
//  so the port map does not change shape when MECS is toggled -- only
//  what is wired to each port does.
//
//  Input ports are [0, c) injection followed by the taps, in build
//  order. Only the [0,c) boundary matters to routing: in_channel < c is
//  true exactly on a packet's first hop, which is how the routing
//  function recognises injection-adjacent state.
//
//  QoS islands (TOPO-003 section 4) are carried as an island-column
//  bitmap. They do not change connectivity -- an island is "a router
//  wrapped in srota_island_wrap" (section 4.1), and section 7.5 is
//  explicit that the router inside the wrapper is an unmodified
//  srota_router_d. The wrapper's rate regulator is not modeled; what IS
//  modeled and checked here is invariant I-ISL, the placement rule,
//  because that is a property of the topology and the routing rules
//  together and is exactly what TP-V2 asks a generator to verify.
//
// ======================================================================
//  2. ROUTING  (ROUTE-001 sections 2, 3, 5, 11, 13)
// ======================================================================
//
//  ROUTE-001 section 2 splits routing into two layers and says keeping
//  them separate is "the single most important design discipline in this
//  document." The split survives into this implementation intact:
//
//  Layer 1 -- path selection. Adaptive, injection-time only, once per
//  flow-epoch, at the FIU. Implemented in SrotaFiuPathSel, reached only
//  from the inject branch of srota_o1turn (where BookSim passes r=NULL,
//  which IS the FIU: no router exists yet).
//
//  Layer 2 -- in-network traversal. Deterministic, always. Implemented
//  in SrotaRouteCompute, which takes only (position, header) and has no
//  congestion argument at all -- the C-model equivalent of ROUTE-001
//  section 8.1's "note the absence of any congestion input on the
//  routing path... checkable by inspection rather than by reading
//  logic." If someone later adds per-hop adaptivity, they have to change
//  that function's signature to do it, which is the point.
//
//  Three path shapes (ROUTE-001 section 5.1), carried in Flit::ph, which
//  is this model's path_shape header field (PKT-008 section 3.1, bits
//  [46:45]):
//
//     ROW_FIRST   row express to (dx,sy), then column express to (dx,dy)
//     COL_FIRST   column express to (sx,dy), then row express to (dx,dy)
//     VALIANT_L1  row-first to a random intermediate, then...
//     VALIANT_L2  ...row-first from the intermediate to the destination
//
//  VALIANT_L2 is not a fourth architectural shape. ROUTE-001 section
//  13.4 says the intermediate router "rewrites the header's shape field
//  to ROW_FIRST"; this model rewrites it to VALIANT_L2, which behaves
//  identically to ROW_FIRST for route computation and differs only in
//  which VC set it may use. Keeping the second leg distinguishable is
//  what lets the rank VC policy below stay acyclic across a Valiant
//  path's two turns -- see section 3. Flit::intm carries the cached
//  intermediate, i.e. hdr_valiant_x/hdr_valiant_y packed as a router id.
//
//  The flow-epoch cache (ROUTE-001 section 10.4) is keyed by a flow hash
//  over (src, dest, class) -- PKT-008 section 3.1's "source-destination-
//  class triple identity" -- with a stored epoch tag and lazy
//  invalidation, no active flush (section 10.3). It stores shape AND
//  intermediate together, which is rev 0.3's RT-R8 fix (section 5.4:
//  "re-randomising per packet breaks F6 for every Valiant-routed flow").
//  There is deliberately no stored flow identity and no identity compare,
//  so a hash collision makes the second flow adopt the first's cached
//  path -- a performance failure, not a correctness one, exactly as
//  section 10.4 argues.
//
// ======================================================================
//  3. DEADLOCK, AND WHY THIS MODEL EXISTS  (ROUTE-001 section 4.5)
// ======================================================================
//
//  ROUTE-001 rev 0.3 section 4.5 is the document's highest-priority open
//  item, RT-R7. In short: each path shape is individually acyclic, but
//  with both direct shapes enabled -- the shipping default,
//  ROUTE_PATH_EN = 0b111 -- a row-first packet contributes a row->col
//  dependency edge and a column-first packet contributes a col->row edge,
//  and together those close a two-node cycle. Every standard defence
//  (two VC sets, escape VC, virtual network partitioning) is unavailable
//  on Plane D by design, because Plane D carries no VC arrays at all
//  (VC-002 section 2.1).
//
//  Section 4.5.4 states the immediate next action: "Run the section 4.4
//  model check on the 4x4 abstraction with ROUTE_PATH_EN = 0b111. It is
//  a two-node cycle needing only two flows; if the hazard is real the
//  check finds it immediately."
//
//  That is what srota_vc_policy is for. It selects the deadlock-
//  avoidance mechanism, so the hazard can be reproduced deliberately and
//  each candidate resolution measured against the same traffic:
//
//    "none"      All shapes share the full VC range. This is the
//                spec-literal Plane D -- no VC separation of any kind.
//                It is the RT-R7 reproducer: run it with both direct
//                shapes enabled and the directed pattern from ROUTE-001
//                section 16.3 and the fabric should deadlock. Use this
//                to answer 4.5.4, not to get throughput numbers.
//
//    "shape"     O1TURN's own answer (ROUTE-001 section 3.4.1): XY and
//                YX get disjoint VC sets. Costs 2 VCs. Refused when
//                Valiant is enabled, because a Valiant path turns twice
//                (row->col at the intermediate leg, then col->row
//                starting the second leg) and so is NOT safe to share
//                the XY set -- a subtlety worth stating explicitly
//                because "Valiant is internally row-first" makes it look
//                like it should be.
//
//    "rank"      VCs split by hop rank rather than by dimension order:
//                leg-and-turn position within the path, which strictly
//                increases along every route regardless of which shape
//                was chosen. 2 ranks for the direct shapes, 4 with
//                Valiant. This is the general fix -- it is the only
//                policy here that keeps all three shapes concurrently
//                live and provably acyclic, and it is NOT among the four
//                options ROUTE-001 section 4.5.3 lists. See RT-R7 NOTE
//                below.
//
//    "oneshape"  Section 4.5.3 option 1, "one shape per epoch, fabric-
//                wide." All flows in an epoch use the same shape, so
//                only one turn direction exists at a time and the
//                section 4.3 argument holds unmodified. Costs 0 extra
//                VCs, loses per-flow diversity, keeps temporal
//                diversity. Section 4.5.3 calls it "cheapest by a wide
//                margin; evaluate first" -- this policy is how you
//                evaluate it.
//
//  RT-R7 NOTE, offered back to the spec. Section 4.5.3's option table
//  lists "two VC sets on Plane D" and dismisses it as reversing VC-002's
//  central decision. Splitting by RANK rather than by ORDER is strictly
//  cheaper than splitting by order and section 4.5.3 does not consider
//  it: it needs the same 2 VCs for the two direct shapes, but unlike the
//  order split it also covers Valiant (at 4), and it does not care how
//  many shapes are enabled. It is still a VC mechanism, so it still
//  reverses VC-002 section 2.1 -- the point is only that if the
//  architecture ends up conceding VCs on Plane D at all, rank is the
//  cheaper way to spend them, and section 4.5.3's cost comparison should
//  say so before "one shape per epoch" is chosen on cost grounds.
//
// ======================================================================
//  4. TELEMETRY  (TEL-004 sections 2, 3, 4)
// ======================================================================
//
//  Plane T is a scheduled TDM ring-tree at 1 GHz against Plane D's 4 GHz
//  (TEL-004 section 2.1), reporting a 4-bit coarse occupancy nibble per
//  router (section 2.2), aggregated per column and per row (section 4).
//  The property that matters to routing is section 3: latency is a
//  constant set by ring depth, NOT a function of Plane D congestion --
//  ROUTE-001 section 5.3 depends on that ("a routing decision based on
//  stale congestion data is worse than no adaptivity at all").
//
//  SrotaTelemetry models exactly that and nothing more: it samples every
//  router's occupancy every srota_tel_period Plane-D cycles, aggregates
//  to per-column and per-row nibbles, and publishes them after a fixed
//  srota_tel_latency delay. Bounded, constant staleness. Deliberately
//  NOT modeled: the ring itself, slot scheduling, TL-V1/TL-V3 slot-map
//  faults. Those are correctness properties of the telemetry plane's own
//  RTL and nothing in a network simulator would exercise them.
//
//  Slot-to-coordinate mapping is identity (TEL-004 section 2.5, S-SLOT:
//  "on a column ring, cfg_my_slot == router_y"), which is why the
//  aggregated vectors here are indexed directly by column and row with
//  no translation table -- the same reason the drop index equals the
//  mesh coordinate in TOPO-003 section 10.2.
//
// ======================================================================
//  5. MODELING DEPARTURES -- read this before trusting a number
// ======================================================================
//
//  1. Express channel granularity. TOPO-003 section 7.3 counts 2K
//     express channels; this model builds up to 4 per router (one per
//     direction per dimension), for the reason argued in section 1
//     above. Channel COUNT figures from this model therefore will not
//     match section 7.3's table, and should not be quoted against it.
//     Hop counts, reach, and contention behaviour are unaffected.
//
//  2. No side buffer, no staging latch. VC-002's Plane D router has a
//     2-flit staging latch per input and one shared 8-flit side buffer
//     (sections 2.1-2.3), and no VC arrays at all. BookSim's IQRouter is
//     a per-input VC-buffered router; it cannot represent "shared buffer
//     that only allocation losers enter." What this model gives you is a
//     conventional buffered router whose buffer depth you set to match,
//     so contention and backpressure are represented but the side
//     buffer's specific fill/drain/watermark behaviour is not. Anything
//     depending on side-buffer occupancy -- VC_SIDEBUF_WATERMARK, the
//     Plane-T congestion hint it raises, VC-R1's 4-16 flit capacity
//     sweep -- is out of reach here and needs the RTL or a dedicated
//     model.
//
//  3. VCs exist here; on Plane D they do not. Every VC policy above
//     except "none" and "oneshape" spends a resource the real Plane D
//     does not have. That is the whole reason "none" and "oneshape" are
//     offered: they are the only two policies that correspond to a
//     shippable Plane D configuration. Treat "shape" and "rank" as
//     measurements of what a VC-equipped Plane D would buy, i.e. as
//     input to the RT-R7 decision, not as models of the current design.
//
//  4. Per-tap VC sub-ranges are NOT allocated. GEC's MECS path splits
//     each multidrop port's VC range per tap so two flits bound for
//     different taps of one channel are not treated as contending for
//     one VC. This model does not, because a directional Srota channel
//     has up to k-1 taps and splitting would need k-1 VCs per rank. The
//     consequence is conservative, not wrong: BookSim will sometimes
//     serialise two packets addressed to different drops of the same
//     channel that hardware would overlap. It costs throughput in the
//     model; it cannot produce an illegal schedule. Per-drop BufferState
//     is still tracked correctly by IQRouter, so credit accounting stays
//     per-drop as VC-002 section 5.1 requires.
//
//  5. Multicast is not routed here. TOPO-003 section 9.3's simultaneous
//     multi-drop accept -- the mechanism behind the ~16x weight-
//     broadcast claim -- needs the multicast fork path, and ROUTE-001
//     section 13.2 explicitly scopes multicast to PKT-008 rather than to
//     the routing algorithm. srota_o1turn routes unicast only.
//
//  6. Arbitration is BookSim's, not Srota's. The three-level golden /
//     slack / STC-batch arbiter (ROUTE-001 section 11.2) is not
//     implemented; measurable claim M3 (section 16.4) needs it and is
//     therefore not answerable from this model yet. Flit::pri carries the
//     slack class so the field exists for a future allocator, but no
//     allocator reads it.
//
//  7. Drop latency. TOPO-003 section 6.2's repeatered fallback
//     (TOPO_DROP_LATENCY = 2) is modeled as channel latency on express
//     channels only, per section 9.5's "at high radix the repeatered
//     fallback makes it 2, adding one cycle per segment." Mesh links
//     stay at 1.
//
// ======================================================================

#ifndef _SROTA_HPP_
#define _SROTA_HPP_

#include <vector>
#include <string>

#include "network.hpp"
#include "routefunc.hpp"

// ----------------------------------------------------------------------
//  Path shapes -- PKT-008 section 3.1 path_shape [46:45], extended with
//  VALIANT_L2 for the post-rewrite second leg (ROUTE-001 section 13.4).
//  Carried in Flit::ph.
// ----------------------------------------------------------------------
enum SrotaShape {
  SROTA_ROW_FIRST  = 0,
  SROTA_COL_FIRST  = 1,
  SROTA_VALIANT_L1 = 2,
  SROTA_VALIANT_L2 = 3
};

// ROUTE_PATH_EN bit positions (ROUTE-001 section 14.1).
enum SrotaPathEn {
  SROTA_EN_ROW     = 0x1,
  SROTA_EN_COL     = 0x2,
  SROTA_EN_VALIANT = 0x4
};

// srota_vc_policy -- see design note section 3.
enum SrotaVCPolicy {
  SROTA_VC_NONE     = 0,  // spec-literal shared VCs; the RT-R7 reproducer
  SROTA_VC_SHAPE    = 1,  // O1TURN's own two-VC-set answer
  SROTA_VC_RANK     = 2,  // hop-rank split; the only all-shapes-safe one
  SROTA_VC_ONESHAPE = 3   // section 4.5.3 option 1, one shape per epoch
};

// ----------------------------------------------------------------------
//  Result of one deterministic route-compute step (ROUTE-001 section
//  11.1's rc_port_oh / rc_is_eject / rc_turn_taken outputs). Lives in the
//  header because the elaboration-time I-ISL check walks routes with it.
// ----------------------------------------------------------------------
struct SrotaRouteResult {
  int  out_port;     // output port index at this router
  int  dir;          // which SrotaNoC::Dir this hop takes, -1 on ejection
  int  drop;         // tap index on a multidrop channel, -1 if not one
  int  rank;         // leg/turn position; see the rank VC policy note
  bool eject;        // rc_is_eject
  int  turn;         // rc_turn_taken -- this hop is the path's turn
  int  new_shape;    // section 13.4 rewrite; == input shape when unchanged
};

// Rank base by shape. The direct shapes occupy ranks 0-1; a Valiant
// path's second leg occupies 2-3 so its second turn cannot share a VC
// set with its first. See the design note, section 3.
inline int SrotaRankBase( int shape ) {
  return ( shape == SROTA_VALIANT_L2 ) ? 2 : 0;
}

// Deterministic route compute -- ROUTE-001 section 11.1.
//
// NOTE THE SIGNATURE. Position and header in, port and rank out. There is
// no congestion argument, no router handle and no telemetry access, which
// is the C-model form of section 8.1's "note the absence of any
// congestion input on the routing path -- checkable by inspection." Any
// future attempt to make in-network routing adaptive has to change this
// signature first.
SrotaRouteResult SrotaRouteCompute( int my_router, int dest_terminal,
                                    int shape, int intm, int k, int c );

class SrotaNoC : public Network {
public:
  SrotaNoC( const Configuration &config, const string & name );

  static void RegisterRoutingFunctions();

  int  GetK() const { return _k; }
  int  GetC() const { return _c; }
  bool RowExpress() const { return _row_express; }
  bool ColExpress() const { return _col_express; }

  // Direction ordering shared by _BuildNet (which assigns ports) and
  // SrotaRouteCompute (which routes into them). Order is fixed here and
  // nowhere else.
  enum Dir { SROTA_XNEG = 0, SROTA_XPOS = 1, SROTA_YNEG = 2, SROTA_YPOS = 3 };

  // True iff at least one router lies in direction `dir` from (x,y).
  // Identical in express and mesh mode -- see the port-map note above.
  static bool DirPresent( int x, int y, int k, Dir dir );

  // 0-based offset (added to the c local ports) of `dir`'s output port at
  // (x,y), or -1 if that direction is absent. Static and stateless so the
  // builder and the routing function call the same code.
  static int PortOffset( int x, int y, int k, Dir dir );

  // Number of present directions at (x,y) -- the router's dimension-port
  // count, i.e. out-degree minus c.
  static int DirDegreeAt( int x, int y, int k );

private:
  int  _k;
  int  _c;
  bool _row_express;      // TOPO_MECS_ENABLE bit 0
  bool _col_express;      // TOPO_MECS_ENABLE bit 1
  int  _drop_latency;     // TOPO_DROP_LATENCY (1 or 2)
  int  _island_col_map;   // TOPO_ISLAND_COL_MAP bitmap

  // Running index into _chan for dimensions built in mesh mode. Express
  // dimensions consume none of these -- they live in _md_chan.
  int  _next_p2p;

  void _ComputeSize( const Configuration &config );
  void _BuildNet( const Configuration &config );

  // One MultiDropChannel per (driver, direction) for the given dimension
  // -- TOPO-003 sections 3.1, 7.4, 11.1.
  void _BuildExpressDim( bool xdim );
  // MECS-off ablation baseline: nearest-neighbour links (section 5).
  void _BuildMeshDim( bool xdim );

  void _PrintConfigBanner( int num_vcs, const string & pol ) const;

  // F1 (ROUTE-001 sections 4.2, 4.4): build the channel dependency graph
  // this configuration's routing rules actually admit, and look for a
  // cycle. Run on a small abstraction radix, exhaustively, which is
  // exactly what section 4.4 specifies -- "a model check on a 4x4
  // abstraction: small enough for exhaustive exploration, large enough
  // to exercise every edge type. Because the argument does not depend on
  // mesh radix, the 4x4 result generalizes."
  void _CheckCDG( int radix ) const;

  // TP-V2 (TOPO-003 section 15): every legal route from every tile to
  // every shared resource must contain exactly one island router, and it
  // must be the last router before the attach queue. Run at elaboration
  // over the emitted structure, exactly as the spec asks a generator to.
  void _CheckIslandPlacement() const;

  // Where a flit lands after one route step; used only by the TP-V2 walk.
  int _NextRouterFor( int cur, const SrotaRouteResult & rr ) const;
};

// ----------------------------------------------------------------------
//  The routing function. ROUTE-001's two layers, both reached through
//  this one entry point because that is BookSim's interface:
//    inject == true   -> Layer 1, the FIU (r is NULL: no router yet)
//    inject == false  -> Layer 2, deterministic route compute
// ----------------------------------------------------------------------
void srota_o1turn( const Router *r, const Flit *f, int in_channel,
                   OutputSet *outputs, bool inject );

#endif

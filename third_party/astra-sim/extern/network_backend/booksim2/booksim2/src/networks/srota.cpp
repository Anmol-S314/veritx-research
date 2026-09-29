// ----------------------------------------------------------------------
//
//  Srota NoC -- concentrated mesh + MECS express, O1TURN-XY routing with
//  an injection-time telemetry-adaptive overlay.
//
//  See srota.hpp for the full design note, the spec section mapping, and
//  the list of deliberate modeling departures. Every section reference in
//  this file ("TOPO-003 section 3.1" and so on) points into the rev 0.3
//  hardware sub-documents.
//
// ----------------------------------------------------------------------

#include "booksim.hpp"

#include <vector>
#include <deque>
#include <string>
#include <sstream>
#include <iostream>
#include <cassert>
#include <cstdlib>

#include "random_utils.hpp"
#include "misc_utils.hpp"
#include "multidropchannel.hpp"
#include "iq_router.hpp"
#include "srota_router_d.hpp"
#include "srota.hpp"

// ----------------------------------------------------------------------
//  File-scope configuration consulted by the routing function. Same
//  convention gec.cpp already uses for gGECo/gGECd: these are set once at
//  network construction and read-only thereafter.
// ----------------------------------------------------------------------
static int  gSrK            = 0;     // mesh radix
static int  gSrC            = 0;     // concentration
static bool gSrRowExpress   = true;  // TOPO_MECS_ENABLE bit 0
static bool gSrColExpress   = true;  // TOPO_MECS_ENABLE bit 1
static int  gSrPathEn       = 0x7;   // ROUTE_PATH_EN
static int  gSrVCPolicy     = SROTA_VC_RANK;
static int  gSrCongThresh   = 8;     // ROUTE_CONGESTION_THRESH
static int  gSrEpochLen     = 1024;  // ROUTE_EPOCH_LEN
static int  gSrForceShape   = -1;    // ROUTE_DEBUG_FORCE_SHAPE, -1 = off
static int  gSrFlowCacheSz  = 64;    // per-FIU flow-epoch cache entries
static int  gSrIslandColMap = 0;     // TOPO_ISLAND_COL_MAP

// Number of distinct VC partitions the active policy needs. Computed once
// in _ComputeSize so the routing function never has to re-derive it.
static int  gSrVCSets       = 1;

// Plane D's VC count. Not gNumVCs: that is the global num_vcs, which the
// traffic manager sizes for the widest plane.
static int  gSrDVCs         = 1;

// Planes. Written only by the Plane D instance (subnet 0) except for the
// Plane C fields, which the Plane C instance writes -- so building the
// second plane can never clobber the first plane's routing state.
static int  gSrPlanes       = 0x5;   // TOPO_PLANE_PRESENT
static int  gSrPlaneCSubnet = -1;    // subnet carrying Plane C, -1 if absent
static int  gSrPlaneCVCs    = 3;

// srota_isl_route = colfirst: island-bound flows are routed column-first.
static bool gSrIslColFirst  = false;

static bool SrotaIslandBound( int dest_router ) {
  return gSrIslColFirst &&
         ( gSrIslandColMap & ( 1 << ( dest_router % gSrK ) ) );
}

// ======================================================================
//  Plane T model -- TEL-004 sections 2, 3, 4.
//
//  Samples every router's occupancy on a fixed period and publishes
//  per-column and per-row 4-bit nibbles after a fixed delay. The ONLY
//  property routing depends on is that this staleness is a constant set
//  by the telemetry plane, never a function of Plane D congestion
//  (TEL-004 section 3, ROUTE-001 section 5.3).
// ======================================================================
namespace {

class SrotaTelemetry {
public:
  SrotaTelemetry() : _k(0), _period(4), _latency(8), _buf_per_port(1),
                     _routers(0), _next_sample(0) {}

  void Configure( int k, int period, int latency, int buf_per_port,
                  vector<Router *> const * routers ) {
    _k       = k;
    _period  = ( period  > 0 ) ? period  : 1;
    _latency = ( latency >= 0 ) ? latency : 0;
    _buf_per_port = ( buf_per_port > 0 ) ? buf_per_port : 1;
    _routers = routers;

    // Published vectors start at zero -- "uncongested until told
    // otherwise". At t=0 no traffic exists, so this is also the truth.
    _col_pub.assign( k, 0 );
    _row_pub.assign( k, 0 );
    _next_sample = 0;
    _pending.clear();
  }

  // Called from the FIU on every path-selection decision. Advancing the
  // model here rather than from a per-cycle hook keeps Plane T entirely
  // inside this file; the sample instants are still determined by
  // GetSimTime() and the configured period, not by how often the FIU
  // happens to ask.
  void Refresh() {
    if ( !_routers ) return;
    int const now = GetSimTime();

    // Retire every sample whose fixed transport delay has elapsed.
    while ( !_pending.empty() && _pending.front().ready <= now ) {
      _col_pub = _pending.front().col;
      _row_pub = _pending.front().row;
      _pending.pop_front();
    }

    // Take new samples on the TDM schedule. The loop (rather than a
    // single if) matters only when the FIU has not been asked for a
    // while; it keeps sample instants on the fixed grid regardless.
    while ( now >= _next_sample ) {
      _Sample( _next_sample );
      _next_sample += _period;
    }
  }

  // TEL-004 section 4: per-column and per-row aggregated load, 0-15.
  // Indexed directly by coordinate -- S-SLOT (section 2.5) makes slot
  // equal coordinate, so no translation table exists anywhere.
  int ColLoad( int x ) const {
    return ( x >= 0 && x < (int)_col_pub.size() ) ? _col_pub[x] : 0;
  }
  int RowLoad( int y ) const {
    return ( y >= 0 && y < (int)_row_pub.size() ) ? _row_pub[y] : 0;
  }

private:
  struct Sample {
    int ready;
    vector<int> col;
    vector<int> row;
  };

  void _Sample( int at ) {
    Sample s;
    s.ready = at + _latency;
    s.col.assign( _k, 0 );
    s.row.assign( _k, 0 );

    // The nibble reports PEAK queue pressure at a router: the fullest
    // input buffer, as a fraction of that buffer's capacity, quantised to
    // 0-15. Two earlier formulations were wrong, and both failed silently
    // by disabling the section 5 overlay rather than by producing a
    // visible error -- so the reasoning is recorded here.
    //
    // (a) Raw sum of GetBufferOccupancy() over all input ports, clamped
    //     at 15. An interior router has c + 2(k-1) inputs (34 at k=16,
    //     c=4), each holding num_vcs * vc_buf_size flits, so the sum
    //     reaches 15 at under 1% utilisation: the nibble reads 0 when
    //     idle and pins at 15 under any load, and no threshold setting
    //     can discriminate.
    //
    // (b) MEAN utilisation across input ports. Fails the other way. On
    //     this topology most of a router's inputs are express taps that
    //     are idle most of the time -- a router taps k-1 channels per
    //     dimension but a given flow uses one. Averaging over ~34 ports
    //     of which a handful are busy pushes the mean below any useful
    //     threshold even when the router is genuinely a bottleneck, so
    //     the overlay never fires and adaptive routing degenerates
    //     exactly to row-first.
    //
    // Peak-over-ports is what a congestion report is actually for: the
    // question the overlay asks is "is this drop point backing up",
    // and one saturated queue is a bottleneck regardless of how many
    // idle taps sit beside it. TEL-004 section 2.2 says only "coarse
    // buffer/queue occupancy", which does not settle the aggregation --
    // that ambiguity is worth closing in the spec (see TL note in
    // SROTA.md).
    vector<int> col_sum( _k, 0 ), row_sum( _k, 0 );
    vector<int> col_n( _k, 0 ), row_n( _k, 0 );

    for ( int node = 0; node < (int)_routers->size(); ++node ) {
      Router const * r = (*_routers)[node];
      if ( !r ) continue;

      int peak = 0;
      for ( int i = 0; i < r->NumInputs(); ++i ) {
        int const o = r->GetBufferOccupancy( i );
        if ( o > peak ) peak = o;
      }

      double const util = ( _buf_per_port > 0 )
          ? ( (double)peak / (double)_buf_per_port ) : 0.0;
      int nib = (int)( util * 15.0 + 0.5 );
      if ( nib > 15 ) nib = 15;

      // VC-002 section 13.3: side-buffer occupancy above
      // VC_SIDEBUF_WATERMARK raises a congestion hint on Plane T. The
      // hint reports "saturated", so it pins the nibble. A staging latch
      // is 2 flits, so the per-port reading alone swings 0 -> 15 on a
      // single flit; the watermark is the signal that means sustained
      // allocation loss.
      SrotaRouterD const * const sd = dynamic_cast<SrotaRouterD const *>( r );
      if ( sd && sd->WatermarkExceeded() ) nib = 15;

      // The LINE aggregate is a mean over the routers in that column or
      // row, not a max. TEL-004 section 4 calls it a "load vector over
      // all routers in that column", and mean is what makes it usable
      // here: a max is dominated by whichever single router is hottest,
      // and under a hot-destination pattern that router is the packet's
      // own destination -- which every path shape has to reach. Both
      // candidates then read "congested" for the same unavoidable
      // reason, and the comparison carries no information. A mean over
      // the line measures how loaded the SEGMENT is, which is the part
      // the choice of shape can actually change.
      int const x = node % _k;
      int const y = node / _k;
      col_sum[x] += nib; col_n[x]++;
      row_sum[y] += nib; row_n[y]++;
    }

    for ( int i = 0; i < _k; ++i ) {
      s.col[i] = col_n[i] ? ( col_sum[i] / col_n[i] ) : 0;
      s.row[i] = row_n[i] ? ( row_sum[i] / row_n[i] ) : 0;
    }

    _pending.push_back( s );
  }

  int _k;
  int _period;
  int _latency;
  int _buf_per_port;   // num_vcs * vc_buf_size -- per-input-port capacity
  vector<Router *> const * _routers;

  int _next_sample;
  deque<Sample> _pending;
  vector<int> _col_pub;
  vector<int> _row_pub;
};

SrotaTelemetry gSrTel;

// ======================================================================
//  FIU path selection -- ROUTE-001 section 10 (srota_fiu_pathsel) plus
//  the flow-epoch cache of section 10.4.
//
//  One cache per FIU, i.e. per source terminal. Keyed by a flow hash over
//  the (src, dest, class) triple (PKT-008 section 3.1 flow_hash). Stores
//  shape AND Valiant intermediate together -- rev 0.3's RT-R8 fix
//  (ROUTE-001 section 5.4). No stored flow identity and no identity
//  compare, so a hash collision makes the second flow adopt the first's
//  path, which section 10.4 argues is a performance failure and not a
//  correctness one.
// ======================================================================
struct SrotaFlowEntry {
  bool vld;
  int  shape;
  int  intm;       // intermediate router id; -1 when shape is not Valiant
  int  epoch_tag;
  SrotaFlowEntry() : vld(false), shape(SROTA_ROW_FIRST), intm(-1),
                     epoch_tag(-1) {}
};

class SrotaFiuPathSel {
public:
  void Configure( int nodes, int entries ) {
    _entries = ( entries > 0 ) ? entries : 1;
    _cache.assign( nodes, vector<SrotaFlowEntry>( _entries ) );
  }

  // ROUTE-001 section 10.1's FSM, collapsed to its observable effect.
  // LOOKUP -> (hit) CACHED, or (miss) TEL_RD -> SELECT. The TEL_RD and
  // INJECT stall states are timing behaviour with no effect on which
  // path is chosen, and BookSim already models injection backpressure
  // its own way, so they are not reproduced here.
  void Select( int src, int dest, int cl, int k, int c,
               int * out_shape, int * out_intm ) {

    // PKT-008 section 3.1: flow_hash identifies the source-destination-
    // class triple. 16 bits, as the field is 16 bits wide.
    unsigned h = (unsigned)src * 2654435761u
               ^ (unsigned)dest * 40503u
               ^ (unsigned)cl * 2246822519u;
    h = ( h ^ ( h >> 16 ) ) & 0xffffu;
    int const idx = (int)( h % (unsigned)_entries );

    int const epoch = GetSimTime() / gSrEpochLen;

    SrotaFlowEntry & e = _cache[src][idx];

    // Lazy epoch validity -- ROUTE-001 section 10.3. Entries are marked
    // stale by tag comparison, never actively flushed, so there is no
    // fabric-wide latency spike at an epoch boundary.
    if ( e.vld && e.epoch_tag == epoch ) {
      *out_shape = e.shape;
      *out_intm  = e.intm;
      return;
    }

    // Cache miss -> TEL_RD -> SELECT. Without Plane T there is nothing to
    // read: the published vectors stay zero, both candidates tie, and
    // selection falls to the anchored default -- a static router.
    if ( gSrPlanes & ( 1 << SROTA_PLANE_T ) ) gSrTel.Refresh();

    int const dest_router = dest / c;
    int const src_router  = src  / c;
    int const dx = dest_router % k;
    int const dy = dest_router / k;

    int shape = _ChooseShape( dx, dy, epoch );
    int intm  = -1;

    // srota_isl_route = colfirst. Island-bound flows ride the row into the
    // island column only on their last segment, so the island router is
    // the only one they transit -- I-ISL by construction. It also keeps
    // them off Valiant, whose runtime intermediate TP-V2 cannot discharge.
    // ROUTE_DEBUG_FORCE_SHAPE still wins: it is a bring-up override.
    if ( gSrForceShape < 0 && SrotaIslandBound( dest_router ) ) {
      shape = SROTA_COL_FIRST;
    }

    if ( shape == SROTA_VALIANT_L1 ) {
      // ROUTE-001 section 5.4: the intermediate is part of the path, not
      // a per-packet choice. Chosen once here, cached below, and reused
      // for every packet of this flow-epoch.
      int const nrouters = k * k;
      do {
        intm = RandomInt( nrouters - 1 );
      } while ( nrouters > 2 && ( intm == src_router || intm == dest_router ) );
    }

    e.vld       = true;
    e.shape     = shape;
    e.intm      = intm;
    e.epoch_tag = epoch;

    *out_shape = shape;
    *out_intm  = intm;
  }

private:
  // ROUTE-001 section 5.1's selection rule.
  int _ChooseShape( int dx, int dy, int epoch ) const {

    // ROUTE_DEBUG_FORCE_SHAPE (section 14.1) -- bring-up and C-model
    // cross-validation, and the mechanism for section 4.5.3 option 1.
    if ( gSrForceShape >= 0 ) return gSrForceShape;

    // srota_vc_policy = oneshape: section 4.5.3 option 1, "one shape per
    // epoch, fabric-wide." Only one turn direction exists at a time, so
    // section 4.3's argument holds unmodified. Per-flow diversity is
    // lost; temporal diversity is kept, which is exactly the trade the
    // option describes.
    if ( gSrVCPolicy == SROTA_VC_ONESHAPE ) {
      bool const row_ok = ( gSrPathEn & SROTA_EN_ROW ) != 0;
      bool const col_ok = ( gSrPathEn & SROTA_EN_COL ) != 0;
      if ( row_ok && col_ok ) return ( epoch & 1 ) ? SROTA_COL_FIRST
                                                   : SROTA_ROW_FIRST;
      return col_ok ? SROTA_COL_FIRST : SROTA_ROW_FIRST;
    }

    bool const row_en = ( gSrPathEn & SROTA_EN_ROW ) != 0;
    bool const col_en = ( gSrPathEn & SROTA_EN_COL ) != 0;
    bool const val_en = ( gSrPathEn & SROTA_EN_VALIANT ) != 0;

    // Row-first turns at (dx, sy) and then rides column dx, so its
    // candidate segment is column dx. Column-first turns at (sx, dy) and
    // rides row dy.
    int const row_load = gSrTel.ColLoad( dx );
    int const col_load = gSrTel.RowLoad( dy );

    bool const row_cong = row_load > gSrCongThresh;
    bool const col_cong = col_load > gSrCongThresh;

    // Section 5.1's rule reads as a comparison, not two independent
    // threshold tests: column-first is taken when "the row-first
    // candidate's column-drop point is congested; the column path is
    // not". Implemented literally as two absolute tests it degenerates
    // whenever both candidates sit on the same side of the threshold --
    // which is most of the time, since both segments end at the same
    // destination. So the threshold decides only whether to escape to
    // Valiant, and the choice between the two direct shapes is made by
    // comparing their candidate loads.
    if ( row_en && col_en ) {
      if ( !( row_cong && col_cong ) ) {
        if ( row_load < col_load ) return SROTA_ROW_FIRST;
        if ( col_load < row_load ) return SROTA_COL_FIRST;
        return SROTA_ROW_FIRST;          // tie -> the anchored default
      }
      // Both candidates congested: spread the load if Valiant is
      // available, else still take the less-bad of the two.
      if ( val_en ) return SROTA_VALIANT_L1;
      return ( col_load < row_load ) ? SROTA_COL_FIRST : SROTA_ROW_FIRST;
    }

    if ( row_en && !row_cong ) return SROTA_ROW_FIRST;
    if ( col_en && !col_cong ) return SROTA_COL_FIRST;
    if ( val_en )              return SROTA_VALIANT_L1;

    // Both direct candidates congested and Valiant unavailable: fall
    // back to whichever direct shape exists. Section 14.3 guarantees
    // row-first is always one of them.
    return row_en ? SROTA_ROW_FIRST : SROTA_COL_FIRST;
  }

  int _entries;
  vector<vector<SrotaFlowEntry> > _cache;
};

SrotaFiuPathSel gSrFiu;

} // namespace

// ======================================================================
//  Deterministic route compute -- ROUTE-001 section 11.1
//  (srota_route_compute). Declared in srota.hpp; see the note there on
//  why the signature carries no congestion state.
// ======================================================================

// Resolve one hop toward (tx,ty) in dimension `xdim`, from (x,y).
static void SrotaDimHop( int x, int y, int tx, int ty, bool xdim,
                         int k, int c, bool express,
                         int * out_port, int * out_drop, int * out_dir ) {
  SrotaNoC::Dir dir;
  int drop = -1;

  if ( xdim ) {
    assert( tx != x );
    if ( tx > x ) {
      dir  = SrotaNoC::SROTA_XPOS;
      // XPOS channel at x is tapped by x+1 .. k-1, in that order.
      drop = express ? ( tx - x - 1 ) : -1;
    } else {
      dir  = SrotaNoC::SROTA_XNEG;
      // XNEG channel at x is tapped by x-1 .. 0, in that order.
      drop = express ? ( x - tx - 1 ) : -1;
    }
  } else {
    assert( ty != y );
    if ( ty > y ) {
      dir  = SrotaNoC::SROTA_YPOS;
      drop = express ? ( ty - y - 1 ) : -1;
    } else {
      dir  = SrotaNoC::SROTA_YNEG;
      drop = express ? ( y - ty - 1 ) : -1;
    }
  }

  int const off = SrotaNoC::PortOffset( x, y, k, dir );
  // If this fires the builder and the routing function disagree about
  // the port map -- a bug in one of them, not a configuration problem.
  assert( off >= 0 );

  *out_port = c + off;
  *out_drop = drop;
  *out_dir  = (int)dir;
}

SrotaRouteResult SrotaRouteCompute( int my_router, int dest_terminal,
                                    int shape, int intm,
                                    int k, int c ) {
  SrotaRouteResult res;
  res.out_port  = -1;
  res.dir       = -1;
  res.drop      = -1;
  res.rank      = 0;
  res.eject     = false;
  res.turn      = 0;
  res.new_shape = shape;

  int const x = my_router % k;
  int const y = my_router / k;

  int const dest_router = dest_terminal / c;
  int const dx = dest_router % k;
  int const dy = dest_router / k;

  // ROUTE-001 section 13.4: a Valiant packet carries VALIANT_L1 until it
  // reaches its intermediate, and that router -- and only that router --
  // rewrites the shape field. This is the one place any router modifies
  // a routing field.
  if ( shape == SROTA_VALIANT_L1 && intm >= 0 && my_router == intm ) {
    shape = SROTA_VALIANT_L2;
    res.new_shape = shape;
  }

  // Section 11.1: the Valiant first leg retargets to the intermediate.
  bool const leg1 = ( shape == SROTA_VALIANT_L1 && intm >= 0 );
  int const tx = leg1 ? ( intm % k ) : dx;
  int const ty = leg1 ? ( intm / k ) : dy;

  if ( my_router == dest_router ) {
    res.eject    = true;
    res.out_port = dest_terminal % c;   // tile_within_group, section 10.1
    res.rank     = SrotaRankBase( shape ) + 1;
    return res;
  }

  // Section 11.1's row_first term: Valiant's legs are internally
  // row-first, which is why both Valiant encodings join ROW_FIRST here.
  bool const row_first = ( shape == SROTA_ROW_FIRST  ||
                           shape == SROTA_VALIANT_L1 ||
                           shape == SROTA_VALIANT_L2 );

  bool take_x;
  bool turned;
  if ( row_first ) {
    take_x = ( tx != x );
    turned = !take_x;              // X resolved -> this hop is the turn
  } else {
    take_x = ( ty == y );          // Y resolved -> turn into X
    turned = take_x;
  }

  // Guard against a degenerate target that is neither ahead in X nor Y.
  // Reachable only if the intermediate equals the current router without
  // the rewrite above having fired, which cannot happen -- assert rather
  // than route somewhere arbitrary.
  assert( take_x ? ( tx != x ) : ( ty != y ) );

  bool const express = take_x ? gSrRowExpress : gSrColExpress;
  SrotaDimHop( x, y, tx, ty, take_x, k, c, express,
               &res.out_port, &res.drop, &res.dir );

  // rc_turn_taken (ROUTE-001 section 8.2). Exists to drive the F1 turn
  // assertions of section 16.2 and, here, to label CDG edges.
  res.turn = turned ? 1 : 0;
  res.rank = SrotaRankBase( shape ) + ( turned ? 1 : 0 );
  return res;
}

// ======================================================================
//  Network construction
// ======================================================================

SrotaNoC::SrotaNoC( const Configuration &config, const string & name )
  : Network( config, name ), _plane( SROTA_PLANE_D ),
    _cfg_plane( NULL ), _cfg_phys( NULL ), _sidebuf( false )
{
  // ---- Planes (TOPO-003 sections 5, 13.2) ----
  //
  // main.cpp names subnet i "network_i". D is mandatory and always subnet
  // 0; C, when present, is subnet 1. T is not a packet network here --
  // it is the telemetry model Plane D's overlay reads -- so it takes no
  // subnet.
  int const planes = config.GetInt( "srota_planes" );
  if ( !( planes & ( 1 << SROTA_PLANE_D ) ) ) {
    std::cerr << "Srota config error: srota_planes=0x" << std::hex << planes
              << std::dec << " lacks Plane D (bit 0). TOPO-003 section 5: "
              << "D is mandatory; C and T are optional." << std::endl;
    exit( -1 );
  }
  bool const has_c = ( planes & ( 1 << SROTA_PLANE_C ) ) != 0;
  int const want_subnets = has_c ? 2 : 1;
  if ( config.GetInt( "subnets" ) != want_subnets ) {
    std::cerr << "Srota config error: srota_planes=0x" << std::hex << planes
              << std::dec << " carries " << want_subnets << " packet plane(s) "
              << "(D" << ( has_c ? " and C" : "" ) << "), so subnets must be "
              << want_subnets << "; got " << config.GetInt( "subnets" )
              << ". Use class_subnet to put each traffic class on its plane."
              << std::endl;
    exit( -1 );
  }

  int subnet = 0;
  size_t const us = name.rfind( '_' );
  if ( us != string::npos ) subnet = atoi( name.c_str() + us + 1 );
  _plane = ( subnet == 1 ) ? SROTA_PLANE_C : SROTA_PLANE_D;

  if ( _plane == SROTA_PLANE_C ) {
    _ComputeSizePlaneC( config );
    _Alloc();
    _BuildNet( config );
    return;
  }

  gSrPlanes = planes;
  gSrPlaneCSubnet = has_c ? 1 : -1;

  _ComputeSize( config );
  _Alloc();
  _BuildNet( config );

  // Both elaboration-time obligations, run in the order the specs assign
  // them: F1 (ROUTE-001 section 4.4) then TP-V2 (TOPO-003 section 15).
  int const cdg_radix = config.GetInt( "srota_cdg_radix" );
  if ( cdg_radix >= 2 ) _CheckCDG( cdg_radix );
  _CheckIslandPlacement();
}

SrotaNoC::~SrotaNoC() {
  if ( _plane == SROTA_PLANE_D && _sidebuf ) _ReportPlaneD();
  // _cfg_plane / _cfg_phys are not freed: the routers hold references to
  // them and are deleted by ~Network, which runs after this body.
}

// End-of-run counters, in the names of the registers they model. The
// "SrotaStats:" prefix is what tracks/t3-topology/scripts parse.
void SrotaNoC::_ReportPlaneD() const {
  long fill = 0, drain = 0, full = 0, reject = 0, wm = 0, occ = 0, cyc = 0;
  long losses = 0;
  int peak = 0, storage = 0;
  vector<long> arr, grant, defer, defer_cyc;

  for ( size_t i = 0; i < _routers.size(); ++i ) {
    SrotaRouterD const * const r = dynamic_cast<SrotaRouterD const *>( _routers[i] );
    if ( !r ) continue;
    SrotaRouterDStats const & s = r->Stats();
    fill += s.sb_fill; drain += s.sb_drain; full += s.sb_full_cyc;
    reject += s.sb_full_reject; wm += s.sb_wm_cyc; occ += s.sb_occ_sum;
    cyc += s.cycles; losses += s.alloc_losses;
    if ( s.sb_peak > peak ) peak = s.sb_peak;
    storage += r->StorageFlits();
    if ( r->IsIsland() ) {
      if ( arr.size() < s.isl_arrive.size() ) {
        arr.resize( s.isl_arrive.size(), 0 );
        grant.resize( s.isl_arrive.size(), 0 );
        defer.resize( s.isl_arrive.size(), 0 );
        defer_cyc.resize( s.isl_arrive.size(), 0 );
      }
      for ( size_t q = 0; q < s.isl_arrive.size(); ++q ) {
        arr[q] += s.isl_arrive[q];     grant[q] += s.isl_grant[q];
        defer[q] += s.isl_defer[q];    defer_cyc[q] += s.isl_defer_cyc[q];
      }
    }
  }

  std::cout << "SrotaStats: sidebuf routers=" << _routers.size()
            << " storage_flits=" << storage
            << " alloc_loss=" << losses
            << " sb_fill=" << fill << " sb_drain=" << drain
            << " sb_full_reject=" << reject
            << " sb_peak=" << peak
            << " sb_mean_occ_per_router=" << ( cyc ? (double)occ / (double)cyc : 0.0 )
            << " sb_full_router_cycles=" << full
            << " sb_watermark_router_cycles=" << wm
            << " router_cycles=" << cyc
            << "  (whole run, incl. warm-up)" << std::endl;

  for ( size_t q = 0; q < arr.size(); ++q ) {
    if ( !arr[q] && !defer[q] ) continue;
    std::cout << "SrotaStats: island class=" << q
              << " arrive=" << arr[q] << " grant=" << grant[q]
              << " deferred_flits=" << defer[q]
              << " defer_flit_cycles=" << defer_cyc[q] << std::endl;
  }
}

// BookSim looks routing functions up as "<routing_function>_<topology>",
// so `routing_function = o1turn;` with `topology = srota;` lands here.
void SrotaNoC::RegisterRoutingFunctions() {
  gRoutingFunctionMap["o1turn_srota"] = &srota_o1turn;
  gRoutingFunctionMap["xy_srota"]     = &srota_planec_xy;
}

// One router of this plane. Plane C and a VC-buffered Plane D go through
// the stock factory with the plane's configuration; a side-buffered Plane
// D router is built directly, because its storage model needs two
// configurations (physical and advertised) that the factory cannot pass.
Router * SrotaNoC::_NewRouter( const Configuration &config,
                               string const & name, int node,
                               int in, int out ) {
  Configuration const & pc = _cfg_plane ? *_cfg_plane : config;

  if ( _plane == SROTA_PLANE_D && _sidebuf ) {
    SrotaRouterDParams p;
    p.sb_depth     = config.GetInt( "srota_sb_depth" );
    p.sb_watermark = config.GetInt( "srota_sb_watermark" );
    p.local_ports  = _c;
    p.island       = ( _island_col_map & ( 1 << ( node % _k ) ) ) != 0;
    p.isl_rate     = config.GetFloatArray( "srota_isl_rate" );
    if ( p.isl_rate.empty() ) {
      p.isl_rate.push_back( config.GetFloat( "srota_isl_rate" ) );
    }
    p.isl_burst    = config.GetInt( "srota_isl_burst" );
    p.isl_class_is_slack = ( config.GetStr( "srota_isl_class" ) == "slack" );
    return new SrotaRouterD( *_cfg_phys, pc, this, name, node, in, out, p );
  }
  return Router::NewRouter( pc, this, name, node, in, out );
}

// Plane C (VC-002 section 3): the SR-C control plane. A conventional
// VC-buffered router on a plain mesh -- no express layer, no side buffer,
// no islands -- with REQ/RSP/SNP on three independent VCs, and plain XY.
// Same k x k grid and concentration as Plane D, because both planes
// serve the same tiles (the node count must match across subnets).
void SrotaNoC::_ComputeSizePlaneC( const Configuration &config ) {
  _k = config.GetInt( "k" );
  _c = config.GetInt( "c" );
  _row_express = false;
  _col_express = false;
  _drop_latency = 1;
  _island_col_map = 0;

  int const vcs = config.GetInt( "srota_planec_vcs" );
  int const depth = config.GetInt( "srota_planec_vc_buf" );
  if ( vcs < 1 || vcs > config.GetInt( "num_vcs" ) ) {
    std::cerr << "Srota config error: srota_planec_vcs=" << vcs << " must be "
              << "1.." << config.GetInt( "num_vcs" ) << " (num_vcs is the "
              << "traffic manager's VC space and must cover every plane)."
              << std::endl;
    exit( -1 );
  }
  if ( config.GetInt( "vc_buf_size" ) > depth ) {
    // The injecting terminal's credit window is the global vc_buf_size,
    // for every subnet. Deeper than Plane C's VCs would overflow them.
    std::cerr << "Srota config error: vc_buf_size=" << config.GetInt( "vc_buf_size" )
              << " exceeds srota_planec_vc_buf=" << depth << ". Terminals "
              << "inject against the global vc_buf_size on every plane."
              << std::endl;
    exit( -1 );
  }

  _cfg_plane = new Configuration( config );
  _cfg_plane->Assign( "num_vcs", vcs );
  _cfg_plane->Assign( "vc_buf_size", depth );
  _cfg_plane->Assign( "buf_size", -1 );
  _cfg_plane->Assign( "routing_function", string( "xy" ) );

  gSrPlaneCVCs = vcs;

  _size  = _k * _k;
  _nodes = _size * _c;
  _channels = 4 * _k * ( _k - 1 );
  _next_p2p = 0;

  std::cout << "Srota Plane C: k=" << _k << " c=" << _c
            << " mesh, XY, " << vcs << " VCs (REQ/RSP/SNP) x " << depth
            << " flits, subnet 1" << std::endl;
}

bool SrotaNoC::DirPresent( int x, int y, int k, Dir dir ) {
  switch ( dir ) {
    case SROTA_XNEG: return x > 0;
    case SROTA_XPOS: return x < k - 1;
    case SROTA_YNEG: return y > 0;
    case SROTA_YPOS: return y < k - 1;
  }
  return false;
}

int SrotaNoC::PortOffset( int x, int y, int k, Dir dir ) {
  if ( !DirPresent( x, y, k, dir ) ) return -1;
  int off = 0;
  for ( int d = 0; d < 4; ++d ) {
    Dir const cand = (Dir)d;
    if ( cand == dir ) return off;
    if ( DirPresent( x, y, k, cand ) ) ++off;
  }
  return -1;
}

int SrotaNoC::DirDegreeAt( int x, int y, int k ) {
  int n = 0;
  for ( int d = 0; d < 4; ++d ) {
    if ( DirPresent( x, y, k, (Dir)d ) ) ++n;
  }
  return n;
}

void SrotaNoC::_ComputeSize( const Configuration &config ) {

  _k = config.GetInt( "k" );
  _c = config.GetInt( "c" );

  assert( _k >= 2 );
  assert( _c >= 1 );

  // TOPO-003 section 5: validated envelope is k 4-32, c 1-8. Warn rather
  // than refuse outside it -- an ablation study at k=2 is legitimate,
  // it just is not a configuration the spec claims to have validated.
  if ( _k < 4 || _k > 32 ) {
    std::cerr << "Srota warning: k=" << _k << " is outside TOPO-003 "
              << "section 5's validated envelope (4-32). Continuing."
              << std::endl;
  }
  if ( _c > 8 ) {
    std::cerr << "Srota warning: c=" << _c << " is outside TOPO-003 "
              << "section 5's validated envelope (1-8). Continuing."
              << std::endl;
  }
  if ( _k > 16 ) {
    // TOPO-003 section 6.2 / risk T-R1: beyond radix 16 a single-driver
    // channel spanning the dimension may need repeater insertion, and
    // the fallback is a 2-cycle drop.
    std::cerr << "Srota note: k=" << _k << " > 16 is past the MECS "
              << "repeater boundary (TOPO-003 section 6.2, risk T-R1). "
              << "Consider srota_drop_latency=2 to model the repeatered "
              << "fallback." << std::endl;
  }

  // TOPO_MECS_ENABLE -- TOPO-003 section 13.2, bit 0 row, bit 1 column.
  int const mecs = config.GetInt( "srota_mecs" );
  _row_express = ( mecs & 0x1 ) != 0;
  _col_express = ( mecs & 0x2 ) != 0;

  _drop_latency = config.GetInt( "srota_drop_latency" );
  if ( _drop_latency < 1 ) _drop_latency = 1;
  if ( _drop_latency > 2 ) {
    std::cerr << "Srota config error: srota_drop_latency must be 1 or 2 "
              << "(TOPO_DROP_LATENCY, TOPO-003 section 13.2); got "
              << _drop_latency << "." << std::endl;
    exit( -1 );
  }

  _island_col_map = config.GetInt( "srota_island_col_map" );

  // TOPO-003 section 4.4: islands require the express layer. Without
  // express reach a route to an island column traverses arbitrary
  // routers, every one of which would have to be QoS-aware for I-ISL to
  // hold -- precisely the cost confinement exists to avoid. The
  // generator rejects the combination at elaboration; so does this.
  if ( _island_col_map != 0 && !( _row_express && _col_express ) ) {
    std::cerr << "Srota config error: srota_island_col_map != 0 with MECS "
              << "disabled on a dimension is not a legal configuration "
              << "(TOPO-003 section 4.4). The MECS-off ablation baseline "
              << "is a zero-island configuration." << std::endl;
    exit( -1 );
  }

  // ---- routing configuration ----
  gSrPathEn     = config.GetInt( "srota_path_en" );
  gSrCongThresh = config.GetInt( "srota_cong_thresh" );
  gSrEpochLen   = config.GetInt( "srota_epoch_len" );
  if ( gSrEpochLen < 1 ) gSrEpochLen = 1;
  gSrFlowCacheSz = config.GetInt( "srota_flow_cache_size" );

  // ROUTE-001 section 14.3: ROUTE_PATH_EN can never be all-zero, and
  // row-first must remain enabled because every deadlock and ordering
  // proof is anchored to it.
  if ( ( gSrPathEn & SROTA_EN_ROW ) == 0 ) {
    std::cerr << "Srota config error: srota_path_en must always include "
              << "row-first (bit 0). ROUTE-001 section 14.3: every "
              << "deadlock and ordering proof is anchored to it. Got 0x"
              << std::hex << gSrPathEn << std::dec << "." << std::endl;
    exit( -1 );
  }

  // ROUTE-001 section 14.3 / constraint C1: a shape depending on a
  // dimension's express reach is forced off when that express is off.
  // With a dimension in mesh mode the shapes still route correctly (the
  // walk is just multi-hop), so this is a note rather than a refusal --
  // but column-first over a mesh column is not what the spec's shape is,
  // and a reader comparing numbers needs to know.
  if ( ( !_row_express || !_col_express ) &&
       ( gSrPathEn & ( SROTA_EN_COL | SROTA_EN_VALIANT ) ) ) {
    std::cerr << "Srota note: MECS is off on a dimension, so column-first "
              << "and Valiant paths traverse it as multi-hop mesh walks "
              << "rather than single express segments. Hop-count and "
              << "latency figures are not comparable with the "
              << "express-on configuration." << std::endl;
  }

  // ---- VC policy (srota.hpp design note section 3) ----
  string const pol = config.GetStr( "srota_vc_policy" );
  if      ( pol == "none"     ) gSrVCPolicy = SROTA_VC_NONE;
  else if ( pol == "shape"    ) gSrVCPolicy = SROTA_VC_SHAPE;
  else if ( pol == "rank"     ) gSrVCPolicy = SROTA_VC_RANK;
  else if ( pol == "oneshape" ) gSrVCPolicy = SROTA_VC_ONESHAPE;
  else {
    std::cerr << "Srota config error: srota_vc_policy=\"" << pol
              << "\" unknown. Expected one of: none, shape, rank, "
              << "oneshape (see the design note in srota.hpp)."
              << std::endl;
    exit( -1 );
  }

  bool const valiant_en = ( gSrPathEn & SROTA_EN_VALIANT ) != 0;

  switch ( gSrVCPolicy ) {
    case SROTA_VC_NONE:
      gSrVCSets = 1;
      break;
    case SROTA_VC_SHAPE:
      // Two sets: XY and YX. Valiant turns twice (row->col reaching the
      // intermediate, then col->row starting the second leg), so it is
      // NOT safe inside the XY set despite each of its legs being
      // internally row-first. Refuse rather than silently mis-model.
      if ( valiant_en ) {
        std::cerr << "Srota config error: srota_vc_policy=shape cannot "
                  << "carry Valiant paths. A Valiant path turns twice, so "
                  << "it contributes a column->row edge to the XY set and "
                  << "breaks the very separation this policy provides. "
                  << "Use srota_vc_policy=rank, or clear bit 2 of "
                  << "srota_path_en." << std::endl;
        exit( -1 );
      }
      gSrVCSets = 2;
      break;
    case SROTA_VC_RANK:
      gSrVCSets = valiant_en ? 4 : 2;
      break;
    case SROTA_VC_ONESHAPE:
      // Section 4.5.3 option 1 keeps the two DIRECT shapes and alternates
      // between them by epoch. Valiant closes a cycle on its own (two
      // turns) and cannot be the fabric-wide shape.
      if ( valiant_en ) {
        std::cerr << "Srota config error: srota_vc_policy=oneshape is "
                  << "ROUTE-001 section 4.5.3 option 1, which alternates "
                  << "the two direct shapes by epoch. Valiant turns twice "
                  << "and closes a cycle by itself, so it cannot be the "
                  << "fabric-wide shape. Clear bit 2 of srota_path_en."
                  << std::endl;
        exit( -1 );
      }
      gSrVCSets = 1;
      break;
  }

  int num_vcs = config.GetInt( "num_vcs" );
  int const d_vcs = config.GetInt( "srota_d_num_vcs" );
  if ( d_vcs > 0 ) {
    if ( d_vcs > num_vcs ) {
      std::cerr << "Srota config error: srota_d_num_vcs=" << d_vcs
                << " exceeds num_vcs=" << num_vcs << "; num_vcs is the "
                << "traffic manager's VC space and must cover every plane."
                << std::endl;
      exit( -1 );
    }
    num_vcs = d_vcs;
  }
  gSrDVCs = num_vcs;

  if ( num_vcs < gSrVCSets ) {
    std::cerr << "Srota config error: srota_vc_policy=" << pol
              << " with srota_path_en=0x" << std::hex << gSrPathEn
              << std::dec << " needs num_vcs >= " << gSrVCSets
              << " (one disjoint VC set per partition); got "
              << num_vcs << "." << std::endl;
    exit( -1 );
  }

  // ROUTE_DEBUG_FORCE_SHAPE -- section 14.1. -1 disables.
  gSrForceShape = config.GetInt( "srota_force_shape" );
  if ( gSrForceShape > 3 ) {
    std::cerr << "Srota config error: srota_force_shape must be -1 "
              << "(disabled) or 0..3." << std::endl;
    exit( -1 );
  }

  // MECS taps cannot be resolved by lookahead routing: IQRouter's
  // lookahead path finds the next hop through FlitChannel::GetSink(),
  // which only remembers a multidrop channel's last-registered tap, not
  // the tap a given flit is addressed to. Same refusal, same reason, as
  // GEC's d>1 case.
  if ( ( _row_express || _col_express ) &&
       config.GetInt( "routing_delay" ) == 0 ) {
    std::cerr << "Srota config error: MECS express channels require "
              << "routing_delay > 0. Lookahead routing resolves the next "
              << "hop via FlitChannel::GetSink(), which cannot "
              << "distinguish a multidrop channel's taps." << std::endl;
    exit( -1 );
  }

  // This model hardcodes channel latency (1 cycle, or srota_drop_latency
  // on express channels) and has no wire-length model, so silently
  // honouring use_noc_latency would produce latency numbers that do not
  // mean what the caller asked for. Same policy GEC already applies.
  if ( config.GetInt( "use_noc_latency" ) != 0 ) {
    std::cerr << "Srota config error: use_noc_latency=1 (it defaults to "
              << "1) requested, but this model has no wire-length latency "
              << "model. Express channels are priced at "
              << "srota_drop_latency cycles and mesh links at 1. Set "
              << "use_noc_latency=0 explicitly." << std::endl;
    exit( -1 );
  }

  // ---- QoS island routing rule ----
  string const isl_route = config.GetStr( "srota_isl_route" );
  if ( isl_route == "colfirst" ) {
    gSrIslColFirst = true;
  } else if ( isl_route != "any" ) {
    std::cerr << "Srota config error: srota_isl_route=\"" << isl_route
              << "\" unknown. Expected any or colfirst." << std::endl;
    exit( -1 );
  }
  if ( gSrIslColFirst && _island_col_map == 0 ) {
    std::cerr << "Srota note: srota_isl_route=colfirst with no island "
              << "columns has nothing to route." << std::endl;
  }

  // ---- Plane D router ----
  string const rtr = config.GetStr( "srota_router" );
  if ( rtr == "sidebuf" ) {
    _sidebuf = true;
  } else if ( rtr != "iq" ) {
    std::cerr << "Srota config error: srota_router=\"" << rtr
              << "\" unknown. Expected iq or sidebuf." << std::endl;
    exit( -1 );
  }

  if ( _sidebuf || d_vcs > 0 ) {
    _cfg_plane = new Configuration( config );
    _cfg_plane->Assign( "num_vcs", num_vcs );
  }
  if ( _sidebuf ) {
    int const sb = config.GetInt( "srota_sb_depth" );
    if ( sb < 1 ) {
      std::cerr << "Srota config error: srota_sb_depth must be >= 1 (VC-002 "
                << "section 13.6 range is 4-16)." << std::endl;
      exit( -1 );
    }
    if ( config.GetInt( "buf_size" ) > 0 ) {
      std::cerr << "Srota config error: srota_router=sidebuf sizes storage "
                << "from vc_buf_size (the staging window) and srota_sb_depth; "
                << "unset buf_size." << std::endl;
      exit( -1 );
    }
    // Physical input storage: the advertised staging window plus the one
    // side-buffer entry a VC can hold (a captured flit stays at the front
    // of its FIFO, so at most one per VC -- see srota_router_d.hpp). The
    // shared depth srota_sb_depth is enforced by the router, not here.
    _cfg_phys = new Configuration( *_cfg_plane );
    _cfg_phys->Assign( "vc_buf_size", config.GetInt( "vc_buf_size" ) + 1 );
  }

  gSrK          = _k;
  gSrC          = _c;
  gSrRowExpress = _row_express;
  gSrColExpress = _col_express;
  gSrIslandColMap = _island_col_map;

  gK = _k;
  gN = 2;
  gC = _c;

  _size  = _k * _k;
  _nodes = _size * _c;

  // Point-to-point channels are needed only for dimensions running in
  // mesh mode; express dimensions live entirely in _md_chan.
  int p2p = 0;
  if ( !_row_express ) p2p += 2 * _k * ( _k - 1 );   // both directions
  if ( !_col_express ) p2p += 2 * _k * ( _k - 1 );
  _channels = p2p;
  _next_p2p = 0;

  gSrFiu.Configure( _nodes, gSrFlowCacheSz );
  gSrTel.Configure( _k,
                    config.GetInt( "srota_tel_period" ),
                    config.GetInt( "srota_tel_latency" ),
                    num_vcs * config.GetInt( "vc_buf_size" ),
                    &_routers );

  _PrintConfigBanner( num_vcs, pol );
}

// The banner is printed unconditionally, not behind a debug flag,
// because the two things most easily got wrong about a Srota run are
// (a) whether express is actually on, and (b) which RT-R7 configuration
// is being exercised. Both belong in the log of every run.
void SrotaNoC::_PrintConfigBanner( int num_vcs, string const & pol ) const {

  int const interior_out = _c + DirDegreeAt( _k / 2, _k / 2, _k );
  int const express_dims = ( _row_express ? 1 : 0 ) + ( _col_express ? 1 : 0 );
  int const interior_in  = _c
      + ( _row_express ? ( _k - 1 ) : ( ( _k > 2 ) ? 2 : 1 ) )
      + ( _col_express ? ( _k - 1 ) : ( ( _k > 2 ) ? 2 : 1 ) );

  std::cout << "Srota: k=" << _k << " c=" << _c
            << " routers=" << ( _k * _k )
            << " tiles=" << ( _k * _k * _c )
            << " | MECS row=" << ( _row_express ? "on" : "off" )
            << " col=" << ( _col_express ? "on" : "off" )
            << " drop_latency=" << _drop_latency
            << " | interior ports out=" << interior_out
            << " in=" << interior_in
            << std::endl;

  std::cout << "Srota: max network hops = "
            << ( express_dims == 2 ? 2 : ( express_dims == 1 ? ( 1 + _k - 1 )
                                                             : 2 * ( _k - 1 ) ) )
            << ( express_dims == 2
                 ? "  (TOPO-003 section 3.2 reach guarantee: <=2)"
                 : "  (MECS off on a dimension -- reach guarantee does NOT hold)" )
            << std::endl;

  // ROUTE-001 section 4.5.4 asks three questions about how the F1 model
  // check was run. Answer them from the configuration, every run, so a
  // result can never be quoted without its RT-R7 context.
  bool const row_en = ( gSrPathEn & SROTA_EN_ROW ) != 0;
  bool const col_en = ( gSrPathEn & SROTA_EN_COL ) != 0;
  bool const val_en = ( gSrPathEn & SROTA_EN_VALIANT ) != 0;

  std::cout << "Srota: planes=0x" << std::hex << gSrPlanes << std::dec << " ("
            << "D" << ( ( gSrPlanes & ( 1 << SROTA_PLANE_C ) ) ? "+C" : "" )
            << ( ( gSrPlanes & ( 1 << SROTA_PLANE_T ) ) ? "+T" : "" ) << ")"
            << "  plane-D router=" << ( _sidebuf ? "sidebuf" : "iq" );
  if ( _sidebuf ) {
    std::cout << " (staging " << ( _cfg_plane ? _cfg_plane->GetInt( "vc_buf_size" ) : 0 )
              << " flits/VC, shared side buffer "
              << ( _cfg_plane ? _cfg_plane->GetInt( "srota_sb_depth" ) : 0 )
              << " flits/router)";
  }
  std::cout << "  islands=0x" << std::hex << _island_col_map << std::dec
            << " isl_route=" << ( gSrIslColFirst ? "colfirst" : "any" )
            << std::endl;
  if ( !( gSrPlanes & ( 1 << SROTA_PLANE_T ) ) ) {
    std::cout << "Srota: no Plane T -- the injection-time overlay has no "
              << "congestion input, so path selection is static (row-first "
              << "unless a shape is forced)." << std::endl;
  }

  std::cout << "Srota: ROUTE_PATH_EN=0x" << std::hex << gSrPathEn << std::dec
            << " (row" << ( row_en ? "+" : "-" )
            << " col" << ( col_en ? "+" : "-" )
            << " valiant" << ( val_en ? "+" : "-" ) << ")"
            << "  vc_policy=" << pol
            << " vc_sets=" << gSrVCSets << "/" << num_vcs
            << std::endl;

  if ( gSrVCPolicy == SROTA_VC_NONE && row_en && col_en ) {
    std::cout << "Srota: *** RT-R7 REPRODUCER CONFIG ***  Both direct "
              << "shapes are live on a shared VC set -- ROUTE-001 section "
              << "4.5's path-shape mixing hazard is UNMITIGATED by "
              << "construction. A hang here is the expected result, not a "
              << "simulator bug. This is the run section 4.5.4 asks for."
              << std::endl;
  } else if ( gSrVCPolicy == SROTA_VC_NONE && !col_en ) {
    std::cout << "Srota: note -- vc_policy=none with only row-first "
              << "enabled is the configuration ROUTE-001 section 4.5.4 "
              << "warns 'has not tested the shipping default'. It is "
              << "deadlock-free for the uninteresting reason that only "
              << "one turn direction exists." << std::endl;
  }
}

void SrotaNoC::_BuildNet( const Configuration &config ) {

  ostringstream name;

  // ---- Pass 1: routers and their local terminal ports ----
  //
  // Every router's c injection/ejection ports are added FIRST, for every
  // router, before any dimension port. That is what makes in_channel < c
  // mean "this flit was injected here" at every router in the fabric,
  // which the routing function relies on.
  for ( int node = 0; node < _size; ++node ) {

    int const x = node % _k;
    int const y = node / _k;

    int const deg = DirDegreeAt( x, y, _k );

    // Out-degree: c local + one port per present direction.
    int const degree_out = _c + deg;

    // In-degree: c local, plus taps. An express dimension makes this
    // router a tap on every other router's channel in that line (k-1);
    // a mesh dimension gives it one input per present direction in that
    // dimension.
    int mesh_x_in = 0, mesh_y_in = 0;
    if ( DirPresent( x, y, _k, SROTA_XNEG ) ) ++mesh_x_in;
    if ( DirPresent( x, y, _k, SROTA_XPOS ) ) ++mesh_x_in;
    if ( DirPresent( x, y, _k, SROTA_YNEG ) ) ++mesh_y_in;
    if ( DirPresent( x, y, _k, SROTA_YPOS ) ) ++mesh_y_in;

    int const degree_in = _c
        + ( _row_express ? ( _k - 1 ) : mesh_x_in )
        + ( _col_express ? ( _k - 1 ) : mesh_y_in );

    name << "srota_router_" << y << '_' << x;
    _routers[node] = _NewRouter( config, name.str(), node,
                                 degree_in, degree_out );
    _timed_modules.push_back( _routers[node] );
    name.str("");

    for ( int t = 0; t < _c; ++t ) {
      int const term = node * _c + t;

      _inject[term]->SetLatency( 1 );
      _inject_cred[term]->SetLatency( 1 );
      _eject[term]->SetLatency( 1 );
      _eject_cred[term]->SetLatency( 1 );

      _routers[node]->AddInputChannel( _inject[term], _inject_cred[term] );
      _routers[node]->AddOutputChannel( _eject[term], _eject_cred[term] );
    }
  }

  // ---- Pass 2: X dimension ----
  if ( _row_express ) _BuildExpressDim( true );
  else                _BuildMeshDim( true );

  // ---- Pass 3: Y dimension ----
  if ( _col_express ) _BuildExpressDim( false );
  else                _BuildMeshDim( false );
}

// TOPO-003 sections 3.1, 7.4, 11.1. One MultiDropChannel per (driver,
// direction): a single electrical driver, passive taps at every router
// along the span. Taps are registered in coordinate order outward from
// the driver, so tap index i is the router i+1 steps away -- which is
// exactly the drop index SrotaDimHop computes. Construction and routing
// therefore cannot disagree, the same discipline PortOffset enforces for
// ports.
void SrotaNoC::_BuildExpressDim( bool xdim ) {

  Dir const pos = xdim ? SROTA_XPOS : SROTA_YPOS;
  Dir const neg = xdim ? SROTA_XNEG : SROTA_YNEG;

  for ( int line = 0; line < _k; ++line ) {      // row y, or column x
    for ( int a = 0; a < _k; ++a ) {             // driver position

      int const src_node = xdim ? ( line * _k + a ) : ( a * _k + line );
      int const sx = src_node % _k;
      int const sy = src_node / _k;

      for ( int s = 0; s < 2; ++s ) {
        Dir const dir = ( s == 0 ) ? neg : pos;
        if ( !DirPresent( sx, sy, _k, dir ) ) continue;

        int const step  = ( dir == pos ) ? 1 : -1;
        int const ntaps = ( dir == pos ) ? ( _k - 1 - a ) : a;
        assert( ntaps >= 1 );

        ostringstream cn;
        cn << "srota_" << ( xdim ? "row" : "col" ) << "_l" << line
           << "_a" << a << ( ( dir == pos ) ? "_pos" : "_neg" );
        MultiDropChannel * fchan =
            new MultiDropChannel( this, cn.str(), _classes );
        cn.str("");
        cn << "srota_" << ( xdim ? "row" : "col" ) << "_cred_l" << line
           << "_a" << a << ( ( dir == pos ) ? "_pos" : "_neg" );
        MultiDropCreditChannel * cchan =
            new MultiDropCreditChannel( this, cn.str() );

        // TOPO-003 section 6.2 / section 9.5: the repeatered fallback
        // costs one extra cycle per express segment.
        fchan->SetLatency( _drop_latency );
        cchan->SetLatency( _drop_latency );

        _timed_modules.push_back( fchan );
        _timed_modules.push_back( cchan );
        _md_chan.push_back( fchan );
        _md_chan_cred.push_back( cchan );

        // Taps, in order outward from the driver. Tap index == distance
        // along the channel minus one == SrotaDimHop's drop.
        for ( int t = 1; t <= ntaps; ++t ) {
          int const b = a + step * t;
          int const dst_node = xdim ? ( line * _k + b ) : ( b * _k + line );
          _routers[dst_node]->AddMultiDropInputChannel( fchan, cchan );
        }

        // The single driver, registered last so NumSinks() is final --
        // this is TOPO-003 section 7.2's "exactly one driver per segment
        // per direction", the premise F1 rests on.
        _routers[src_node]->AddMultiDropOutputChannel( fchan, cchan );
      }
    }
  }
}

// MECS-off ablation baseline (TOPO-003 section 5): a dimension reverts to
// plain nearest-neighbour links. Port assignment uses the same
// PortOffset() as express mode, so the port map keeps its shape.
void SrotaNoC::_BuildMeshDim( bool xdim ) {

  Dir const pos = xdim ? SROTA_XPOS : SROTA_YPOS;
  Dir const neg = xdim ? SROTA_XNEG : SROTA_YNEG;

  for ( int line = 0; line < _k; ++line ) {
    for ( int a = 0; a + 1 < _k; ++a ) {

      int const lo_node = xdim ? ( line * _k + a )       : ( a * _k + line );
      int const hi_node = xdim ? ( line * _k + a + 1 )   : ( ( a + 1 ) * _k + line );

      // Two directed channels per adjacent pair.
      for ( int s = 0; s < 2; ++s ) {
        int const src = ( s == 0 ) ? lo_node : hi_node;
        int const dst = ( s == 0 ) ? hi_node : lo_node;
        Dir const dir = ( s == 0 ) ? pos : neg;
        (void)dir;

        int const idx = _next_p2p++;
        assert( idx < _channels );

        _chan[idx]->SetLatency( 1 );
        _chan_cred[idx]->SetLatency( 1 );

        _routers[src]->AddOutputChannel( _chan[idx], _chan_cred[idx] );
        _routers[dst]->AddInputChannel( _chan[idx], _chan_cred[idx] );
      }
    }
  }
}

// ======================================================================
//  TP-V2 -- island placement invariant I-ISL (TOPO-003 sections 4.1, 15)
//
//  "For every tile t and every shared resource r, every legal route from
//  t to r contains exactly one island router, and that island router is
//  the final router before r's attach queue."
//
//  Checked here by route enumeration over the emitted structure, which is
//  what section 15 asks a generator to do. Shared resources are taken to
//  attach at the island columns themselves (TOPO-003 section 4.3: islands
//  sit in the column adjacent to the HBM/UCIe attach points), so the
//  check reduces to: for every source tile and every destination router
//  in an island column, every shape-legal route touches exactly one
//  island-column router, and it is the last one.
// ======================================================================
void SrotaNoC::_CheckIslandPlacement() const {

  if ( _island_col_map == 0 ) {
    // TOPO-003 section 4.4's legal degenerate case: a single-tenant part
    // where guarantees degrade to best-effort under credit flow control.
    return;
  }

  // Per-shape violation counts. Which shape violates is the whole point:
  // if one shape is clean and another is not, the answer is a routing
  // rule for island-bound traffic (ROUTE-001 section 13.1) rather than a
  // different island map.
  int viol[2]  = { 0, 0 };
  int total[2] = { 0, 0 };
  int first_src[2] = { -1, -1 }, first_dst[2] = { -1, -1 }, first_via[2] = { -1, -1 };

  // Enumerate every (source router, island-column destination router)
  // pair and every enabled direct shape. Valiant is excluded on purpose:
  // its intermediate is chosen at runtime, so I-ISL cannot be discharged
  // structurally for it -- which is itself a finding, reported below.
  for ( int src = 0; src < _size; ++src ) {
    for ( int dst = 0; dst < _size; ++dst ) {
      int const dcol = dst % _k;
      if ( !( _island_col_map & ( 1 << dcol ) ) ) continue;   // not a resource
      if ( src == dst ) continue;

      for ( int shape = 0; shape <= 1; ++shape ) {
        if ( gSrIslColFirst ) {
          // The island routing rule is the only shape these flows take.
          if ( shape != SROTA_COL_FIRST ) continue;
        } else {
          if ( shape == 0 && !( gSrPathEn & SROTA_EN_ROW ) ) continue;
          if ( shape == 1 && !( gSrPathEn & SROTA_EN_COL ) ) continue;
        }

        ++total[shape];

        // Walk the route and count island routers the packet TRANSITS.
        // The source router is excluded: a packet injected there is not
        // routed through that island's regulator toward the resource,
        // it originates behind it (TOPO-003 section 7.5 -- the wrapper
        // sits between the channel drop and the resource attach queue,
        // not on a local injection that leaves over an express channel).
        // The destination is excluded too: it is the one island I-ISL
        // permits, and requiring it to be last is what the loop's exit
        // condition already encodes.
        int cur = src;
        int islands_on_path = 0;
        int via = -1;
        int guard = 4 * _k + 4;

        while ( cur != dst && guard-- > 0 ) {
          SrotaRouteResult const rr =
              SrotaRouteCompute( cur, dst * _c, shape, -1, _k, _c );
          cur = _NextRouterFor( cur, rr );
          if ( cur < 0 || cur == dst ) break;
          if ( _island_col_map & ( 1 << ( cur % _k ) ) ) {
            ++islands_on_path;
            if ( via < 0 ) via = cur;
          }
        }

        if ( islands_on_path != 0 ) {
          if ( viol[shape] == 0 ) {
            first_src[shape] = src; first_dst[shape] = dst; first_via[shape] = via;
          }
          ++viol[shape];
        }
      }
    }
  }

  static const char * shape_name[2] = { "row-first", "column-first" };

  bool any = false;
  for ( int s = 0; s < 2; ++s ) {
    if ( !viol[s] ) continue;
    any = true;
    std::cerr << "Srota TP-V2 FAILED (" << shape_name[s] << "): invariant "
              << "I-ISL (TOPO-003 section 4.1) is violated on " << viol[s]
              << " of " << total[s] << " (tile, resource) routes. "
              << "Example: router " << first_src[s] << " -> router "
              << first_dst[s] << " transits island router "
              << first_via[s] << " before arriving. Two islands on one "
              << "path means the second regulator shapes traffic the "
              << "first already shaped, so the composed rate is the "
              << "product of the two bounds rather than the intended "
              << "bound -- bandwidth is silently lost with no error "
              << "indication (section 4.1.2)." << std::endl;
  }

  if ( viol[0] > viol[1] ) {
    std::cerr << "Srota TP-V2 diagnosis: the two shapes fail for "
              << "different reasons, and the asymmetry is the finding.\n"
              << "  Row-first fails STRUCTURALLY. A row-first route to a "
              << "resource in island column X turns at (X, source_row) "
              << "-- which is itself an island router, because TOPO-003 "
              << "section 7.3 wraps every router in an island COLUMN, "
              << "K per column -- and then rides that column to the "
              << "resource. Two island routers on the path, on every "
              << "route whose source is not already in the destination "
              << "row.\n"
              << "  Column-first fails only INCIDENTALLY: it turns at "
              << "(source_col, dest_row), which is outside the island "
              << "column unless the source itself happens to sit in an "
              << "island column. That residue is why its count above is "
              << "small -- and it disappears entirely if island columns "
              << "host no ordinary tiles.\n"
              << "  Implication: island-bound traffic cannot use the "
              << "default shape. ROUTE-001 section 13.1 says island-bound "
              << "traffic 'uses its own MECS drop class -- a routing "
              << "rule, not a separate path-selection mechanism', and "
              << "requires that routing 'must not admit a path that "
              << "violates I-ISL'. This is the concrete rule that "
              << "sentence needs and does not yet state: force "
              << "column-first for island-bound flows, or make an island "
              << "a per-router property at the attach point rather than "
              << "a whole-column one.\n"
              << "  Continuing -- this is a finding about the "
              << "island/routing interaction in the specs, not a "
              << "malformed config, so refusing to run would help "
              << "no one." << std::endl;
  } else if ( any && gSrIslColFirst ) {
    std::cerr << "Srota TP-V2 diagnosis (isl_route=colfirst): the rule "
              << "removes every structural violation. What remains are "
              << "routes whose SOURCE sits in an island column: a whole "
              << "island column cannot be left without transiting a second "
              << "island router on either shape. That is TOPO-003 T-R5's "
              << "territory -- island columns that also host ordinary tiles "
              << "-- and it vanishes if they host none." << std::endl;
  } else if ( any ) {
    std::cerr << "Srota TP-V2: continuing despite the violation -- see "
              << "TOPO-003 section 4.1.2 for the consequence."
              << std::endl;
  }

  if ( any ) return;

  if ( gSrPathEn & SROTA_EN_VALIANT ) {
    std::cout << "Srota TP-V2: passed for the direct shapes, but Valiant "
              << "is enabled and its intermediate is chosen at runtime, "
              << "so I-ISL cannot be discharged structurally for "
              << "island-bound Valiant flows. ROUTE-001 section 13.1 "
              << "requires routing rules not to admit such a path; with "
              << "a uniform-random intermediate they can. Either exclude "
              << "island-bound flows from Valiant selection or restrict "
              << "the intermediate to non-island columns." << std::endl;
  } else {
    std::cout << "Srota TP-V2: I-ISL verified over all (tile, resource, "
              << "shape) routes for island columns 0x" << std::hex
              << _island_col_map << std::dec << "." << std::endl;
  }
}

// Where a flit lands after one route step. Mirrors the builder's tap
// ordering (tap i is i+1 steps from the driver), so this and
// _BuildExpressDim cannot disagree.
static int SrotaNextRouter( int cur, SrotaRouteResult const & rr, int k ) {
  if ( rr.eject || rr.dir < 0 ) return cur;

  int const x = cur % k;
  int const y = cur / k;
  int const dist = ( rr.drop >= 0 ) ? ( rr.drop + 1 ) : 1;

  switch ( (SrotaNoC::Dir)rr.dir ) {
    case SrotaNoC::SROTA_XNEG: return y * k + ( x - dist );
    case SrotaNoC::SROTA_XPOS: return y * k + ( x + dist );
    case SrotaNoC::SROTA_YNEG: return ( y - dist ) * k + x;
    case SrotaNoC::SROTA_YPOS: return ( y + dist ) * k + x;
  }
  return -1;
}

int SrotaNoC::_NextRouterFor( int cur, SrotaRouteResult const & rr ) const {
  return SrotaNextRouter( cur, rr, _k );
}

// ======================================================================
//  F1 -- deadlock freedom by static CDG construction.
//  ROUTE-001 sections 4.2, 4.4, 4.5.
//
//  Section 4.2 defines the graph: "one node per physical channel (here:
//  per MECS row-segment and column-segment) and a directed edge from
//  channel A to channel B whenever some routing path uses A immediately
//  followed by B", and stresses that it is "a property of the routing
//  algorithm, not of any single packet -- the union of dependencies over
//  every path the algorithm admits."
//
//  So this builds the union over every (source, destination, enabled
//  shape, Valiant intermediate) route the configuration admits, and
//  looks for a cycle. A channel here is a (driving router, direction)
//  pair -- one driven segment, which is exactly section 7.2's "exactly
//  one driver per segment per direction." When a VC policy is active the
//  node is (channel, VC set), because a packet holding a channel in one
//  VC set cannot block one waiting in another.
//
//  Section 4.4 says to run this on a 4x4 abstraction: "small enough for
//  exhaustive exploration, large enough to exercise every edge type.
//  Because the argument in section 4.3 does not depend on mesh radix,
//  the 4x4 result generalizes." That is why this runs at a small fixed
//  radix regardless of the configured k -- it makes exhaustive
//  enumeration over every Valiant intermediate affordable, which
//  sampling would not be, and a sampled CDG check is worth very little.
//
//  Section 4.5.4 asks for exactly this run at ROUTE_PATH_EN = 0b111 and
//  lists three possible outcomes. This function answers it on every
//  elaboration, so the answer can never drift away from the code.
// ======================================================================
void SrotaNoC::_CheckCDG( int radix ) const {

  // The island routing rule makes the admitted route set depend on WHICH
  // columns are islands, which a 4x4 abstraction cannot represent -- the
  // radix-independence argument of section 4.4 is about the shapes, not
  // about a placement. So with the rule on, check the real fabric.
  bool const isl_rule = gSrIslColFirst && _island_col_map != 0;
  int const k = isl_rule ? _k : radix;
  int const c = 1;                 // concentration is irrelevant to the CDG
  int const nrouters = k * k;
  int const nsets = gSrVCSets;
  int const nch = nrouters * 4;    // (driving router, direction)
  int const nnodes = nch * nsets;

  vector<vector<int> > adj( nnodes );
  vector<vector<char> > seen( nnodes );

  // Label an edge with the shape that created it, so a reported cycle
  // says which path shapes combined to close it -- which is the actual
  // question section 4.5 asks.
  vector<vector<int> > adj_shape( nnodes );

  bool const val_en = ( gSrPathEn & SROTA_EN_VALIANT ) != 0;

  for ( int shape = 0; shape <= 2; ++shape ) {
    bool const shape_en =
        ( shape == 0 ) ? ( gSrPathEn & SROTA_EN_ROW ) != 0 :
        ( shape == 1 ) ? ( gSrPathEn & SROTA_EN_COL ) != 0 : val_en;
    // Column-first is live for island-bound flows even when path_en
    // leaves it off for everyone else.
    if ( !shape_en && !( isl_rule && shape == 1 ) ) continue;

    // oneshape keeps only one direct shape live at a time, fabric-wide,
    // so the union that matters is per-epoch and never contains both.
    // Checking row-first alone is the correct model of that policy --
    // unless the island rule keeps column-first flows alive inside a
    // row-first epoch, in which case the union is exactly what exists.
    bool const isolate = ( gSrVCPolicy == SROTA_VC_ONESHAPE ) && !isl_rule;
    if ( isolate && shape == 1 ) continue;

    for ( int src = 0; src < nrouters; ++src ) {
      for ( int dst = 0; dst < nrouters; ++dst ) {
        if ( src == dst ) continue;

        // Island-bound flows take column-first and nothing else.
        if ( isl_rule ) {
          bool const isl_dst = ( _island_col_map & ( 1 << ( dst % k ) ) ) != 0;
          if ( isl_dst && shape != SROTA_COL_FIRST ) continue;
          if ( !isl_dst && !shape_en ) continue;
        }

        // Exhaustive over intermediates for Valiant; a single dummy pass
        // for the direct shapes.
        int const ilo = ( shape == 2 ) ? 0 : -1;
        int const ihi = ( shape == 2 ) ? nrouters - 1 : -1;

        for ( int intm = ilo; intm <= ihi; ++intm ) {
          if ( shape == 2 && ( intm == src || intm == dst ) ) continue;

          int cur = src;
          int sh = shape;
          int prev_node = -1;
          int prev_shape = shape;
          int guard = 4 * k + 8;

          while ( cur != dst && guard-- > 0 ) {
            SrotaRouteResult const rr =
                SrotaRouteCompute( cur, dst * c, sh, intm, k, c );
            if ( rr.eject ) break;

            int set = 0;
            if ( nsets > 1 ) {
              set = ( gSrVCPolicy == SROTA_VC_SHAPE )
                      ? ( ( sh == SROTA_COL_FIRST ) ? 1 : 0 )
                      : rr.rank;
              if ( set >= nsets ) set = nsets - 1;
            }

            int const node = ( cur * 4 + rr.dir ) * nsets + set;

            if ( prev_node >= 0 && prev_node != node ) {
              if ( seen[prev_node].empty() ) seen[prev_node].assign( nnodes, 0 );
              if ( !seen[prev_node][node] ) {
                seen[prev_node][node] = 1;
                adj[prev_node].push_back( node );
                adj_shape[prev_node].push_back( prev_shape );
              }
            }

            prev_node  = node;
            prev_shape = sh;
            sh  = rr.new_shape;
            cur = SrotaNextRouter( cur, rr, k );
            if ( cur < 0 ) break;
          }
        }
      }
    }
  }

  // Iterative DFS with colours: 0 unvisited, 1 on stack, 2 done.
  vector<char> colour( nnodes, 0 );
  vector<int>  parent( nnodes, -1 );
  vector<int>  cycle;

  for ( int s = 0; s < nnodes && cycle.empty(); ++s ) {
    if ( colour[s] != 0 ) continue;

    vector<pair<int,int> > stk;       // (node, next child index)
    stk.push_back( make_pair( s, 0 ) );
    colour[s] = 1;

    while ( !stk.empty() && cycle.empty() ) {
      int const u = stk.back().first;
      int & ci = stk.back().second;

      if ( ci < (int)adj[u].size() ) {
        int const v = adj[u][ci++];
        if ( colour[v] == 1 ) {
          // Back edge -> cycle. v is somewhere on the stack; the cycle is
          // the stack segment from v to the current top, and then the
          // back edge closing it. Collected in forward (traversal) order.
          size_t start = 0;
          for ( size_t i = 0; i < stk.size(); ++i ) {
            if ( stk[i].first == v ) { start = i; break; }
          }
          for ( size_t i = start; i < stk.size(); ++i ) {
            cycle.push_back( stk[i].first );
          }
        } else if ( colour[v] == 0 ) {
          colour[v] = 1;
          parent[v] = u;
          stk.push_back( make_pair( v, 0 ) );
        }
      } else {
        colour[u] = 2;
        stk.pop_back();
      }
    }
  }

  static const char * dname[4] = { "X-", "X+", "Y-", "Y+" };
  static const char * sname[4] = { "row-first", "column-first",
                                   "valiant-L1", "valiant-L2" };

  int edges = 0;
  for ( int i = 0; i < nnodes; ++i ) edges += (int)adj[i].size();

  if ( isl_rule ) {
    std::cout << "Srota F1 CDG check: srota_isl_route=colfirst -- checking "
              << "the full " << k << "x" << k << " fabric with island "
              << "columns 0x" << std::hex << _island_col_map << std::dec
              << ", because the rule's route set depends on placement."
              << std::endl;
  }

  if ( cycle.empty() ) {
    std::cout << "Srota F1 CDG check: PASS on the " << k << "x" << k
              << ( isl_rule ? " fabric" : " abstraction" )
              << " (ROUTE-001 section 4.4). "
              << nnodes << " nodes, " << edges << " edges, no cycle. "
              << "Shapes enabled: "
              << ( ( gSrPathEn & SROTA_EN_ROW ) ? "row " : "" )
              << ( ( gSrPathEn & SROTA_EN_COL ) ? "column " : "" )
              << ( val_en ? "valiant " : "" )
              << "| vc_sets=" << nsets << "." << std::endl;
    return;
  }

  std::cerr << "Srota F1 CDG check: *** CYCLE FOUND *** on the " << k
            << "x" << k << ( isl_rule ? " fabric" : " abstraction" )
            << ". This is ROUTE-001 section "
            << "4.5's path-shape mixing hazard (RT-R7), reproduced "
            << "statically. The routing rules this configuration admits "
            << "have a cyclic channel dependency graph, so F1 does not "
            << "hold and the fabric can deadlock." << std::endl;

  std::cerr << "  Cycle of " << cycle.size() << " channels "
            << "(channel = driving router + direction; the shape in "
            << "brackets is the path that creates that dependency):"
            << std::endl;
  for ( size_t i = 0; i < cycle.size(); ++i ) {
    int const node = cycle[i];
    int const nxt  = cycle[( i + 1 ) % cycle.size()];
    int const set  = node % nsets;
    int const ch   = node / nsets;
    int const dir  = ch % 4;
    int const rtr  = ch / 4;

    std::cerr << "    router(" << ( rtr % k ) << "," << ( rtr / k )
              << ") " << dname[dir] << " vc_set=" << set;

    for ( size_t e = 0; e < adj[node].size(); ++e ) {
      if ( adj[node][e] == nxt ) {
        std::cerr << "  --[" << sname[ adj_shape[node][e] ] << "]-->";
        break;
      }
    }
    if ( i + 1 == cycle.size() ) std::cerr << "  (back to the first)";
    std::cerr << std::endl;
  }

  std::cerr << "  Resolutions, per ROUTE-001 section 4.5.3 plus one it "
            << "does not list: srota_vc_policy=oneshape (option 1, one "
            << "shape per epoch fabric-wide, 0 extra VCs), "
            << "srota_vc_policy=shape (option 2, O1TURN's own two VC "
            << "sets), or srota_vc_policy=rank (a hop-rank split -- 2 VC "
            << "sets for the direct shapes, 4 with Valiant, and the only "
            << "one of the three that keeps all shapes concurrently "
            << "live)." << std::endl;
  if ( isl_rule && ( gSrVCPolicy == SROTA_VC_NONE ||
                     gSrVCPolicy == SROTA_VC_ONESHAPE ) ) {
    std::cerr << "  The island rule is a shape-mixing source in its own "
              << "right: island-bound flows go column-first while the rest "
              << "of the fabric goes row-first, which is RT-R7 again even "
              << "with ROUTE_PATH_EN = row-first only. So on a zero-VC "
              << "Plane D, making I-ISL hold by routing re-opens F1. "
              << "ROUTE-001 section 13.1's 'its own MECS drop class' would "
              << "have to be a separate VC set to close both at once."
              << std::endl;
  }
  std::cerr << "  Continuing: a cyclic CDG means deadlock is REACHABLE, "
            << "not that it is certain, and observing what the fabric "
            << "does under this configuration is the point of running it."
            << std::endl;
}

// ======================================================================
//  The routing function.
// ======================================================================
void srota_o1turn( const Router *r, const Flit *f, int in_channel,
                   OutputSet *outputs, bool inject ) {

  // ------------------------------------------------------------------
  //  Layer 1 -- the FIU. ROUTE-001 sections 2, 5, 10.
  //
  //  BookSim passes r == NULL here, which is exactly right: no router
  //  exists yet, so nothing about in-network state is reachable even by
  //  accident. Never dereference r before this branch returns.
  //
  //  trafficmanager calls this for head flits only, and may call it
  //  repeatedly across cycles while the packet waits for a free VC. The
  //  flow-epoch cache makes that idempotent -- a repeat call inside the
  //  same epoch hits the cache and returns the identical decision, which
  //  is also what section 10.2's "the shape is not re-evaluated on
  //  resume" requires.
  // ------------------------------------------------------------------
  if ( inject ) {
    // The traffic manager holds one routing function for every subnet,
    // so the FIU for Plane C packets is reached through here too. Plane
    // selection is by arrival port (PKT-008 section 7.2): the subnet the
    // packet was generated on IS its plane.
    if ( gSrPlaneCSubnet >= 0 && f->subnetwork == gSrPlaneCSubnet ) {
      srota_planec_xy( r, f, in_channel, outputs, true );
      return;
    }
    if ( f->head ) {
      int shape = SROTA_ROW_FIRST;
      int intm  = -1;
      gSrFiu.Select( f->src, f->dest, f->cl, gSrK, gSrC, &shape, &intm );
      f->ph   = shape;   // path_shape, PKT-008 section 3.1 bits [46:45]
      f->intm = intm;    // hdr_valiant_x/y, cached per flow-epoch
    }
    outputs->Clear();
    outputs->AddRange( -1, 0, gSrDVCs - 1 );
    return;
  }

  // ------------------------------------------------------------------
  //  Layer 2 -- deterministic in-network traversal. No congestion state
  //  is consulted below this line, by construction: SrotaRouteCompute
  //  cannot see any.
  // ------------------------------------------------------------------
  assert( r );

  int const k = gSrK;
  int const c = gSrC;

  int const my_router = r->GetID();

  // Body and tail flits inherit their head's decision through the VC, so
  // f->ph is authoritative for whichever flit is being routed. A flit
  // that somehow arrives without one falls back to row-first, which
  // section 14.3 guarantees is always enabled.
  int shape = f->ph;
  if ( shape < 0 || shape > 3 ) shape = SROTA_ROW_FIRST;

  SrotaRouteResult const rr =
      SrotaRouteCompute( my_router, f->dest, shape, f->intm, k, c );

  // ROUTE-001 section 13.4: the shape rewrite happens at the intermediate
  // router and only there. SrotaRouteCompute decides that; persisting it
  // into the header is this line.
  if ( rr.new_shape != shape ) f->ph = rr.new_shape;

  f->drop = rr.drop;

  assert( rr.out_port >= 0 );

  // ------------------------------------------------------------------
  //  VC partition -- srota.hpp design note section 3.
  // ------------------------------------------------------------------
  int vc_lo = 0;
  int vc_hi = gSrDVCs - 1;

  if ( !rr.eject && gSrVCSets > 1 ) {
    int set;
    if ( gSrVCPolicy == SROTA_VC_SHAPE ) {
      // O1TURN's own separation: XY in one set, YX in the other.
      set = ( shape == SROTA_COL_FIRST ) ? 1 : 0;
    } else {
      // Rank. Strictly non-decreasing along every route regardless of
      // which shape was chosen, and a turn always advances it -- so
      // every dependency edge runs from a lower set to a higher one and
      // the CDG cannot close a cycle.
      set = rr.rank;
      if ( set >= gSrVCSets ) set = gSrVCSets - 1;
    }

    int const per = gSrDVCs / gSrVCSets;   // remainder is simply unused
    vc_lo = set * per;
    vc_hi = vc_lo + per - 1;
  }

  outputs->Clear();
  outputs->AddRange( rr.out_port, vc_lo, vc_hi );
}

// ======================================================================
//  Plane C routing -- VC-002 section 3, ROUTE-001 section 3.4.
//
//  Plain dimension-ordered XY on the mesh: X to the destination column,
//  then Y. One turn direction exists, so the CDG is acyclic with no VC
//  help at all; the three VCs are there for PROTOCOL deadlock, not
//  routing deadlock (VC-002 section 3.2), and are chosen by message class
//  and never by hop. BookSim's request/reply packet types are the CHI
//  classes it can express: requests on REQ, replies on RSP. Nothing in
//  BookSim generates snoops, so SNP stays idle unless a trace adds them.
// ======================================================================
static int SrotaChiVC( Flit const * f ) {
  int cls = 0;                                     // REQ
  if ( f->type == Flit::READ_REPLY || f->type == Flit::WRITE_REPLY ) cls = 1;
  return ( cls < gSrPlaneCVCs ) ? cls : gSrPlaneCVCs - 1;
}

void srota_planec_xy( const Router *r, const Flit *f, int in_channel,
                      OutputSet *outputs, bool inject ) {
  int const vc = SrotaChiVC( f );

  outputs->Clear();
  if ( inject ) {
    outputs->AddRange( -1, vc, vc );
    return;
  }

  assert( r );
  int const k = gSrK;
  int const c = gSrC;
  int const cur = r->GetID();
  int const x = cur % k, y = cur / k;
  int const dest_router = f->dest / c;
  int const dx = dest_router % k, dy = dest_router / k;

  int port;
  if ( cur == dest_router ) {
    port = f->dest % c;
  } else {
    int drop, dir;
    bool const xdim = ( dx != x );
    SrotaDimHop( x, y, dx, dy, xdim, k, c, false, &port, &drop, &dir );
  }
  outputs->AddRange( port, vc, vc );
}

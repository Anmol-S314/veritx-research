// ----------------------------------------------------------------------
//
// GEC: Generalized Express Cubes (mesh / point-to-point-express / MECS)
//
// See gec.hpp for the full design note.
//
//   mesh = 1                 -> real nearest-neighbor mesh graph
//   mesh = 0, o = k-1, d = 1 -> real full row/column ("express") graph
//   mesh = 0, o < k-1        -> MECS: real shared/tapped channels via
//                                MultiDropChannel (pout = c + 2*o,
//                                constant in k, per Table 1).
//
// ----------------------------------------------------------------------

#include "booksim.hpp"
#include <vector>
#include <sstream>
#include <iostream>
#include <cassert>
#include <cstdlib>
#include "random_utils.hpp"
#include "misc_utils.hpp"
#include "multidropchannel.hpp"
#include "gec.hpp"

// File-scope flags consulted by dor_gec(). Mirrors the existing gK/gC/gN
// convention this file already relies on (those are pre-existing
// BookSim simulation-wide globals; these are new and local to GEC, so
// they don't need to live in a shared globals header).
static bool gGECMesh = false;
static int  gGECo = 0;
static int  gGECd = 1;

GEC::GEC( const Configuration &config, const string & name )
  : Network( config, name )
{
  _ComputeSize( config );
  _Alloc();
  _BuildNet( config );
}

void GEC::RegisterRoutingFunctions() {
  gRoutingFunctionMap["dor_gec"] = &dor_gec;
  gRoutingFunctionMap["adaptive_xy_yx_gec"] = &adaptive_xy_yx_gec;
  gRoutingFunctionMap["hybrid_gec"] = &hybrid_gec;
}

int  GEC::GetN() const { return _n; }
int  GEC::GetK() const { return _k; }
int  GEC::GetC() const { return _c; }
int  GEC::GetO() const { return _o; }
int  GEC::GetD() const { return _d; }
bool GEC::IsMesh() const { return _mesh; }

void GEC::_ComputeSize( const Configuration &config ) {

  _k = config.GetInt( "k" );
  _c = config.GetInt( "c" );
  _n = 2;

  // o, d default to the full-express corner (o=k-1, d=1) so existing
  // configs that don't set them keep behaving exactly as before.
  _o = config.GetInt( "o" );
  _d = config.GetInt( "d" );
  if ( _o == 0 ) _o = _k - 1;
  if ( _d == 0 ) _d = 1;

  _mesh = ( config.GetInt( "mesh" ) != 0 );
  _hybrid = ( config.GetInt( "hybrid" ) != 0 );

  assert( _k >= 2 );
  assert( _c >= 1 );

  if ( _hybrid && _mesh ) {
    std::cerr << "GEC config error: hybrid=1 and mesh=1 are mutually "
              << "exclusive -- hybrid already builds the mesh graph "
              << "itself (plus MECS layered on top); mesh=1 alone builds "
              << "nothing but the mesh graph. Pick one." << std::endl;
    exit( -1 );
  }

  if ( _mesh ) {
    // The paper's mesh case is a structurally different graph
    // (physically-adjacent-only), not "the complete graph partitioned
    // into groups of one." o/d partition semantics don't apply to it,
    // so requesting anything other than o=1,d=1 alongside mesh=1 is a
    // config error -- fail loudly rather than guess what was meant.
    if ( _o != 1 || _d != 1 ) {
      std::cerr << "GEC config error: mesh=1 requires o=1 and d=1 "
                << "(got o=" << _o << ", d=" << _d << "). "
                << "The o/d express-channel partitioning model does not "
                << "apply to the nearest-neighbor mesh graph." << std::endl;
      exit( -1 );
    }
  } else {
    if ( _o * _d != _k - 1 ) {
      std::cerr << "GEC config error: o*d must equal k-1 "
                << "(got o=" << _o << ", d=" << _d << ", k-1=" << (_k-1)
                << ")." << std::endl;
      exit( -1 );
    }
    if ( _d > 1 ) {
      // MECS / MECS-P corner: pout = c + 2*o (constant in k, per
      // Table 1), realized over real shared/tapped MultiDropChannels
      // (see multidropchannel.hpp and _BuildNetMECS() below).
      //
      // Lookahead routing can't be supported here yet: IQRouter's
      // lookahead path resolves the next hop via FlitChannel::GetSink(),
      // which only tracks a multidrop channel's most-recently-registered
      // tap, not the specific tap a given flit is addressed to (that's
      // carried in Flit::drop, resolved by dor_gec() at the router, not
      // by GetSink()). Deferred routing (routing_delay>0, the default)
      // has no such ambiguity since it always asks the actual current
      // router for its own ID. Refuse rather than silently mis-route.
      if ( config.GetInt( "routing_delay" ) == 0 ) {
        std::cerr << "GEC config error: d=" << _d << " > 1 (MECS) requires "
                  << "routing_delay > 0. Lookahead routing (routing_delay=0) "
                  << "resolves the next hop via FlitChannel::GetSink(), which "
                  << "cannot distinguish a multidrop channel's taps -- see "
                  << "the comment above this check for the full reason. "
                  << "Set routing_delay to a positive value (the BookSim "
                  << "default) to use MECS." << std::endl;
        exit( -1 );
      }

      // The VC allocator's request/grant key is (out_port, out_vc), with
      // no room for which tap of a multidrop out_port a request is for
      // -- so two flits addressed to different taps of the same shared
      // channel, requesting the same out_vc number, would otherwise look
      // like a genuine conflict over one resource when they are actually
      // headed to two independent downstream buffers. dor_gec() avoids
      // that false sharing by partitioning each multidrop port's VC
      // range into d disjoint sub-ranges, one per tap (the same
      // partitioning idiom xy_yx_mesh already uses to split a port's VCs
      // across its two DOR phases) -- which needs at least 1 VC per tap.
      if ( config.GetInt( "num_vcs" ) < _d ) {
        std::cerr << "GEC config error: num_vcs=" << config.GetInt( "num_vcs" )
                  << " < d=" << _d << ". MECS needs at least one VC per tap "
                  << "on a shared channel to give each tap a disjoint VC "
                  << "sub-range (see the comment above this check)."
                  << std::endl;
        exit( -1 );
      }
    }
  }

  // adaptive_xy_yx_gec (see below) picks, once per packet at its first
  // hop, whether to resolve the row or the column first, then commits
  // for the rest of that packet's journey. Mixing "row first" and
  // "column first" packets on shared VCs is exactly the classic 2-cycle
  // deadlock (row_channel depends on col_channel for row-first packets,
  // AND col_channel depends on row_channel for col-first packets --
  // each direction of that mutual dependency is fine alone, but together
  // they form a cycle). The fix used here is the same principle as
  // dor_gec's per-tap split: give a packet's *first* hop and *second/
  // final* hop disjoint VC sub-ranges (rank strictly increases 1->2 on
  // every route, regardless of which dimension went first, so the
  // dependency graph stays acyclic) -- and, when MECS is also active,
  // split each of those two halves again into d per-tap sub-ranges. That
  // needs 2*d VCs at minimum, double dor_gec's own floor.
  // hybrid_gec needs the identical floor and for the identical reason:
  // it also splits VCs into two hop-phase halves (X-dimension traffic
  // vs Y-dimension traffic this time, not first-hop-vs-second-hop --
  // see the design note in gec.hpp -- but the arithmetic is the same),
  // each further split by MECS tap when d>1.
  if ( config.GetStr( "routing_function" ) == "adaptive_xy_yx" || _hybrid ) {
    if ( config.GetInt( "num_vcs" ) < 2 * _d ) {
      std::cerr << "GEC config error: num_vcs=" << config.GetInt( "num_vcs" )
                << " < 2*d=" << ( 2 * _d ) << ". adaptive_xy_yx_gec and "
                << "hybrid_gec both need a disjoint VC sub-range per "
                << "(phase, tap) pair -- 2 phases x d taps -- to stay "
                << "deadlock-free (see the comment above this check)."
                << std::endl;
      exit( -1 );
    }
  }

  // GEC hardcodes SetLatency(1) on every channel below -- it has no
  // physical-floorplan/wire-length model (unlike cmesh's use_noc_latency
  // formula, which needs xr/yr concentration-footprint info GEC doesn't
  // track). use_noc_latency defaults to 1 in stock BookSim
  // (booksim_config.cpp), so silently ignoring it would silently give
  // wrong latency numbers to anyone who doesn't happen to set it to 0
  // by hand. Refuse instead of silently diverging -- same policy as
  // the d>1 refusal above.
  if ( config.GetInt( "use_noc_latency" ) != 0 ) {
    std::cerr << "GEC config error: use_noc_latency=1 (or unset -- it "
              << "defaults to 1) requested, but GEC has no wire-length "
              << "latency model and hardcodes 1-cycle channel latency. "
              << "Set use_noc_latency=0 explicitly, or compare against "
              << "other topologies with use_noc_latency=0 on both sides. "
              << "Refusing to silently produce latency numbers that "
              << "don't match what was asked for." << std::endl;
    exit( -1 );
  }

  gGECMesh = _mesh;
  gGECo = _o;
  gGECd = _d;
  gK = _k;
  gN = _n;
  gC = _c;

  _size  = _k * _k;      // routers
  _nodes = _size * _c;   // terminals

  if ( _mesh ) {
    // Directed mesh channels: k*(k-1) undirected horizontal edges and
    // k*(k-1) undirected vertical edges, each realized as 2 directed
    // point-to-point Channel objects.
    _degree   = 0; // unused in mesh mode; degree varies per router, see _BuildNetMesh
    _channels = 4 * _k * ( _k - 1 );
  } else if ( _hybrid ) {
    // Mesh edges (point-to-point, in _chan) plus o MECS express channels
    // per dimension (shared/tapped, in Network::_md_chan) on the SAME
    // router set. Router degree varies with grid position (mesh part)
    // AND is offset by a constant (MECS part) -- see _BuildNetHybrid.
    _degree   = 0; // unused; per-router degree computed in _BuildNetHybrid
    _channels = 4 * _k * ( _k - 1 ); // mesh edges only; MECS lives in _md_chan
  } else if ( _d == 1 ) {
    // Full row/column point-to-point graph (o=k-1, d=1 confirmed above).
    _degree   = _c + 2 * ( _k - 1 );
    _channels = 2 * _size * ( _k - 1 );
  } else {
    // MECS: connectivity lives entirely in the MultiDropChannels built
    // by _BuildNetMECS() (pushed onto Network::_md_chan, not _chan), so
    // the ordinary point-to-point _chan array is unused here.
    _degree   = 0; // unused in MECS mode; in/out degree differ per router, see _BuildNetMECS
    _channels = 0;
  }

  // Printed unconditionally (not gated behind a debug flag) because the
  // headline, easy-to-get-wrong claim about this topology is port count:
  // MECS's whole point is pout = c + 2*o staying constant as k grows,
  // where express/point-to-point's pout = c + 2*(k-1) grows with k. This
  // makes that claim checkable on every run instead of asserted in a
  // comment.
  {
    string mode = _mesh ? "mesh" : ( _hybrid ? "hybrid(mesh+MECS)" : ( _d == 1 ? "express(p2p)" : "MECS" ) );
    std::cout << "GEC: mode=" << mode
              << " k=" << _k << " c=" << _c << " o=" << _o << " d=" << _d
              << " => routers=" << ( _k * _k ) << " terminals=" << ( _k * _k * _c );
    if ( _hybrid ) {
      // Router degree varies by grid position (mesh part), so print the
      // interior (max-degree, non-boundary) router's counts as the
      // representative figure -- outputs = c + 4 (mesh) + 2*o (MECS);
      // inputs = c + 4 (mesh) + 2*(k-1) (MECS taps).
      int const pout = _c + 4 + 2 * _o;
      int const pin  = _c + 4 + 2 * ( _k - 1 );
      std::cout << " | interior-router ports: outputs=" << pout
                << " inputs=" << pin
                << " (boundary routers have fewer mesh ports; MECS part "
                << "constant in k, mesh part isn't)";
    } else if ( !_mesh ) {
      int const pout = ( _d == 1 ) ? _degree : ( _c + 2 * _o );
      int const pin_row_col = ( _d == 1 ) ? _degree : ( _c + 2 * ( _k - 1 ) );
      std::cout << " | per-router ports: outputs=" << pout
                << " inputs=" << pin_row_col
                << " (outputs constant in k iff MECS; inputs always grow with k)";
    }
    std::cout << std::endl;
  }
}

int GEC::_PeerIndex( int self, int peer ) {
  assert( self != peer );
  return ( peer < self ) ? peer : ( peer - 1 );
}

int GEC::_RowChannelId( int y, int a, int b ) const {
  assert( a != b );
  int idx_in_row = a * ( _k - 1 ) + _PeerIndex( a, b );
  return y * _k * ( _k - 1 ) + idx_in_row;
}

int GEC::_ColChannelId( int x, int a, int b ) const {
  assert( a != b );
  int idx_in_col = a * ( _k - 1 ) + _PeerIndex( a, b );
  int col_base = _size * ( _k - 1 ); // after all row channels
  return col_base + x * _k * ( _k - 1 ) + idx_in_col;
}

int GEC::_MeshRowChannelId( int y, int a, int b ) const {
  assert( a >= 0 && b >= 0 && a < _k && b < _k );
  assert( ( a - b == 1 ) || ( b - a == 1 ) ); // must be adjacent
  int e   = ( a < b ) ? a : b;
  int dir = ( a < b ) ? 0 : 1; // 0: a->b ascending, 1: a->b descending
  return y * ( _k - 1 ) * 2 + e * 2 + dir;
}

int GEC::_MeshColChannelId( int x, int a, int b ) const {
  assert( a >= 0 && b >= 0 && a < _k && b < _k );
  assert( ( a - b == 1 ) || ( b - a == 1 ) );
  int e   = ( a < b ) ? a : b;
  int dir = ( a < b ) ? 0 : 1;
  int row_base = _k * ( _k - 1 ) * 2; // after all mesh row channels
  return row_base + x * ( _k - 1 ) * 2 + e * 2 + dir;
}

int GEC::MeshPortOffset( int x, int y, int k, MeshDir dir ) {
  int offset = 0;
  bool west  = ( x > 0 );
  bool east  = ( x < k - 1 );
  bool north = ( y > 0 );
  bool south = ( y < k - 1 );

  if ( dir == MESH_WEST )  return west  ? offset : -1;
  if ( west ) offset++;
  if ( dir == MESH_EAST )  return east  ? offset : -1;
  if ( east ) offset++;
  if ( dir == MESH_NORTH ) return north ? offset : -1;
  if ( north ) offset++;
  if ( dir == MESH_SOUTH ) return south ? offset : -1;
  return -1;
}

int GEC::MeshDegreeAt( int x, int y, int k ) {
  bool const west  = ( x > 0 );
  bool const east  = ( x < k - 1 );
  bool const north = ( y > 0 );
  bool const south = ( y < k - 1 );
  return ( west ? 1 : 0 ) + ( east ? 1 : 0 ) + ( north ? 1 : 0 ) + ( south ? 1 : 0 );
}

void GEC::_BuildNet( const Configuration &config ) {
  if ( _mesh ) {
    _BuildNetMesh( config );
  } else if ( _hybrid ) {
    _BuildNetHybrid( config );
  } else if ( _d == 1 ) {
    _BuildNetExpress( config );
  } else {
    _BuildNetMECS( config );
  }
}

// ----------------------------------------------------------------------
// Full row/column point-to-point graph. o=k-1, d=1 confirmed by
// _ComputeSize before this is ever called. Unchanged from the original
// v1 implementation.
// ----------------------------------------------------------------------
void GEC::_BuildNetExpress( const Configuration &config ) {

  ostringstream name;

  for ( int node = 0; node < _size; ++node ) {

    int x = node % _k;
    int y = node / _k;

    name << "gec_router_" << y << '_' << x;
    _routers[node] = Router::NewRouter( config,
                                         this,
                                         name.str(),
                                         node,
                                         _degree,
                                         _degree );
    _timed_modules.push_back( _routers[node] );
    name.str("");

    // Local terminal ports: [0, c)
    for ( int t = 0; t < _c; ++t ) {
      int term = node * _c + t;

      _inject[term]->SetLatency( 1 );
      _inject_cred[term]->SetLatency( 1 );
      _eject[term]->SetLatency( 1 );
      _eject_cred[term]->SetLatency( 1 );

      _routers[node]->AddInputChannel( _inject[term], _inject_cred[term] );
      _routers[node]->AddOutputChannel( _eject[term], _eject_cred[term] );
    }

    // Row (express) ports: [c, c+(k-1))
    for ( int px = 0; px < _k; ++px ) {
      if ( px == x ) continue;

      int out_id = _RowChannelId( y, x, px );
      int in_id  = _RowChannelId( y, px, x );

      _chan[out_id]->SetLatency( 1 );
      _chan_cred[out_id]->SetLatency( 1 );
      _chan[in_id]->SetLatency( 1 );
      _chan_cred[in_id]->SetLatency( 1 );

      _routers[node]->AddOutputChannel( _chan[out_id], _chan_cred[out_id] );
      _routers[node]->AddInputChannel( _chan[in_id], _chan_cred[in_id] );
    }

    // Column (express) ports: [c+(k-1), c+2*(k-1))
    for ( int py = 0; py < _k; ++py ) {
      if ( py == y ) continue;

      int out_id = _ColChannelId( x, y, py );
      int in_id  = _ColChannelId( x, py, y );

      _chan[out_id]->SetLatency( 1 );
      _chan_cred[out_id]->SetLatency( 1 );
      _chan[in_id]->SetLatency( 1 );
      _chan_cred[in_id]->SetLatency( 1 );

      _routers[node]->AddOutputChannel( _chan[out_id], _chan_cred[out_id] );
      _routers[node]->AddInputChannel( _chan[in_id], _chan_cred[in_id] );
    }
  }
}

// ----------------------------------------------------------------------
// Nearest-neighbor mesh graph. Variable router degree (2..4 dimension
// ports + c local ports depending on grid position). Port order at
// each router is fixed as west, east, north, south (skipping any
// direction that doesn't exist at this router) via MeshPortOffset(),
// which dor_gec() calls with the exact same logic to pick the output
// port -- so construction and routing can never disagree about port
// numbering.
// ----------------------------------------------------------------------
void GEC::_BuildNetMesh( const Configuration &config ) {

  ostringstream name;

  for ( int node = 0; node < _size; ++node ) {

    int x = node % _k;
    int y = node / _k;

    bool west  = ( x > 0 );
    bool east  = ( x < _k - 1 );
    bool north = ( y > 0 );
    bool south = ( y < _k - 1 );

    int degree_local = _c + ( west ? 1 : 0 ) + ( east ? 1 : 0 )
                           + ( north ? 1 : 0 ) + ( south ? 1 : 0 );

    name << "gec_router_" << y << '_' << x;
    _routers[node] = Router::NewRouter( config,
                                         this,
                                         name.str(),
                                         node,
                                         degree_local,
                                         degree_local );
    _timed_modules.push_back( _routers[node] );
    name.str("");

    // Local terminal ports: [0, c)
    for ( int t = 0; t < _c; ++t ) {
      int term = node * _c + t;

      _inject[term]->SetLatency( 1 );
      _inject_cred[term]->SetLatency( 1 );
      _eject[term]->SetLatency( 1 );
      _eject_cred[term]->SetLatency( 1 );

      _routers[node]->AddInputChannel( _inject[term], _inject_cred[term] );
      _routers[node]->AddOutputChannel( _eject[term], _eject_cred[term] );
    }

    // Dimension ports, in the fixed west/east/north/south order that
    // MeshPortOffset() also uses -- only added when the neighbor exists.
    if ( west ) {
      int out_id = _MeshRowChannelId( y, x, x - 1 );
      int in_id  = _MeshRowChannelId( y, x - 1, x );
      _chan[out_id]->SetLatency( 1 );      _chan_cred[out_id]->SetLatency( 1 );
      _chan[in_id]->SetLatency( 1 );       _chan_cred[in_id]->SetLatency( 1 );
      _routers[node]->AddOutputChannel( _chan[out_id], _chan_cred[out_id] );
      _routers[node]->AddInputChannel( _chan[in_id], _chan_cred[in_id] );
    }
    if ( east ) {
      int out_id = _MeshRowChannelId( y, x, x + 1 );
      int in_id  = _MeshRowChannelId( y, x + 1, x );
      _chan[out_id]->SetLatency( 1 );      _chan_cred[out_id]->SetLatency( 1 );
      _chan[in_id]->SetLatency( 1 );       _chan_cred[in_id]->SetLatency( 1 );
      _routers[node]->AddOutputChannel( _chan[out_id], _chan_cred[out_id] );
      _routers[node]->AddInputChannel( _chan[in_id], _chan_cred[in_id] );
    }
    if ( north ) {
      int out_id = _MeshColChannelId( x, y, y - 1 );
      int in_id  = _MeshColChannelId( x, y - 1, y );
      _chan[out_id]->SetLatency( 1 );      _chan_cred[out_id]->SetLatency( 1 );
      _chan[in_id]->SetLatency( 1 );       _chan_cred[in_id]->SetLatency( 1 );
      _routers[node]->AddOutputChannel( _chan[out_id], _chan_cred[out_id] );
      _routers[node]->AddInputChannel( _chan[in_id], _chan_cred[in_id] );
    }
    if ( south ) {
      int out_id = _MeshColChannelId( x, y, y + 1 );
      int in_id  = _MeshColChannelId( x, y + 1, y );
      _chan[out_id]->SetLatency( 1 );      _chan_cred[out_id]->SetLatency( 1 );
      _chan[in_id]->SetLatency( 1 );       _chan_cred[in_id]->SetLatency( 1 );
      _routers[node]->AddOutputChannel( _chan[out_id], _chan_cred[out_id] );
      _routers[node]->AddInputChannel( _chan[in_id], _chan_cred[in_id] );
    }
  }
}

// ----------------------------------------------------------------------
// MECS (o < k-1, d = (k-1)/o > 1). Each router drives o MultiDropChannels
// per dimension (row and column), each shared/tapped by d peers.
//
// Grouping: within row y, router a's k-1 peers are ordered by the same
// _PeerIndex() used by express mode (all other columns, ascending, self
// skipped). Splitting that ordering into o contiguous runs of d gives
// peer b's (group, tap) = (peer_idx/d, peer_idx%d). Router a owns one
// MultiDropChannel per group g -- its g-th row output port -- tapped by
// exactly the d peers whose peer_idx falls in that group; column
// channels are built the identical way, transposed. dor_gec() computes
// this exact (group, tap) pair when routing, so construction and
// routing can never disagree about which channel or which tap a flit
// needs. Ports, in build order (and so in the order dor_gec() must
// match): [0,c) local, [c,c+o) row groups, [c+o,c+2o) column groups.
// ----------------------------------------------------------------------
void GEC::_BuildNetMECS( const Configuration &config ) {

  ostringstream name;

  int const degree_out = _c + 2 * _o;
  int const degree_in  = _c + 2 * ( _k - 1 );

  for ( int node = 0; node < _size; ++node ) {

    int x = node % _k;
    int y = node / _k;

    name << "gec_router_" << y << '_' << x;
    _routers[node] = Router::NewRouter( config,
                                         this,
                                         name.str(),
                                         node,
                                         degree_in,
                                         degree_out );
    _timed_modules.push_back( _routers[node] );
    name.str("");

    // Local terminal ports: [0, c)
    for ( int t = 0; t < _c; ++t ) {
      int term = node * _c + t;

      _inject[term]->SetLatency( 1 );
      _inject_cred[term]->SetLatency( 1 );
      _eject[term]->SetLatency( 1 );
      _eject_cred[term]->SetLatency( 1 );

      _routers[node]->AddInputChannel( _inject[term], _inject_cred[term] );
      _routers[node]->AddOutputChannel( _eject[term], _eject_cred[term] );
    }
  }

  // Row MultiDropChannels: one per (y, a, g). Router a's g-th row output
  // port, [c+g], tapped by the d peers with peer_idx in [g*d, g*d+d).
  for ( int y = 0; y < _k; ++y ) {
    for ( int a = 0; a < _k; ++a ) {
      for ( int g = 0; g < _o; ++g ) {

        ostringstream cname;
        cname << "gec_row_y" << y << "_a" << a << "_g" << g;
        MultiDropChannel * fchan = new MultiDropChannel( this, cname.str(), _classes );
        cname.str("");
        cname << "gec_row_cred_y" << y << "_a" << a << "_g" << g;
        MultiDropCreditChannel * cchan = new MultiDropCreditChannel( this, cname.str() );

        fchan->SetLatency( 1 );
        cchan->SetLatency( 1 );
        _timed_modules.push_back( fchan );
        _timed_modules.push_back( cchan );
        _md_chan.push_back( fchan );
        _md_chan_cred.push_back( cchan );

        for ( int local = 0; local < _d; ++local ) {
          int const peer_idx = g * _d + local;
          int const b = ( peer_idx < a ) ? peer_idx : ( peer_idx + 1 );
          int const dst_node = y * _k + b;
          _routers[dst_node]->AddMultiDropInputChannel( fchan, cchan );
        }

        int const src_node = y * _k + a;
        _routers[src_node]->AddMultiDropOutputChannel( fchan, cchan );
      }
    }
  }

  // Column MultiDropChannels: one per (x, a, g), transposed from the row
  // construction above. Router a's g-th column output port is
  // [c+o+g] -- it comes right after the o row outputs above because
  // every router's row outputs are added to completion before any
  // column output is added, for any router.
  for ( int x = 0; x < _k; ++x ) {
    for ( int a = 0; a < _k; ++a ) {
      for ( int g = 0; g < _o; ++g ) {

        ostringstream cname;
        cname << "gec_col_x" << x << "_a" << a << "_g" << g;
        MultiDropChannel * fchan = new MultiDropChannel( this, cname.str(), _classes );
        cname.str("");
        cname << "gec_col_cred_x" << x << "_a" << a << "_g" << g;
        MultiDropCreditChannel * cchan = new MultiDropCreditChannel( this, cname.str() );

        fchan->SetLatency( 1 );
        cchan->SetLatency( 1 );
        _timed_modules.push_back( fchan );
        _timed_modules.push_back( cchan );
        _md_chan.push_back( fchan );
        _md_chan_cred.push_back( cchan );

        for ( int local = 0; local < _d; ++local ) {
          int const peer_idx = g * _d + local;
          int const b = ( peer_idx < a ) ? peer_idx : ( peer_idx + 1 );
          int const dst_node = b * _k + x;
          _routers[dst_node]->AddMultiDropInputChannel( fchan, cchan );
        }

        int const src_node = a * _k + x;
        _routers[src_node]->AddMultiDropOutputChannel( fchan, cchan );
      }
    }
  }
}

// ----------------------------------------------------------------------
// Hybrid: mesh + MECS on the same router set. Combines _BuildNetMesh's
// per-position variable mesh degree with _BuildNetMECS's row/column
// MultiDropChannel construction, unchanged from each. Port order per
// router (this is what hybrid_gec() must match): [0,c) local,
// [c,c+mesh_degree) mesh (west,east,north,south, only present ones, via
// MeshPortOffset/MeshDegreeAt), [c+mesh_degree,c+mesh_degree+o) row MECS
// groups, [c+mesh_degree+o,c+mesh_degree+2o) column MECS groups. Input
// tap order for the MECS taps doesn't need to match anything -- see the
// comment on this in _BuildNetMECS's design note in gec.hpp.
// ----------------------------------------------------------------------
void GEC::_BuildNetHybrid( const Configuration &config ) {

  ostringstream name;

  // Pass 1: create every router (with its position-dependent degree)
  // plus its local terminal and mesh ports. MECS ports get added in
  // passes 2 and 3 below, once every router object already exists.
  for ( int node = 0; node < _size; ++node ) {

    int x = node % _k;
    int y = node / _k;

    bool const west  = ( x > 0 );
    bool const east  = ( x < _k - 1 );
    bool const north = ( y > 0 );
    bool const south = ( y < _k - 1 );
    int const mesh_degree = MeshDegreeAt( x, y, _k );

    int const degree_out = _c + mesh_degree + 2 * _o;
    int const degree_in  = _c + mesh_degree + 2 * ( _k - 1 );

    name << "gec_router_" << y << '_' << x;
    _routers[node] = Router::NewRouter( config,
                                         this,
                                         name.str(),
                                         node,
                                         degree_in,
                                         degree_out );
    _timed_modules.push_back( _routers[node] );
    name.str("");

    // Local terminal ports: [0, c)
    for ( int t = 0; t < _c; ++t ) {
      int term = node * _c + t;

      _inject[term]->SetLatency( 1 );
      _inject_cred[term]->SetLatency( 1 );
      _eject[term]->SetLatency( 1 );
      _eject_cred[term]->SetLatency( 1 );

      _routers[node]->AddInputChannel( _inject[term], _inject_cred[term] );
      _routers[node]->AddOutputChannel( _eject[term], _eject_cred[term] );
    }

    // Mesh ports: [c, c+mesh_degree), fixed west/east/north/south order,
    // only added when the neighbor exists -- identical to _BuildNetMesh.
    if ( west ) {
      int out_id = _MeshRowChannelId( y, x, x - 1 );
      int in_id  = _MeshRowChannelId( y, x - 1, x );
      _chan[out_id]->SetLatency( 1 );      _chan_cred[out_id]->SetLatency( 1 );
      _chan[in_id]->SetLatency( 1 );       _chan_cred[in_id]->SetLatency( 1 );
      _routers[node]->AddOutputChannel( _chan[out_id], _chan_cred[out_id] );
      _routers[node]->AddInputChannel( _chan[in_id], _chan_cred[in_id] );
    }
    if ( east ) {
      int out_id = _MeshRowChannelId( y, x, x + 1 );
      int in_id  = _MeshRowChannelId( y, x + 1, x );
      _chan[out_id]->SetLatency( 1 );      _chan_cred[out_id]->SetLatency( 1 );
      _chan[in_id]->SetLatency( 1 );       _chan_cred[in_id]->SetLatency( 1 );
      _routers[node]->AddOutputChannel( _chan[out_id], _chan_cred[out_id] );
      _routers[node]->AddInputChannel( _chan[in_id], _chan_cred[in_id] );
    }
    if ( north ) {
      int out_id = _MeshColChannelId( x, y, y - 1 );
      int in_id  = _MeshColChannelId( x, y - 1, y );
      _chan[out_id]->SetLatency( 1 );      _chan_cred[out_id]->SetLatency( 1 );
      _chan[in_id]->SetLatency( 1 );       _chan_cred[in_id]->SetLatency( 1 );
      _routers[node]->AddOutputChannel( _chan[out_id], _chan_cred[out_id] );
      _routers[node]->AddInputChannel( _chan[in_id], _chan_cred[in_id] );
    }
    if ( south ) {
      int out_id = _MeshColChannelId( x, y, y + 1 );
      int in_id  = _MeshColChannelId( x, y + 1, y );
      _chan[out_id]->SetLatency( 1 );      _chan_cred[out_id]->SetLatency( 1 );
      _chan[in_id]->SetLatency( 1 );       _chan_cred[in_id]->SetLatency( 1 );
      _routers[node]->AddOutputChannel( _chan[out_id], _chan_cred[out_id] );
      _routers[node]->AddInputChannel( _chan[in_id], _chan_cred[in_id] );
    }
  }

  // Pass 2: row MultiDropChannels -- identical construction to
  // _BuildNetMECS's row loop.
  for ( int y = 0; y < _k; ++y ) {
    for ( int a = 0; a < _k; ++a ) {
      for ( int g = 0; g < _o; ++g ) {

        ostringstream cname;
        cname << "gec_hyb_row_y" << y << "_a" << a << "_g" << g;
        MultiDropChannel * fchan = new MultiDropChannel( this, cname.str(), _classes );
        cname.str("");
        cname << "gec_hyb_row_cred_y" << y << "_a" << a << "_g" << g;
        MultiDropCreditChannel * cchan = new MultiDropCreditChannel( this, cname.str() );

        fchan->SetLatency( 1 );
        cchan->SetLatency( 1 );
        _timed_modules.push_back( fchan );
        _timed_modules.push_back( cchan );
        _md_chan.push_back( fchan );
        _md_chan_cred.push_back( cchan );

        for ( int local = 0; local < _d; ++local ) {
          int const peer_idx = g * _d + local;
          int const b = ( peer_idx < a ) ? peer_idx : ( peer_idx + 1 );
          int const dst_node = y * _k + b;
          _routers[dst_node]->AddMultiDropInputChannel( fchan, cchan );
        }

        int const src_node = y * _k + a;
        _routers[src_node]->AddMultiDropOutputChannel( fchan, cchan );
      }
    }
  }

  // Pass 3: column MultiDropChannels -- identical to _BuildNetMECS's
  // column loop. Comes after every router's row outputs are complete,
  // so each router's column-group output ports land right after its
  // row-group ones, as the port-order comment above requires.
  for ( int x = 0; x < _k; ++x ) {
    for ( int a = 0; a < _k; ++a ) {
      for ( int g = 0; g < _o; ++g ) {

        ostringstream cname;
        cname << "gec_hyb_col_x" << x << "_a" << a << "_g" << g;
        MultiDropChannel * fchan = new MultiDropChannel( this, cname.str(), _classes );
        cname.str("");
        cname << "gec_hyb_col_cred_x" << x << "_a" << a << "_g" << g;
        MultiDropCreditChannel * cchan = new MultiDropCreditChannel( this, cname.str() );

        fchan->SetLatency( 1 );
        cchan->SetLatency( 1 );
        _timed_modules.push_back( fchan );
        _timed_modules.push_back( cchan );
        _md_chan.push_back( fchan );
        _md_chan_cred.push_back( cchan );

        for ( int local = 0; local < _d; ++local ) {
          int const peer_idx = g * _d + local;
          int const b = ( peer_idx < a ) ? peer_idx : ( peer_idx + 1 );
          int const dst_node = b * _k + x;
          _routers[dst_node]->AddMultiDropInputChannel( fchan, cchan );
        }

        int const src_node = a * _k + x;
        _routers[src_node]->AddMultiDropOutputChannel( fchan, cchan );
      }
    }
  }
}

// ----------------------------------------------------------------------
//  Routing: dimension-order (X then Y). In express mode this is a
//  direct 1-hop-per-dimension jump (diameter 2, matching Table 1). In
//  mesh mode it's a standard multi-hop mesh DOR walk, one grid step per
//  hop, toward the destination column then the destination row.
// ----------------------------------------------------------------------
void dor_gec( const Router *r, const Flit *f, int in_channel,
              OutputSet *outputs, bool inject ) {

  // Injection: r may be NULL here. Never dereference r before this
  // check returns.
  if ( inject ) {
    outputs->Clear();
    outputs->AddRange( -1, 0, gNumVCs - 1 );
    return;
  }

  int k = gK;
  int c = gC;

  int router = r->GetID();
  int dest   = f->dest;

  int dest_router = dest / c;

  int out_port = -1;
  // Default: use the full VC range, as for any non-multidrop port
  // (local terminal, mesh hop, or an express/MECS hop with d=1, where
  // tap is always 0 and this range is never narrowed below). Only a
  // MECS hop (d>1) narrows this to its tap's disjoint sub-range -- see
  // the comment on the num_vcs>=d check in _ComputeSize() for why.
  int vc_lo = 0;
  int vc_hi = gNumVCs - 1;

  if ( router == dest_router ) {
    // local terminal port
    out_port = dest % c;
  } else {
    int x  = router % k;
    int y  = router / k;
    int dx = dest_router % k;
    int dy = dest_router / k;

    if ( gGECMesh ) {
      if ( x != dx ) {
        GEC::MeshDir dir = ( dx > x ) ? GEC::MESH_EAST : GEC::MESH_WEST;
        int offset = GEC::MeshPortOffset( x, y, k, dir );
        assert( offset >= 0 ); // if this fires, the graph and the
                                // routing function disagree -- a bug,
                                // not a config issue
        out_port = c + offset;
      } else {
        assert( y != dy );
        GEC::MeshDir dir = ( dy > y ) ? GEC::MESH_SOUTH : GEC::MESH_NORTH;
        int offset = GEC::MeshPortOffset( x, y, k, dir );
        assert( offset >= 0 );
        out_port = c + offset;
      }
    } else {
      // Unified express (d=1) / MECS (d>1) case: peer_idx is the same
      // _PeerIndex() ordering _BuildNetExpress()/_BuildNetMECS() group
      // taps by; splitting it into (group, tap) = (peer_idx/d,
      // peer_idx%d) picks the same channel and the same tap on it that
      // construction registered for this (router, peer) pair. When
      // d=1, tap is always 0 and group==peer_idx, so this reduces to
      // exactly the old point-to-point formula.
      if ( x != dx ) {
        // row hop toward dx (direct, express/MECS)
        int peer_idx = ( dx < x ) ? dx : ( dx - 1 );
        out_port = c + peer_idx / gGECd;
        f->drop = peer_idx % gGECd;
      } else {
        // already in the right column, take the column hop toward dy
        assert( y != dy );
        int peer_idx = ( dy < y ) ? dy : ( dy - 1 );
        out_port = c + gGECo + peer_idx / gGECd;
        f->drop = peer_idx % gGECd;
      }
      if ( gGECd > 1 ) {
        // Give this hop's tap its own disjoint slice of the port's VCs
        // (floor(gNumVCs/d) each; any remainder is simply unused) so the
        // VC allocator's (out_port, out_vc) request key can never
        // conflate two different taps' flits into one false conflict.
        int const vcs_per_drop = gNumVCs / gGECd;
        vc_lo = f->drop * vcs_per_drop;
        vc_hi = vc_lo + vcs_per_drop - 1;
      }
    }
  }

  assert( out_port >= 0 );

  outputs->Clear();
  outputs->AddRange( out_port, vc_lo, vc_hi );
}

// ----------------------------------------------------------------------
//  Congestion-informed dimension-order choice. Identical to dor_gec()
//  except: when a packet still needs to resolve BOTH row and column (only
//  possible on its first hop, in_channel < c -- express/MECS resolves a
//  whole dimension in one hop, so diameter never exceeds 2), it compares
//  live occupancy (Router::GetUsedCredit) on the row candidate against
//  the column candidate and takes whichever is less busy, instead of
//  dor_gec's fixed "row always first." Ties broken randomly. Mesh mode
//  (gGECMesh) gets no adaptivity here -- falls back to the same
//  deterministic mesh walk dor_gec uses.
//
//  Deadlock: mixing "row-first" and "column-first" packets on shared VCs
//  is the classic 2-cycle (row_channel -> col_channel via row-first
//  packets, col_channel -> row_channel via col-first packets -- each
//  direction is fine alone, together they cycle). Fixed the same way
//  dor_gec's per-tap split avoids its own false-sharing problem: split
//  VCs by hop *rank* (this packet's first hop vs. its second/final hop),
//  not by which dimension went first. Rank strictly increases 1->2 on
//  every possible route regardless of which dimension is chosen when, so
//  the channel dependency graph stays acyclic. When MECS is also active,
//  each rank's half is further split into d per-tap sub-ranges exactly
//  like dor_gec's -- hence the num_vcs>=2*d floor in _ComputeSize().
// ----------------------------------------------------------------------
void adaptive_xy_yx_gec( const Router *r, const Flit *f, int in_channel,
                          OutputSet *outputs, bool inject ) {

  if ( inject ) {
    outputs->Clear();
    outputs->AddRange( -1, 0, gNumVCs - 1 );
    return;
  }

  int k = gK;
  int c = gC;

  int router = r->GetID();
  int dest   = f->dest;
  int dest_router = dest / c;

  int out_port = -1;
  int vc_lo = 0;
  int vc_hi = gNumVCs - 1;

  if ( router == dest_router ) {
    // local terminal port -- no phase/order concept applies
    out_port = dest % c;
  } else {
    int x  = router % k;
    int y  = router / k;
    int dx = dest_router % k;
    int dy = dest_router / k;

    if ( gGECMesh ) {
      if ( x != dx ) {
        GEC::MeshDir dir = ( dx > x ) ? GEC::MESH_EAST : GEC::MESH_WEST;
        int offset = GEC::MeshPortOffset( x, y, k, dir );
        assert( offset >= 0 );
        out_port = c + offset;
      } else {
        assert( y != dy );
        GEC::MeshDir dir = ( dy > y ) ? GEC::MESH_SOUTH : GEC::MESH_NORTH;
        int offset = GEC::MeshPortOffset( x, y, k, dir );
        assert( offset >= 0 );
        out_port = c + offset;
      }
    } else {
      bool const need_row = ( x != dx );
      bool const need_col = ( y != dy );
      assert( need_row || need_col ); // router != dest_router guarantees this

      // Robust "which hop is this" check: a packet needing only one
      // dimension finishes in 1 hop; one needing both takes exactly 2
      // (diameter <=2, see the function comment) -- so in_channel < c
      // (the local-terminal port range) can only be true on a genuine
      // first hop, never on a forced second hop.
      bool const first_hop = ( in_channel < c );

      bool take_row;
      if ( need_row && need_col ) {
        if ( first_hop ) {
          int const row_peer = ( dx < x ) ? dx : ( dx - 1 );
          int const row_port = c + row_peer / gGECd;
          int const row_drop = row_peer % gGECd;
          int const col_peer = ( dy < y ) ? dy : ( dy - 1 );
          int const col_port = c + gGECo + col_peer / gGECd;
          int const col_drop = col_peer % gGECd;

          int const row_credit = r->GetUsedCredit( row_port, row_drop );
          int const col_credit = r->GetUsedCredit( col_port, col_drop );

          if ( row_credit < col_credit ) {
            take_row = true;
          } else if ( col_credit < row_credit ) {
            take_row = false;
          } else {
            take_row = ( RandomInt( 1 ) > 0 );
          }
        } else {
          // Unreachable given diameter <=2, but stay deterministic
          // rather than assert if some future extension changes that.
          take_row = true;
        }
      } else {
        take_row = need_row; // forced: only one dimension left to resolve
      }

      int peer_idx, drop;
      if ( take_row ) {
        assert( need_row );
        peer_idx = ( dx < x ) ? dx : ( dx - 1 );
        out_port = c + peer_idx / gGECd;
      } else {
        assert( need_col );
        peer_idx = ( dy < y ) ? dy : ( dy - 1 );
        out_port = c + gGECo + peer_idx / gGECd;
      }
      drop = peer_idx % gGECd;
      f->drop = drop;

      // Hop-phase VC split (see the function comment for the deadlock
      // argument): first hop gets the lower half, second/final hop gets
      // the upper half. Any remainder from odd gNumVCs/gGECd is simply
      // unused, same convention dor_gec already uses for its own split.
      int const phase = first_hop ? 0 : 1;
      int const half = gNumVCs / 2;
      vc_lo = phase * half;
      vc_hi = vc_lo + half - 1;

      if ( gGECd > 1 ) {
        int const vcs_per_drop = half / gGECd;
        vc_lo = vc_lo + drop * vcs_per_drop;
        vc_hi = vc_lo + vcs_per_drop - 1;
      }
    }
  }

  assert( out_port >= 0 );

  outputs->Clear();
  outputs->AddRange( out_port, vc_lo, vc_hi );
}

// ----------------------------------------------------------------------
//  hybrid_gec: per-hop UGAL-style choice between a mesh step and a MECS
//  jump, while resolving X then Y (strict order -- no row/col-first
//  adaptivity stacked on top of this; that's adaptive_xy_yx_gec's own,
//  separate, orthogonal feature). Re-evaluated fresh at EVERY router
//  while a dimension is still unresolved, using CURRENT position -- so
//  a packet is free to mix mesh steps and a MECS jump within one phase
//  (e.g. two mesh steps then a MECS jump to finish X), not committed to
//  one or the other for the whole phase.
//
//  Cost model (real UGAL, unlike adaptive_xy_yx_gec's degenerate H=1-
//  for-both case): mesh's H is the REMAINING grid distance in this
//  dimension (it only advances one step per hop); MECS's H is always 1
//  (an express jump reaches the target row/column-mate in exactly one
//  hop, however far away it is -- that's what express channels are
//  for). cost = GetUsedCredit(candidate) * H; MECS is preferred on ties
//  (bias=0 here, exposed as a constant below for tuning).
// ----------------------------------------------------------------------
void hybrid_gec( const Router *r, const Flit *f, int in_channel,
                  OutputSet *outputs, bool inject ) {

  if ( inject ) {
    outputs->Clear();
    outputs->AddRange( -1, 0, gNumVCs - 1 );
    return;
  }

  int const k = gK;
  int const c = gC;
  // take_mesh is decided by a plain cost comparison below (mesh_cost <
  // mecs_cost, ties go to MECS). Three different damping schemes were
  // tried and rejected here (flat additive bias, multiplicative margin,
  // "only detour if mesh is strictly idle"): all of them reduced
  // hybrid's small, real cost under uniform traffic (~1-8% extra hops
  // vs plain dor_gec, from mesh and MECS getting identical cost weight
  // whenever mesh_H==1 and queues sit near equally loaded), but every
  // one of them did so by suppressing the *same signal* that produces
  // hybrid's large win under skewed traffic (30%+ throughput under
  // transpose) -- confirmed empirically each time: the more a damping
  // scheme closed the uniform-traffic gap, the more it also closed the
  // transpose-traffic win, down to erasing it completely. A single
  // instantaneous queue-occupancy reading cannot distinguish "real,
  // sustained congestion worth detouring for" from "momentary,
  // meaningless fluctuation" -- that would need a time-averaged signal
  // (e.g. an EWMA per port), not a smarter threshold on one snapshot.
  // Left undamped on purpose: the uniform-traffic cost is real but
  // small (~1% throughput-neutral latency tax), and not worth trading
  // away the much larger transpose-traffic win for.

  int const router = r->GetID();
  int const dest = f->dest;
  int const dest_router = dest / c;

  int out_port = -1;
  int vc_lo = 0;
  int vc_hi = gNumVCs - 1;

  if ( router == dest_router ) {
    // local terminal port -- no phase/mesh/MECS concept applies
    out_port = dest % c;
  } else {
    int const x  = router % k;
    int const y  = router / k;
    int const dx = dest_router % k;
    int const dy = dest_router / k;

    int const mesh_degree = GEC::MeshDegreeAt( x, y, k );
    bool const resolving_x = ( x != dx ); // if false, y != dy (router != dest_router guarantees one holds)

    int phase; // 0 = X, 1 = Y -- see the VC-split comment below for why
    bool take_mesh;

    if ( resolving_x ) {
      phase = 0;

      GEC::MeshDir const dir = ( dx > x ) ? GEC::MESH_EAST : GEC::MESH_WEST;
      int const mesh_offset = GEC::MeshPortOffset( x, y, k, dir );
      assert( mesh_offset >= 0 ); // a neighbor toward dx always exists: no
                                   // wraparound needed since dx is itself
                                   // a valid grid column
      int const mesh_port = c + mesh_offset;
      int const mesh_H = ( dx > x ) ? ( dx - x ) : ( x - dx );
      int const mesh_cost = r->GetUsedCredit( mesh_port ) * mesh_H;

      int const peer_idx = ( dx < x ) ? dx : ( dx - 1 );
      int const mecs_port = c + mesh_degree + peer_idx / gGECd;
      int const mecs_drop = peer_idx % gGECd;
      int const mecs_cost = r->GetUsedCredit( mecs_port, mecs_drop ) * 1;

      take_mesh = ( mesh_cost < mecs_cost );
      if ( take_mesh ) {
        out_port = mesh_port;
      } else {
        out_port = mecs_port;
        f->drop = mecs_drop;
      }
    } else {
      phase = 1;
      assert( y != dy );

      GEC::MeshDir const dir = ( dy > y ) ? GEC::MESH_SOUTH : GEC::MESH_NORTH;
      int const mesh_offset = GEC::MeshPortOffset( x, y, k, dir );
      assert( mesh_offset >= 0 );
      int const mesh_port = c + mesh_offset;
      int const mesh_H = ( dy > y ) ? ( dy - y ) : ( y - dy );
      int const mesh_cost = r->GetUsedCredit( mesh_port ) * mesh_H;

      int const peer_idx = ( dy < y ) ? dy : ( dy - 1 );
      int const mecs_port = c + mesh_degree + gGECo + peer_idx / gGECd;
      int const mecs_drop = peer_idx % gGECd;
      int const mecs_cost = r->GetUsedCredit( mecs_port, mecs_drop ) * 1;

      take_mesh = ( mesh_cost < mecs_cost );
      if ( take_mesh ) {
        out_port = mesh_port;
      } else {
        out_port = mecs_port;
        f->drop = mecs_drop;
      }
    }

    // Phase VC split: X-phase gets the lower half of the VC range,
    // Y-phase the upper half -- by PHASE (which dimension is being
    // resolved), not by hop-rank the way dor_gec's own MECS split is.
    // That distinction matters here specifically because a phase can
    // now span multiple hops (mesh steps don't finish a dimension in
    // one hop the way an express jump does), so "this packet's first
    // hop vs second hop" no longer lines up with "which dimension" --
    // but X-channels still only ever precede Y-channels in any route
    // (strict order, enforced above), so the same acyclic-rank argument
    // holds with phase defined this way instead.
    int const half = gNumVCs / 2;
    vc_lo = phase * half;
    vc_hi = vc_lo + half - 1;

    if ( !take_mesh && gGECd > 1 ) {
      int const vcs_per_drop = half / gGECd;
      vc_lo = vc_lo + f->drop * vcs_per_drop;
      vc_hi = vc_lo + vcs_per_drop - 1;
    }
  }

  assert( out_port >= 0 );

  outputs->Clear();
  outputs->AddRange( out_port, vc_lo, vc_hi );
}
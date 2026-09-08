// ----------------------------------------------------------------------
//
// GEC: Generalized Express Cubes
//
// Implements two REAL, config-selectable connectivity modes from the
// GEC design space in Grot, Hestness, Keckler, Mutlu, "Express Cube
// Topologies for On-Chip Interconnects," HPCA 2009:
//
//   1. "mesh"    (o=1, d=1, nearest-neighbor only)   -> Mesh / CMesh graph
//   2. "express" (o=k-1, d=1, full row/column)        -> flattened-butterfly
//                                                         graph
//
// Six-tuple <n, k, c, o, d, x>:
//   n - dimensionality              (fixed to 2)
//   k - radix (routers per dim)     -> config "k"
//   c - concentration factor        -> config "c"
//   o - output channels/dim/node    -> config "o" (validated, see below)
//   d - channel radix (sinks/chan)  -> config "d" (validated, see below)
//   x - replicated networks         -> use BookSim's native "subnets";
//       GEC does not implement x itself. NOT independently verified
//       against trafficmanager.cpp/main.cpp semantics yet -- do that
//       before trusting subnets-based x for a paper number.
//
// ------------------------- WHAT IS AND ISN'T REAL HERE -----------------
// mesh=1  -> real nearest-neighbor-only graph, variable router degree at
//            edges/corners (c + 2..4 dimension ports). o and d MUST be 1
//            in this mode (the paper's mesh case isn't "complete graph
//            partitioned into groups of 1" -- it's a structurally
//            different, physically-adjacent-only graph, so o/d partition
//            semantics don't apply to it; asking for anything else here
//            is a config error, not silently ignored).
//
// mesh=0, o=k-1, d=1 -> real full row/column point-to-point graph
//            (every router connects directly to every other router in
//            its row and its column). This is the flattened-butterfly
//            corner of the GEC space. pout = c + 2*(k-1), matching the
//            paper's OWN flattened-butterfly port count.
//
// mesh=0, o<k-1 (i.e. d = (k-1)/o > 1) -> MECS / MECS-P family. Real
//            shared/tapped channels, via MultiDropChannel (see
//            multidropchannel.hpp): each router drives o output
//            channels per dimension (pout = c + 2*o, constant in k, per
//            Table 1) and each output channel is tapped by d peers.
//
//            Grouping convention: within a row (or column), router a's
//            k-1 peers are ordered by peer index
//            (b < a ? b : b-1, i.e. "all other routers in ascending
//            order, self skipped" -- the same _PeerIndex() ordering the
//            o=k-1 express corner already uses), then split into o
//            contiguous groups of d. Peer group g = peer_idx / d is
//            reached over router a's g-th output channel; within that
//            channel the peer is tap number peer_idx % d. dor_gec()
//            computes this exact same (group, tap) pair when routing,
//            so construction and routing can never disagree -- the same
//            discipline MeshPortOffset() already uses for mesh mode.
//
//            Because each router only has ONE MultiDropChannel per
//            (dimension, group), but is a tap on up to k-1 other
//            routers' channels, input port count grows with k even
//            though output port count doesn't -- this asymmetry (cheap
//            passive taps vs. expensive active drivers) is the actual
//            point of MECS, not a modeling artifact.
//
//            Lookahead routing (routing_delay=0) is refused for d>1:
//            IQRouter's lookahead path resolves the next hop via
//            FlitChannel::GetSink(), which only tracks the last-
//            registered tap on a multidrop channel, not the specific
//            tap a given flit is addressed to. Deferred routing (the
//            default, routing_delay>0) always asks the actual router
//            for its own ID and has no such ambiguity, so it is
//            unaffected.
//
// x (replication) is not implemented natively; the README documents how
// to use "subnets" and flags that its exact semantics have not yet been
// checked against the BookSim source for this project.
//
// hybrid=1 (mesh=0 required) -> mesh + MECS layered on the SAME router
//            set: every router keeps its up-to-4 nearest-neighbor mesh
//            links (built exactly like mesh=1's graph) AND o MECS
//            express channels per dimension on top (built exactly like
//            the o<k-1 MECS case above, same grouping convention).
//            hybrid_gec() re-evaluates, at every hop while a dimension
//            is still unresolved, whether to take one mesh step (cost
//            = queue_occupancy * remaining_grid_distance) or the MECS
//            jump (cost = queue_occupancy * 1, since an express jump
//            always reaches the target row/column-mate in exactly one
//            hop regardless of distance) -- the real UGAL-shaped
//            min-vs-nonmin decision this project has been building
//            toward, unlike adaptive_xy_yx_gec's degenerate H=1-for-
//            both row/column choice. Deadlock safety: strict X-then-Y
//            phase order (a phase may now span multiple hops, since
//            mesh steps don't resolve a whole dimension in one hop the
//            way an express jump does), VC space split in half by
//            phase -- NOT by hop-rank the way dor_gec's MECS-only case
//            is, because a phase is no longer capped at one hop -- and
//            each half further split by MECS tap when d>1. Needs
//            num_vcs >= 2*d, same floor and same reasoning as
//            adaptive_xy_yx_gec.
// ----------------------------------------------------------------------

#ifndef _GEC_HPP_
#define _GEC_HPP_

#include "network.hpp"
#include "routefunc.hpp"

class GEC : public Network {
public:
  GEC( const Configuration &config, const string & name );

  int  GetN() const;
  int  GetK() const;
  int  GetC() const;
  int  GetO() const;
  int  GetD() const;
  bool IsMesh() const;

  static void RegisterRoutingFunctions();

  // Direction enum shared between _BuildNet (assigns ports) and
  // dor_gec (routes into ports) so the two can never disagree about
  // which physical port a given direction maps to on a given router.
  enum MeshDir { MESH_WEST = 0, MESH_EAST = 1, MESH_NORTH = 2, MESH_SOUTH = 3 };

  // Returns the 0-based offset (added to c local-terminal ports) of
  // the channel for `dir` at grid position (x,y) in a k x k mesh, or
  // -1 if that direction doesn't exist for this router (boundary).
  // Deterministic order: west, east, north, south, each counted only
  // if present. Static + stateless so both _BuildNet and dor_gec call
  // the exact same function -- no separate lookup table to drift out
  // of sync.
  static int MeshPortOffset( int x, int y, int k, MeshDir dir );

  // Number of present mesh neighbor directions at grid position (x,y) --
  // shared by _BuildNetHybrid (to size router degree) and hybrid_gec (to
  // compute port offsets), same discipline as MeshPortOffset. Public for
  // the same reason MeshPortOffset is: hybrid_gec is a free function.
  static int MeshDegreeAt( int x, int y, int k );

private:
  int  _k;      // radix per dimension
  int  _c;      // concentration factor (terminals per router)
  int  _n;      // dimensionality (must be 2 for this implementation)
  int  _o;      // output channels per dimension per node
  int  _d;      // channel radix (sinks per channel); o*d == k-1 required
  bool _mesh;   // true -> nearest-neighbor mesh graph, false -> express graph
  bool _hybrid; // true -> mesh + MECS layered together (mesh must be false)

  int _degree; // used only in express mode: c + 2*(k-1), uniform for all routers

  void _ComputeSize( const Configuration &config );
  void _BuildNet( const Configuration &config );

  void _BuildNetExpress( const Configuration &config );
  void _BuildNetMesh( const Configuration &config );
  void _BuildNetMECS( const Configuration &config );
  void _BuildNetHybrid( const Configuration &config );

  // ---- express-mode (full row/column, o=k-1,d=1) channel id helpers ----
  static int _PeerIndex( int self, int peer );
  int _RowChannelId( int y, int a, int b ) const;
  int _ColChannelId( int x, int a, int b ) const;

  // ---- mesh-mode (nearest-neighbor only) channel id helpers ----
  // a,b must be adjacent (|a-b| == 1).
  int _MeshRowChannelId( int y, int a, int b ) const;
  int _MeshColChannelId( int x, int a, int b ) const;
};

void dor_gec( const Router *r, const Flit *f, int in_channel,
              OutputSet *outputs, bool inject );

// Congestion-informed choice of which dimension to resolve first (row or
// column), made once per packet at its first hop; deterministic dor_gec
// dimension-order routing otherwise. See the design note above _ComputeSize's
// num_vcs>=2*d check in gec.cpp for the deadlock argument.
void adaptive_xy_yx_gec( const Router *r, const Flit *f, int in_channel,
                          OutputSet *outputs, bool inject );

// Per-hop UGAL-style choice between a mesh step and a MECS jump while
// resolving each dimension in turn (X then Y). See the design note above
// for the cost formula and deadlock argument. hybrid=1 only.
void hybrid_gec( const Router *r, const Flit *f, int in_channel,
                  OutputSet *outputs, bool inject );

#endif
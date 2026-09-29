// ----------------------------------------------------------------------
//
//  SrotaRouterD -- the Plane D router of SSM-UARCH-VC-002 rev 0.3, with
//  the QoS island wrapper of SSM-UARCH-TOPO-003 rev 0.3 section 7.5.
//
//  An IQRouter whose storage model is the spec's, not BookSim's:
//
//  STAGING LATCH (VC-002 section 2.2). Each input advertises a credit
//  window of vc_buf_size flits per VC -- the 2-flit staging latch at the
//  spec default. Upstream routers and the injecting terminal see only
//  that window.
//
//  SHARED SIDE BUFFER (VC-002 sections 2.3, 7.2, 10, 11.2). One buffer of
//  srota_sb_depth flits per router, shared across every input port. A
//  flit enters it only when it bid for the switch and LOST to another
//  input (the alloc_loss condition) -- never because it lacked
//  downstream credit, which the spec masks out before arbitration. On
//  capture the flit's staging slot frees, so its credit goes back
//  upstream immediately; when the flit later drains, no second credit
//  is sent. That early credit is the entire performance effect of the
//  side buffer, and it is what makes a 2-flit staging latch behave like
//  a deeper queue exactly when -- and only when -- allocation contention
//  exists.
//
//     Drain (section 2.3, 7.4): one buffered flit per router is offered
//     for re-injection per cycle (srota_sidebuf_arb has a single sb_rd
//     port) and it competes on equal terms with fresh arrivals -- no
//     priority either way.
//
//     Overflow (section 2.3, 6.4): a loser that finds the buffer full is
//     simply not captured. Its staging slot stays occupied, so credit is
//     withheld upstream -- backpressure, never a drop.
//
//     Ordering (F6, section 11.2's sidebuf_pending): a buffered flit
//     stays at the front of its input's FIFO, so a newer flit of the same
//     port cannot overtake it. This is the conservative reading of the
//     bypass-inhibit term, and it has a consequence worth knowing: each
//     input VC holds at most ONE side-buffer entry, so the buffer can only
//     fill when at least srota_sb_depth inputs are losing at once. See
//     SROTA.md, "Side buffer".
//
//     Watermark (section 13.3 VC_SIDEBUF_WATERMARK): occupancy above
//     srota_sb_watermark raises a congestion hint that the Plane T model
//     folds into this router's occupancy nibble.
//
//  ISLAND WRAPPER (TOPO-003 sections 4, 7.5). When the router sits in an
//  island column it gets srota_qos_class_account (per-class arrivals,
//  grants, deferrals) and srota_qos_rate_regulator (a token bucket per
//  class) in front of the resource attach queue -- i.e. on every flit
//  switched to a local ejection port. A class without tokens defers: it
//  does not bid this cycle. The router inside the wrapper is otherwise
//  unmodified, as section 7.5 requires. The token-bucket field layout of
//  TOPO_ISL_RATE_CFG is "owned by the QoS section of #2", which VC-002
//  does not yet contain; the parameters here (rate in flits/cycle, burst
//  in flits) are this model's choice, not the spec's.
//
// ----------------------------------------------------------------------

#ifndef _SROTA_ROUTER_D_HPP_
#define _SROTA_ROUTER_D_HPP_

#include <vector>
#include <ostream>

#include "iq_router.hpp"

struct SrotaRouterDParams {
  int  sb_depth;              // srota_sb_depth      VC-002 13.6, 4-16, default 8
  int  sb_watermark;          // srota_sb_watermark  VC_SIDEBUF_WATERMARK, default 6
  int  local_ports;           // c -- output ports [0, c) are the attach queue
  bool island;                // this router is wrapped in srota_island_wrap
  vector<double> isl_rate;    // per QoS class, flits/cycle; <= 0 = unregulated
  double isl_burst;           // token-bucket depth, flits
  bool isl_class_is_slack;    // QoS class from the slack field, else Flit::cl
};

// Counters, named after the VC-002 section 13.5 / TOPO-003 section 13.5
// registers they model. Whole-run totals (not reset at warm-up).
struct SrotaRouterDStats {
  long sb_fill;        // VC_CNT_SB_FILL
  long sb_drain;       // VC_CNT_SB_DRAIN
  long sb_full_cyc;    // VC_CNT_SB_FULL_CYC
  long sb_full_reject; // losers not captured because the buffer was full
  long sb_wm_cyc;      // cycles above VC_SIDEBUF_WATERMARK
  long sb_occ_sum;     // for mean occupancy
  long cycles;
  int  sb_peak;
  long alloc_losses;   // alloc_loss events, captured or not
  vector<long> isl_arrive;   // per class: flits that asked for the attach queue
  vector<long> isl_grant;    // per class: flits admitted
  vector<long> isl_defer;    // TOPO_CNT_ISL_DEFER, per class, distinct flits
  vector<long> isl_defer_cyc;// per class, flit-cycles spent deferred
};

class SrotaRouterD : public IQRouter {
public:
  // phys_config sizes this router's own input buffers (the staging
  // window plus room for the side-buffer entry an input can hold);
  // credit_config is the window it advertises and assumes of its
  // neighbours. Both must outlive the router -- SrotaNoC owns them.
  SrotaRouterD( Configuration const & phys_config,
                Configuration const & credit_config,
                Module * parent, string const & name, int id,
                int inputs, int outputs, SrotaRouterDParams const & p );

  int  SideBufOccupancy() const { return _sb_occ; }
  bool WatermarkExceeded() const { return _sb_occ > _p.sb_watermark; }
  bool IsIsland() const { return _p.island; }
  SrotaRouterDStats const & Stats() const { return _st; }

  // Storage this router actually represents in hardware: the staging
  // window on every input plus the one shared side buffer.
  virtual int StorageFlits() const;

protected:
  virtual void _InternalStep( );
  virtual bool _SWAllocGate( int input, int vc, int output, Flit const * f );
  virtual void _SWAllocLost( int input, int vc, Flit * f );
  virtual bool _CreditOnDepart( int input, int vc, Flit const * f );

private:
  SrotaRouterDParams _p;
  int _window;                 // credit window per VC (staging depth)

  // Side buffer. _sb_id[input*_vcs+vc] is the id of the flit at the front
  // of that VC that lives in the side buffer, or -1.
  vector<int> _sb_id;
  int  _sb_occ;
  bool _drain_offered;         // single sb_rd port: one offer per cycle

  // Island regulator.
  vector<double> _tokens;
  int _last_refill;
  // Tokens taken this cycle by bids that may still lose; refunded next
  // cycle unless the flit actually departed.
  struct TokenHold { int slot; int cl; int fid; };
  vector<TokenHold> _held;
  vector<int> _deferred_fid;   // per (input,vc): last flit counted as deferred
  vector<int> _arrive_fid;     // per (input,vc): last flit counted as arrived
  vector<int> _eject_fid;      // per (input,vc): flit whose bid for the attach queue passed the gate

  SrotaRouterDStats _st;

  int  _QosClass( Flit const * f ) const;
  void _Refill();
};

#endif

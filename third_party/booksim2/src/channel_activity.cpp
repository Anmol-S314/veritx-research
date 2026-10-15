// channel_activity.cpp — versioned per-channel measurement emission.
// See channel_activity.hpp for the contract.

#include <iostream>

#include "channel_activity.hpp"
#include "networks/network.hpp"
#include "routers/router.hpp"
#include "routers/iq_router.hpp"
#include "power/switch_monitor.hpp"
#include "power/buffer_monitor.hpp"

// ---- Sampled per-window series --------------------------------------
//
// Id packing (see header for decode): subnet * 1e8 + router * 1e4 + port.
namespace {
const long TS_SUBNET_STRIDE = 100000000L ;
const long TS_ROUTER_STRIDE = 10000L ;
const long TS_MAX_ROUTER_ID = 100000L ;
const long TS_MAX_PORTS = 10000L ;
const char * const TS_CAPACITY_FORMULA =
  "flits_per_window/(window_cycles*link_capacity_flits_per_cycle)" ;

struct TsChannel {
  long id ;
  std::vector<long> wins ;  // one delta per completed window
  std::vector<long> spans ; // true cycle span of each window
  std::vector<long> base ;  // single cumulative total at last snapshot
  // ---- v3 extended series (Phase A): telescoping sums use the same
  // delta-of-cumulative pattern as flits (q/a/tx-grants differenced
  // against router cumulatives; occupancy/tx-busy accumulated by the
  // sampler's once-per-cycle walk); the three maxima are window-local.
  std::vector<long> qwins ; // queue_cycles deltas
  long qbase ;              // queue_cycles cumulative at last snapshot
  std::vector<long> awins ; // arb_wait_cycles deltas
  long abase ;
  std::vector<long> txwins ; // tx_flits (grants) deltas
  long txbase ;
  long occ_cum ;            // occupancy_flit_cycles running total
  long occ_base ;           // ... at last snapshot
  std::vector<long> occwins ;
  long txb_cum ;            // tx_busy_cycles running total
  long txb_base ;
  std::vector<long> txbwins ;
  long occ_maxw ;           // occupancy window-local maximum depth
  std::vector<long> occmaxwins ;
  std::vector<long> qmaxwins ; // queue/arb window-local maxima
  std::vector<long> amaxwins ;
};

struct TsRouter {
  IQRouter * iq ;           // cached live router, null where unmonitorable
  std::vector<TsChannel> outs ;
};

bool ts_armed = false ;
long ts_period = 0 ;
long ts_windows = 0 ;
long ts_resets = 0 ;
long ts_last_poll = 0 ; // poll-clock: exactly one backward step per epoch
long ts_window_start = 0 ; // sim-time the current window opened
long ts_next_boundary = 0 ; // next per-epoch window boundary
long ts_ext_last = -1 ; // sampler walk clock: walk runs once per cycle
bool ts_corrupt = false ;
TimeseriesConfig ts_cfg ;
// Wall-time boundaries per sim epoch. BookSim wall time resets to 0
// every sim (TrafficManager::Run), so each epoch restarts boundaries
// at its own observed start and edge slices are handled explicitly
// (see Poll). Monitor counters are monotonic across epochs, so
// conservation telescopes exactly no matter how many sims ran.
// ts_nets[s][r] parallels the live routers; null where unmonitorable.
struct TsNet { std::vector<TsRouter> routers ; long skipped ; } ;
std::vector<TsNet> ts_state ;
std::vector<Network *> ts_live ;

void ts_escape_json( std::ostream & os, std::string const & s ) {
  for ( size_t k = 0 ; k < s.size() ; ++k ) {
    char ch = s[k] ;
    if ( ch == '"' || ch == '\\' ) os << '\\' ;
    os << ch ;
  }
}

SwitchMonitor const * ts_sw( Network * net, size_t r ) {
  vector<Router *> const & rs = net->GetRouters() ;
  if ( r >= rs.size() || !rs[r] ) return 0 ;
  IQRouter const * iq = dynamic_cast<IQRouter const *>( rs[r] ) ;
  if ( !iq ) return 0 ;
  return iq->GetSwitchMonitor() ;
}

// Once-per-cycle sampler walk (Phase A): accumulates the per-output
// occupancy integral and tx-busy cycles, and tracks the occupancy
// window maximum. Runs at most once per distinct sim-time value —
// GetSimTime() is called many times per cycle — so each cycle is
// counted exactly once. Window-close captures run BEFORE this walk in
// Poll, so cycle T belongs to the window that opens at T: a window
// [T,T') counts exactly T'−T cycles, matching its true span. Cache the
// live IQRouter pointers from Init; sizes are re-checked every walk so
// a topology surprise corrupts the run loudly, never silently.
void ts_ext_walk( long sim_time ) {
  if ( !ts_armed || ts_corrupt ) return ;
  if ( sim_time == ts_ext_last ) return ;
  ts_ext_last = sim_time ;
  for ( size_t s = 0 ; s < ts_state.size() ; ++s ) {
    for ( size_t r = 0 ; r < ts_state[s].routers.size() ; ++r ) {
      TsRouter & tr = ts_state[s].routers[r] ;
      IQRouter * iq = tr.iq ;
      if ( !iq ) continue ;
      if ( (int)tr.outs.size() != iq->TsOutNum() ) {
        cerr << "channel_timeseries: output count changed on subnet "
             << s << " router idx " << r << " — refusing a series "
             << "that cannot telescope exactly" << endl ;
        ts_corrupt = true ; return ;
      }
      int const nin = iq->TsInNum() ;
      int const nvc = iq->TsVCNum() ;
      for ( int i = 0 ; i < nin ; ++i ) {
        for ( int v = 0 ; v < nvc ; ++v ) {
          int const o = iq->TsVCOut( i, v ) ;
          if ( o < 0 ) continue ; // routing/vc_alloc: documented residual
          if ( o >= (int)tr.outs.size() ) {
            cerr << "channel_timeseries: VC output out of range on subnet "
                 << s << " router idx " << r << endl ;
            ts_corrupt = true ; return ;
          }
          long const n = iq->TsVCOcc( i, v ) ;
          tr.outs[o].occ_cum += n ;
          if ( n > tr.outs[o].occ_maxw ) tr.outs[o].occ_maxw = n ;
        }
      }
      for ( size_t o = 0 ; o < tr.outs.size() ; ++o ) {
        if ( iq->TsOutBusy( (int)o ) ) ++tr.outs[o].txb_cum ;
      }
    }
  }
}

// Snapshot cumulative per-(output) totals into `tot` (summed over inputs
// and classes, mirroring the cumulative dump exactly).
void ts_snapshot( std::vector<long> & tot ) {
  tot.clear() ;
  for ( size_t s = 0 ; s < ts_live.size() ; ++s ) {
    vector<Router *> const & rs = ts_live[s]->GetRouters() ;
    for ( size_t r = 0 ; r < rs.size() ; ++r ) {
      SwitchMonitor const * sw = ts_sw( ts_live[s], r ) ;
      if ( !sw ) continue ;
      int const inputs = sw->NumInputs() ;
      int const outputs = sw->NumOutputs() ;
      int const classes = sw->NumClasses() ;
      for ( int o = 0 ; o < outputs ; ++o ) {
        long total = 0 ;
        for ( int i = 0 ; i < inputs ; ++i )
          for ( int c = 0 ; c < classes ; ++c ) total += sw->At( i, o, c ) ;
        tot.push_back( total ) ;
      }
    }
  }
}

// Order of ts_snapshot totals matches ts_state channel order by
// construction (same traversal). Deltas append one window per channel
// with its TRUE span (capture time minus window start). Late polls
// make spans longer than the nominal period; recording the truth keeps
// denominators exact. Counters are monotonic, so a negative delta
// means memory corruption or a reused router — fail closed.
// A non-positive span with pending flits (sub-cycle edge slice, see
// Poll) folds forward: the baseline advances without emitting, and the
// flits join the next window. Spans stay positive; conservation stays
// exact; the fold is documented in the header.
bool ts_capture_window( long span, bool fold ) {
  std::vector<long> cur ;
  ts_snapshot( cur ) ;
  size_t k = 0 ;
  for ( size_t s = 0 ; s < ts_state.size() ; ++s ) {
    for ( size_t r = 0 ; r < ts_state[s].routers.size() ; ++r ) {
      TsRouter & tr = ts_state[s].routers[r] ;
      IQRouter * iq = tr.iq ;
      if ( !iq || (int)tr.outs.size() != iq->TsOutNum() ) {
        cerr << "channel_timeseries: router tracking lost on subnet "
             << s << " router idx " << r << endl ;
        ts_corrupt = true ; return false ;
      }
      for ( size_t o = 0 ; o < tr.outs.size() ; ++o, ++k ) {
        TsChannel & ch = tr.outs[o] ;
        long delta = cur[k] - ch.base[0] ;
        if ( delta < 0 ) {
          cerr << "channel_timeseries: counter regression on subnet "
               << s << " router idx " << r << " port " << o
               << " (id " << ch.id << "): baseline "
               << ch.base[0] << " now " << cur[k] << endl ;
          ts_corrupt = true ; return false ;
        }
        // v3 extended sums: differenced against the router cumulatives,
        // read in channel order (order-safe by construction, no second
        // snapshot vector). Window-local grant maxima are read but only
        // cleared on emit; a fold carries them into the next window.
        long const qcur = iq->TsQSum( (int)o ) ;
        long const acur = iq->TsASum( (int)o ) ;
        long const txcur = iq->TsTxG( (int)o ) ;
        long const qd = qcur - ch.qbase ;
        long const ad = acur - ch.abase ;
        long const txd = txcur - ch.txbase ;
        long const occd = ch.occ_cum - ch.occ_base ;
        long const txbd = ch.txb_cum - ch.txb_base ;
        if ( qd < 0 || ad < 0 || txd < 0 || occd < 0 || txbd < 0 ) {
          cerr << "channel_timeseries: extended counter regression on "
               << "subnet " << s << " router idx " << r << " port " << o
               << " (id " << ch.id << ")" << endl ;
          ts_corrupt = true ; return false ;
        }
        if ( !fold ) {
          ch.wins.push_back( delta ) ;
          ch.spans.push_back( span ) ;
          ch.qwins.push_back( qd ) ;
          ch.awins.push_back( ad ) ;
          ch.txwins.push_back( txd ) ;
          ch.occwins.push_back( occd ) ;
          ch.txbwins.push_back( txbd ) ;
          ch.qmaxwins.push_back( iq->TsQMaxW( (int)o ) ) ;
          ch.amaxwins.push_back( iq->TsAMaxW( (int)o ) ) ;
          ch.occmaxwins.push_back( ch.occ_maxw ) ;
          ch.occ_maxw = 0 ;
        }
        ch.base[0] = cur[k] ;
        ch.qbase = qcur ;
        ch.abase = acur ;
        ch.txbase = txcur ;
        ch.occ_base = ch.occ_cum ;
        ch.txb_base = ch.txb_cum ;
      }
    }
  }
  if ( !fold ) {
    ++ts_windows ;
    // Window-local grant maxima reset on emit (a fold carries them
    // into the next window instead).
    for ( size_t s = 0 ; s < ts_state.size() ; ++s )
      for ( size_t r = 0 ; r < ts_state[s].routers.size() ; ++r )
        if ( ts_state[s].routers[r].iq )
          ts_state[s].routers[r].iq->TsClearWMax() ;
  }
  return true ;
}
} // namespace

// External linkage (declared in channel_activity.hpp): router
// instrumentation calls this on its hot paths, so it must be visible
// across translation units. `ts_armed` above has internal linkage but
// lives in this TU, so this accessor is exact.
bool TimeseriesExtArmed( ) {
  return ts_armed ;
}

bool TimeseriesSamplerInit( Network * const * nets, int subnets,
                            const TimeseriesConfig & cfg ) {
  ts_cfg = cfg ;
  ts_period = cfg.sample_period_cycles ;
  ts_live.assign( nets, nets + subnets ) ;
  ts_state.clear() ;
  ts_state.resize( subnets ) ;
  for ( int s = 0 ; s < subnets ; ++s ) {
    vector<Router *> const & rs = nets[s]->GetRouters() ;
    ts_state[s].skipped = 0 ;
    for ( size_t r = 0 ; r < rs.size() ; ++r ) {
      SwitchMonitor const * sw = ts_sw( nets[s], r ) ;
      if ( !sw ) { ++ts_state[s].skipped ; continue ; }
      IQRouter * iq = dynamic_cast<IQRouter *>( rs[r] ) ;
      if ( !iq ) { ++ts_state[s].skipped ; continue ; }
      int const outputs = sw->NumOutputs() ;
      if ( outputs >= TS_MAX_PORTS ) return false ;
      long rid = (long)rs[r]->GetID() ;
      if ( rid < 0 || rid >= TS_MAX_ROUTER_ID ) return false ;
      TsRouter tr ;
      tr.iq = iq ;
      for ( int o = 0 ; o < outputs ; ++o ) {
        TsChannel ch ;
        ch.id = s * TS_SUBNET_STRIDE + rid * TS_ROUTER_STRIDE + o ;
        ch.base.push_back( 0 ) ; // baseline snapshot below
        ch.qbase = 0 ; ch.abase = 0 ; ch.txbase = 0 ;
        ch.occ_cum = 0 ; ch.occ_base = 0 ;
        ch.txb_cum = 0 ; ch.txb_base = 0 ;
        ch.occ_maxw = 0 ;
        tr.outs.push_back( ch ) ;
      }
      ts_state[s].routers.push_back( tr ) ;
    }
  }
  // Baseline: cumulative counters are fresh (zero), but snapshot for
  // real so a mid-run arm would still telescope correctly.
  std::vector<long> cur ;
  ts_snapshot( cur ) ;
  size_t k = 0 ;
  for ( size_t s = 0 ; s < ts_state.size() ; ++s )
    for ( size_t r = 0 ; r < ts_state[s].routers.size() ; ++r ) {
      IQRouter * iq = ts_state[s].routers[r].iq ;
      for ( size_t o = 0 ; o < ts_state[s].routers[r].outs.size() ; ++o, ++k ) {
        ts_state[s].routers[r].outs[o].base[0] = cur[k] ;
        if ( iq ) {
          ts_state[s].routers[r].outs[o].qbase = iq->TsQSum( (int)o ) ;
          ts_state[s].routers[r].outs[o].abase = iq->TsASum( (int)o ) ;
          ts_state[s].routers[r].outs[o].txbase = iq->TsTxG( (int)o ) ;
        }
      }
    }
  ts_window_start = 0 ;
  ts_next_boundary = ts_period ;
  ts_last_poll = 0 ;
  ts_ext_last = -1 ;
  ts_resets = 0 ;
  ts_windows = 0 ;
  ts_corrupt = false ;
  ts_armed = true ;
  return true ;
}

void TimeseriesSamplerPoll( int sim_time ) {
  if ( !ts_armed || ts_corrupt ) return ;
  // Epoch handling: BookSim wall time resets to 0 every sim, while
  // the monitor counters behind the baselines never reset. On the one
  // backward step per epoch boundary, close the epoch's edge slice as
  // its own window (true span: last observed pre-reset time minus
  // window start), re-baseline, and restart boundaries at the new
  // epoch's observed start. A zero-advance edge (sub-cycle slice:
  // counters moved with no observed time advance) folds forward —
  // baseline advances, no window emitted — so spans stay positive and
  // every flit is still counted exactly once. Conservation telescopes
  // across any number of sims by construction.
  if ( sim_time < ts_last_poll ) {
    ++ts_resets ;
    long edge = ts_last_poll - ts_window_start ;
    if ( edge <= 0 ) {
      if ( !ts_capture_window( 0, true ) ) return ;
    } else {
      if ( !ts_capture_window( edge, false ) ) return ;
    }
    ts_window_start = sim_time ;
    ts_next_boundary = sim_time + ts_period ;
  }
  ts_last_poll = sim_time ;
  while ( sim_time >= ts_next_boundary ) {
    if ( !ts_capture_window( sim_time - ts_window_start, false ) ) return ;
    ts_window_start = sim_time ;
    ts_next_boundary += ts_period ;
  }
  // Occupancy/tx-busy walk runs AFTER any boundary captures above, so
  // the current cycle is counted into the window that opens here.
  ts_ext_walk( sim_time ) ;
}

void ts_emit_longs( std::ostream & os, std::vector<long> const & v ) {
  for ( size_t w = 0 ; w < v.size() ; ++w ) {
    if ( w ) os << "," ;
    os << v[w] ;
  }
}

bool DumpChannelTimeseries( std::ostream & os, int sim_end_time ) {
  if ( ts_corrupt ) {
    ts_armed = false ;
    cerr << "channel_timeseries: counter regression detected "
         << "(a window delta went negative) — refusing a series "
         << "that cannot telescope exactly" << endl ;
    return false ;
  }
  // Close the occupancy gap: the walk counts each distinct sim-time once,
  // and no poll may have run at exactly the final time. Networks are
  // still alive here (main.cpp dumps before deleting them); the walk
  // skips itself when the final cycle was already counted.
  ts_ext_walk( sim_end_time ) ;
  ts_armed = false ;
  // Trailing partial window: the run ends mid-window. Its true span is
  // recorded like any other, so denominators stay exact and nothing is
  // dropped (dropping would break telescoping) or padded (padding
  // would invent flits). A run that never advanced gains no window.
  if ( sim_end_time > ts_window_start &&
       !ts_capture_window( sim_end_time - ts_window_start, false ) )
    return false ;
  long nwin = ts_windows ;
  os << "{\"schema_version\":3" ;
  os << ",\"run_hash\":\"" ;
  ts_escape_json( os, ts_cfg.run_hash ) ;
  os << "\"" ;
  os << ",\"sample_period_cycles\":" << ts_period ;
  os << ",\"num_windows\":" << nwin ;
  os << ",\"time_resets_observed\":" << ts_resets ;
  os << ",\"capacity_formula\":\"" << TS_CAPACITY_FORMULA << "\"" ;
  os << ",\"link_capacity_flits_per_cycle\":"
     << ts_cfg.link_capacity_flits_per_cycle ;
  os << ",\"channels\":[" ;
  bool first = true ;
  for ( size_t s = 0 ; s < ts_state.size() ; ++s ) {
    for ( size_t r = 0 ; r < ts_state[s].routers.size() ; ++r ) {
      TsRouter const & tr = ts_state[s].routers[r] ;
      for ( size_t o = 0 ; o < tr.outs.size() ; ++o ) {
        TsChannel const & ch = tr.outs[o] ;
        if ( !first ) os << "," ;
        first = false ;
        os << "{\"logical_channel_id\":" << ch.id ;
        os << ",\"flits_per_window\":[" ;
        for ( size_t w = 0 ; w < ch.wins.size() ; ++w ) {
          if ( w ) os << "," ;
          os << ch.wins[w] ;
        }
        // True per-window spans (global sampler: identical for every
        // channel, but carried per channel so a window array is
        // self-describing). Denominators use these, never the nominal
        // period — epoch edges and the trailing partial window have
        // shorter spans, and assuming full periods would understate
        // utilization silently.
        os << "],\"window_cycles\":[" ;
        for ( size_t w = 0 ; w < ch.spans.size() ; ++w ) {
          if ( w ) os << "," ;
          os << ch.spans[w] ;
        }
        // Stalls: no single stall counter exists — null, never zeros.
        // The measured wait/Tx split below supersedes it: queue_cycles
        // is the credit-stall measure, arb_wait_cycles the arb-stall
        // measure. Render the split, never zeros.
        os << "],\"stalls_per_window\":null" ;
        os << ",\"queue_cycles_per_window\":[" ;
        ts_emit_longs( os, ch.qwins ) ;
        os << "],\"arb_wait_cycles_per_window\":[" ;
        ts_emit_longs( os, ch.awins ) ;
        os << "],\"tx_flits_per_window\":[" ;
        ts_emit_longs( os, ch.txwins ) ;
        os << "],\"tx_busy_cycles_per_window\":[" ;
        ts_emit_longs( os, ch.txbwins ) ;
        os << "],\"occupancy_flit_cycles_per_window\":[" ;
        ts_emit_longs( os, ch.occwins ) ;
        os << "],\"queue_max_per_window\":[" ;
        ts_emit_longs( os, ch.qmaxwins ) ;
        os << "],\"arb_max_per_window\":[" ;
        ts_emit_longs( os, ch.amaxwins ) ;
        os << "],\"occupancy_max_per_window\":[" ;
        ts_emit_longs( os, ch.occmaxwins ) ;
        os << "]}" ;
      }
    }
  }
  os << "]" ;
  os << ",\"provenance\":{\"backend\":\"" ;
  ts_escape_json( os, ts_cfg.backend ) ;
  os << "\",\"version\":\"" ;
  ts_escape_json( os, ts_cfg.version ) ;
  os << "\",\"binary_hash\":\"" ;
  ts_escape_json( os, ts_cfg.binary_hash ) ;
  os << "\",\"input_hashes\":[" ;
  for ( size_t h = 0 ; h < ts_cfg.input_hashes.size() ; ++h ) {
    if ( h ) os << "," ;
    os << "\"" ;
    ts_escape_json( os, ts_cfg.input_hashes[h] ) ;
    os << "\"" ;
  }
  os << "]}" ;
  os << "}\n" ;
  return true ;
}

void DumpChannelActivity( Network * net, int subnet, std::ostream & os ) {
  vector<Router *> const & rs = net->GetRouters();

  os << "{\"schema\":\"veritx/channel-activity/v1\"";
  os << ",\"subnet\":" << subnet;
  os << ",\"router_count\":" << rs.size();

  long skipped = 0;
  os << ",\"routers\":[";
  bool first_router = true;
  for ( size_t r = 0 ; r < rs.size() ; ++r ) {
    if ( !rs[r] ) { ++skipped ; continue ; }
    IQRouter const * iq = dynamic_cast<IQRouter const *>( rs[r] ) ;
    if ( !iq ) { ++skipped ; continue ; }
    SwitchMonitor const * sw = iq->GetSwitchMonitor() ;
    BufferMonitor const * buf = iq->GetBufferMonitor() ;
    if ( !sw || !buf ) { ++skipped ; continue ; }

    int const inputs = sw->NumInputs() ;
    int const outputs = sw->NumOutputs() ;
    int const classes = sw->NumClasses() ;

    if ( !first_router ) os << "," ;
    first_router = false ;
    os << "{\"id\":" << rs[r]->GetID();
    os << ",\"num_inputs\":" << inputs;
    os << ",\"num_outputs\":" << outputs;
    os << ",\"num_classes\":" << classes;
    os << ",\"cycles_observed\":" << sw->Cycles();

    // Crossbar traversals summed over inputs, per output port per traffic
    // class: flits that left the router through this port. Injection and
    // ejection ports are reported raw like any other; the reader joins
    // (router, port) pairs to certified channels and ignores the rest.
    os << ",\"output_activity\":[";
    for ( int o = 0 ; o < outputs ; ++o ) {
      if ( o ) os << "," ;
      os << "{\"port\":" << o << ",\"flits_by_class\":[";
      for ( int c = 0 ; c < classes ; ++c ) {
        if ( c ) os << "," ;
        long total = 0 ;
        for ( int i = 0 ; i < inputs ; ++i ) total += sw->At( i, o, c ) ;
        os << total ;
      }
      os << "]}";
    }
    os << "]";

    // Buffer reads/writes per input port per traffic class.
    os << ",\"input_activity\":[";
    for ( int i = 0 ; i < inputs ; ++i ) {
      if ( i ) os << "," ;
      os << "{\"port\":" << i << ",\"reads_by_class\":[";
      for ( int c = 0 ; c < classes ; ++c ) {
        if ( c ) os << "," ;
        os << buf->ReadsAt( i, c ) ;
      }
      os << "],\"writes_by_class\":[";
      for ( int c = 0 ; c < classes ; ++c ) {
        if ( c ) os << "," ;
        os << buf->WritesAt( i, c ) ;
      }
      os << "]}";
    }
    os << "]";
    os << "}";
  }
  os << "]";
  os << ",\"skipped_non_iq_routers\":" << skipped;
  os << "}\n";
}

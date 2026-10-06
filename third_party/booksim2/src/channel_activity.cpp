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
};

struct TsRouter {
  std::vector<TsChannel> outs ;
};

bool ts_armed = false ;
long ts_period = 0 ;
long ts_windows = 0 ;
long ts_resets = 0 ;
long ts_last_poll = 0 ; // poll-clock: exactly one backward step per epoch
long ts_window_start = 0 ; // sim-time the current window opened
long ts_next_boundary = 0 ; // next per-epoch window boundary
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
      for ( size_t o = 0 ; o < tr.outs.size() ; ++o, ++k ) {
        long delta = cur[k] - tr.outs[o].base[0] ;
        if ( delta < 0 ) {
          cerr << "channel_timeseries: counter regression on subnet "
               << s << " router idx " << r << " port " << o
               << " (id " << tr.outs[o].id << "): baseline "
               << tr.outs[o].base[0] << " now " << cur[k] << endl ;
          ts_corrupt = true ; return false ;
        }
        if ( !fold ) {
          tr.outs[o].wins.push_back( delta ) ;
          tr.outs[o].spans.push_back( span ) ;
        }
        tr.outs[o].base[0] = cur[k] ;
      }
    }
  }
  if ( !fold ) ++ts_windows ;
  return true ;
}
} // namespace

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
      int const outputs = sw->NumOutputs() ;
      if ( outputs >= TS_MAX_PORTS ) return false ;
      long rid = (long)rs[r]->GetID() ;
      if ( rid < 0 || rid >= TS_MAX_ROUTER_ID ) return false ;
      TsRouter tr ;
      for ( int o = 0 ; o < outputs ; ++o ) {
        TsChannel ch ;
        ch.id = s * TS_SUBNET_STRIDE + rid * TS_ROUTER_STRIDE + o ;
        ch.base.push_back( 0 ) ; // baseline snapshot below
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
    for ( size_t r = 0 ; r < ts_state[s].routers.size() ; ++r )
      for ( size_t o = 0 ; o < ts_state[s].routers[r].outs.size() ; ++o, ++k )
        ts_state[s].routers[r].outs[o].base[0] = cur[k] ;
  ts_window_start = 0 ;
  ts_next_boundary = ts_period ;
  ts_last_poll = 0 ;
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
}

bool DumpChannelTimeseries( std::ostream & os, int sim_end_time ) {
  ts_armed = false ;
  if ( ts_corrupt ) {
    cerr << "channel_timeseries: counter regression detected "
         << "(a window delta went negative) — refusing a series "
         << "that cannot telescope exactly" << endl ;
    return false ;
  }
  // Trailing partial window: the run ends mid-window. Its true span is
  // recorded like any other, so denominators stay exact and nothing is
  // dropped (dropping would break telescoping) or padded (padding
  // would invent flits). A run that never advanced gains no window.
  if ( sim_end_time > ts_window_start &&
       !ts_capture_window( sim_end_time - ts_window_start, false ) )
    return false ;
  long nwin = ts_windows ;
  os << "{\"schema_version\":2" ;
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
        // Stalls: ABSENT per Phase-0 spike — null, never zeros.
        os << "],\"stalls_per_window\":null}" ;
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

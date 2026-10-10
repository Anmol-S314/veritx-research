// ----------------------------------------------------------------------
//
//  SrotaRouterD -- Plane D router with the VC-002 shared side buffer and
//  the TOPO-003 section 7.5 island wrapper. See srota_router_d.hpp.
//
// ----------------------------------------------------------------------

#include "srota_router_d.hpp"

#include <cassert>
#include <algorithm>
#include <sstream>
#include <iomanip>

#include "globals.hpp"
#include "flit.hpp"
#include "credit.hpp"
#include "../networks/srota.hpp"
#include "buffer.hpp"

SrotaRouterD::SrotaRouterD( Configuration const & phys_config,
                            Configuration const & credit_config,
                            Module * parent, string const & name, int id,
                            int inputs, int outputs,
                            SrotaRouterDParams const & p )
  : IQRouter( phys_config, parent, name, id, inputs, outputs ),
    _p( p ), _sb_occ( 0 ), _drain_offered( false ), _last_refill( 0 )
{
  // Every BufferState this router creates from here on -- one per output,
  // or per tap of a multidrop output -- models the neighbour's staging
  // window, not this router's physical buffer. Channels are attached
  // after construction, so setting it here covers all of them.
  _credit_config = &credit_config;
  _window = credit_config.GetInt( "vc_buf_size" );
  _ledger = phys_config.GetInt("srota_diagnostic_ledger") != 0;
  _ledger_seq = 0;
  _ledger_time = 0;

  _sb_id.assign( _inputs * _vcs, -1 );
  _deferred_fid.assign( _inputs * _vcs, -1 );
  _arrive_fid.assign( _inputs * _vcs, -1 );
  _eject_fid.assign( _inputs * _vcs, -1 );

  int const nq = (int)_p.isl_rate.size();
  _tokens.assign( nq, _p.isl_burst );   // buckets start full

  _st.sb_fill = _st.sb_drain = _st.sb_full_cyc = _st.sb_full_reject = 0;
  _st.sb_wm_cyc = _st.sb_occ_sum = _st.cycles = 0;
  _st.sb_peak = 0;
  _st.alloc_losses = 0;
  _st.defl_events = _st.defl_packets = _st.head_departs = 0;
  int const ncl = std::max( std::max( nq, _classes ), 4 );
  _st.isl_arrive.assign( ncl, 0 );
  _st.isl_grant.assign( ncl, 0 );
  _st.isl_defer.assign( ncl, 0 );
  _st.isl_defer_cyc.assign( ncl, 0 );
  _Trace("begin", _p.island ? 1 : 0, -1, -1, _p.isl_burst, _p.sb_depth);
  for (int q = 0; q < nq; ++q) _Trace("init", q, -1, -1, _p.isl_rate[q], _tokens[q]);
}

SrotaRouterD::~SrotaRouterD() {
  _Trace("end", -1, -1, -1, _held.size(), _sb_occ);
}

void SrotaRouterD::_Trace(char const * event, int q, int fid, int slot,
                         double before, double after, int dt) {
  if (!_ledger) return;
  std::ostringstream row;
  row << std::setprecision(17) << "SrotaLedger " << GetID() << " "
      << _ledger_seq++ << " " << _ledger_time << " " << event << " "
      << q << " " << fid << " " << slot << " " << before << " "
      << after << " " << dt << " " << _sb_occ;
  std::cout << row.str() << std::endl;
}

int SrotaRouterD::StorageFlits() const {
  return _inputs * _vcs * _window + _p.sb_depth;
}

int SrotaRouterD::_QosClass( Flit const * f ) const {
  return _p.isl_class_is_slack ? f->slack : f->cl;
}

void SrotaRouterD::_Refill() {
  int const now = GetSimTime();
  int const dt = now - _last_refill;
  _last_refill = now;
  if ( dt <= 0 ) return;
  for ( size_t q = 0; q < _tokens.size(); ++q ) {
    if ( _p.isl_rate[q] <= 0.0 ) continue;
    double const before = _tokens[q];
    _tokens[q] = std::min( _p.isl_burst, _tokens[q] + _p.isl_rate[q] * dt );
    _Trace("refill", q, -1, -1, before, _tokens[q], dt);
  }
}

void SrotaRouterD::_InternalStep( ) {
  _ledger_time = GetSimTime();
  _Trace("step_begin");
  _drain_offered = false;
  if ( _p.island ) _Refill();

  IQRouter::_InternalStep();

  // A token taken by a bid that then lost allocation was never spent:
  // the regulator admits flits, not bids.
  for ( size_t i = 0; i < _held.size(); ++i ) {
    int const q = _held[i].cl;
    double const before = _tokens[q];
    _tokens[q] = std::min( _p.isl_burst, _tokens[q] + 1.0 );
    _Trace("refund", q, _held[i].fid, _held[i].slot, before, _tokens[q]);
  }
  _held.clear();
  _Trace("step_end");

  ++_st.cycles;
  _st.sb_occ_sum += _sb_occ;
  if ( _sb_occ > _st.sb_peak ) _st.sb_peak = _sb_occ;
  if ( _sb_occ >= _p.sb_depth ) ++_st.sb_full_cyc;
  if ( WatermarkExceeded() ) ++_st.sb_wm_cyc;
}

bool SrotaRouterD::_SWAllocGate( int input, int vc, int output,
                                 Flit const * f ) {
  int const slot = input * _vcs + vc;
  bool const buffered = ( _sb_id[slot] == f->id );

  // srota_sidebuf_arb has one read port: a second buffered flit waits
  // for a later cycle whatever the allocator would have done with it.
  if ( buffered && _drain_offered ) return false;

  if ( _p.island && output < _p.local_ports ) {
    int const q = _QosClass( f );
    if ( q >= 0 && q < (int)_st.isl_arrive.size() &&
         _arrive_fid[slot] != f->id ) {
      _arrive_fid[slot] = f->id;
      ++_st.isl_arrive[q];
      _Trace("arrive", q, f->id, slot);
    }
    bool const regulated = ( q >= 0 && q < (int)_tokens.size() &&
                             _p.isl_rate[q] > 0.0 );
    if ( regulated ) {
      if ( _tokens[q] < 1.0 ) {
        // Defer: the class is over its rate. The flit keeps its staging
        // slot, so persistent deferral backs up into the fabric exactly
        // as ISL_STATUS "applying backpressure upstream" describes.
        _Trace("defer", q, f->id, slot, _tokens[q], _tokens[q]);
        ++_st.isl_defer_cyc[q];
        if ( _deferred_fid[slot] != f->id ) {
          _deferred_fid[slot] = f->id;
          ++_st.isl_defer[q];
        }
        return false;
      }
      double const before = _tokens[q];
      _tokens[q] -= 1.0;
      _Trace("reserve", q, f->id, slot, before, _tokens[q]);
      TokenHold h = { slot, q, f->id };
      _held.push_back( h );
    }
    _eject_fid[slot] = f->id;
  }

  if ( buffered ) _drain_offered = true;
  return true;
}

void SrotaRouterD::_SWAllocLost( int input, int vc, Flit * f ) {
  ++_st.alloc_losses;

  int const slot = input * _vcs + vc;
  _Trace("allocation_loss", -1, f->id, slot);
  if ( _sb_id[slot] == f->id ) return;   // already buffered: stays put
  assert( _sb_id[slot] < 0 );             // only the front flit can be

  if ( _sb_occ >= _p.sb_depth ) {
    // FULL: not captured, staging slot stays occupied, credit withheld.
    ++_st.sb_full_reject;
    _Trace("full", -1, f->id, slot);
    return;
  }

  _sb_id[slot] = f->id;
  ++_sb_occ;
  ++_st.sb_fill;
  _Trace("capture", -1, f->id, slot);
  _Trace("credit", -1, f->id, slot);

  // The staging slot is free now, so its credit goes upstream this
  // cycle rather than when the flit finally leaves.
  if ( _out_queue_credits.count( input ) == 0 ) {
    _out_queue_credits.insert( make_pair( input, Credit::New() ) );
  }
  _out_queue_credits.find( input )->second->vc.insert( vc );
}

bool SrotaRouterD::_CreditOnDepart( int input, int vc, Flit const * f ) {
  int const slot = input * _vcs + vc;

  // Deflection accounting. The allocator has already bound this VC to an
  // output port; route compute says which port was the productive one.
  // Counted on the head flit only -- the rest of the packet follows the
  // head's binding by construction, so counting them too would just
  // multiply every number by packet_size.
  if ( f->head && SrotaDeflectEnabled() ) {
    ++_st.head_departs;
    int const got  = _buf[input]->GetOutputPort( vc );
    int const prod = SrotaProductivePort( f, GetID() );
    if ( prod >= 0 && got >= 0 && got != prod ) {
      ++_st.defl_events;
      if ( f->defl == 0 ) ++_st.defl_packets;
      ++f->defl;            // the budget srota_deflect_max bounds
    }
  }

  // Admitted by the regulator: the token is spent, not refunded.
  for ( size_t i = 0; i < _held.size(); ++i ) {
    if ( _held[i].fid == f->id ) {
      _Trace("spend", _held[i].cl, f->id, slot, _tokens[_held[i].cl], _tokens[_held[i].cl]);
      _held.erase( _held.begin() + i );
      break;
    }
  }

  // Only head flits carry a destination, so whether this departure is
  // toward the attach queue comes from the bid the gate saw.
  if ( _p.island && _eject_fid[slot] == f->id ) {
    _eject_fid[slot] = -1;
    int const q = _QosClass( f );
    if ( q >= 0 && q < (int)_st.isl_grant.size() ) {
      ++_st.isl_grant[q];
      _Trace("grant", q, f->id, slot);
    }
  }

  if ( _sb_id[slot] == f->id ) {
    _sb_id[slot] = -1;
    --_sb_occ;
    ++_st.sb_drain;
    _Trace("drain", -1, f->id, slot);
    _Trace("depart_buffered", -1, f->id, slot);
    return false;   // credit already returned at capture
  }
  _Trace("credit", -1, f->id, slot);
  _Trace("depart", -1, f->id, slot);
  return true;
}

// ----------------------------------------------------------------------
//  Srota three-level arbiter. See srota_arb.hpp for the spec mapping and
//  the modeling departures.
// ----------------------------------------------------------------------

#include "booksim.hpp"

#include <cassert>
#include <climits>
#include <iostream>

#include "srota_arb.hpp"
#include "globals.hpp"

SrotaArbAllocator::SrotaArbAllocator( Module *parent, const string& name,
                                      int inputs, int outputs, int iters,
                                      Configuration const * const config )
  : SparseAllocator( parent, name, inputs, outputs ),
    _iters( iters )
{
  // Defaults keep all three levels live, which is the shipping arbiter.
  // Turning one off is how you find out which level did the work -- the
  // ablation M3 needs to be more than a single number.
  _en_golden      = true;
  _en_slack       = true;
  _en_stc         = true;
  _golden_epoch   = 64;
  _golden_windows = 16;

  if ( config ) {
    _en_golden      = ( config->GetInt("srota_arb_l0_golden") != 0 );
    _en_slack       = ( config->GetInt("srota_arb_l1_slack")  != 0 );
    _en_stc         = ( config->GetInt("srota_arb_l2_stc")    != 0 );
    _golden_epoch   = config->GetInt("srota_arb_golden_epoch");
    _golden_windows = config->GetInt("srota_arb_golden_windows");
  }

  if ( _golden_epoch < 1 ) {
    Error("srota_arb_golden_epoch must be >= 1");
  }
  if ( _golden_windows < 1 ) {
    Error("srota_arb_golden_windows must be >= 1");
  }

  _gptrs.resize(_outputs, 0);
  _aptrs.resize(_inputs, 0);
}

int SrotaArbAllocator::_GoldenWindow() const
{
  // Bounded-delay floor (F3): the window advances on a fixed schedule, so
  // every golden_id gets its turn within _golden_epoch * _golden_windows
  // cycles regardless of load.
  return ( GetSimTime() / _golden_epoch ) % _golden_windows;
}

int SrotaArbAllocator::_AllocateGrant(
    vector<pair<int, Allocator::sRequest> > const & cands,
    int rr_offset, int modulus ) const
{
  if ( cands.empty() ) {
    return -1;
  }

  // ---- Level 0: golden rotation (F3) --------------------------------
  //
  //   m0 = |(elig & golden_match) ? (elig & golden_match) : elig
  //
  // The conditional is the whole point. Intersecting unconditionally
  // would empty the candidate set in every cycle with no golden-window
  // request, and the allocator would grant nobody while requests were
  // pending -- idling on a schedule rather than on demand.
  vector<int> m0;
  if ( _en_golden ) {
    for ( size_t i = 0; i < cands.size(); ++i ) {
      if ( ( cands[i].second.golden_id % _golden_windows ) == _GoldenWindow() ) {
        m0.push_back((int)i);
      }
    }
  }
  if ( m0.empty() ) {                       // fallback, or L0 disabled
    for ( size_t i = 0; i < cands.size(); ++i ) {
      m0.push_back((int)i);
    }
  }

  // ---- Level 1: slack class -----------------------------------------
  //
  //   best_slack = min_over(m0, req_slack)
  //   m1         = m0 & slack_eq(req_slack, best_slack)
  //
  // 0 is the critical class (PKT-008 section 8.2), so minimum wins.
  vector<int> m1;
  if ( _en_slack ) {
    int best = INT_MAX;
    for ( size_t i = 0; i < m0.size(); ++i ) {
      int const s = cands[m0[i]].second.slack;
      if ( s < best ) best = s;
    }
    for ( size_t i = 0; i < m0.size(); ++i ) {
      if ( cands[m0[i]].second.slack == best ) m1.push_back(m0[i]);
    }
  } else {
    m1 = m0;
  }
  assert( !m1.empty() );

  // ---- Level 2: STC batch epoch (F4) ---------------------------------
  //
  //   best_batch = min_over(m1, req_batch)
  //   m2         = m1 & batch_eq(req_batch, best_batch)
  //
  // The starvation bound: an older batch cannot be held behind a newer
  // one indefinitely, because the older batch's epoch tag is smaller and
  // this level selects the minimum.
  vector<int> m2;
  if ( _en_stc ) {
    int best = INT_MAX;
    for ( size_t i = 0; i < m1.size(); ++i ) {
      int const b = cands[m1[i]].second.batch;
      if ( b < best ) best = b;
    }
    for ( size_t i = 0; i < m1.size(); ++i ) {
      if ( cands[m1[i]].second.batch == best ) m2.push_back(m1[i]);
    }
  } else {
    m2 = m1;
  }
  assert( !m2.empty() );

  // ---- Round-robin tiebreak over the survivors -----------------------
  //
  //   gnt_oh = rr_select(m2, rr_ptr)
  //
  // Progress guarantee. Without it the cascade could hand the same
  // winner every cycle when the fields tie.
  int best_port = -1;
  int best_key = INT_MAX;
  for ( size_t i = 0; i < m2.size(); ++i ) {
    int const port = cands[m2[i]].first;
    int const key = ( port - rr_offset + modulus ) % modulus;
    if ( key < best_key ) {
      best_key = key;
      best_port = port;
    }
  }
  assert( best_port >= 0 );   // a_golden_no_deadgrant: (|elig) |-> gnt_vld
  return best_port;
}

void SrotaArbAllocator::Allocate( )
{
  for ( int iter = 0; iter < _iters; ++iter ) {

    // ---- Grant phase: each free output picks among free inputs -------
    vector<int> grants(_outputs, -1);

    for ( int output = 0; output < _outputs; ++output ) {
      if ( _out_req[output].empty() || ( _outmatch[output] != -1 ) ) {
        continue;
      }
      vector<pair<int, sRequest> > cands;
      for ( map<int, sRequest>::const_iterator p = _out_req[output].begin();
            p != _out_req[output].end(); ++p ) {
        int const input = p->second.port;
        if ( _inmatch[input] == -1 ) {
          cands.push_back(make_pair(input, p->second));
        }
      }
      grants[output] = _AllocateGrant(cands, _gptrs[output], _inputs);
    }

    // ---- Accept phase: each input picks among the grants it got ------
    //
    // The cascade runs here too. An input holding a critical-class flit
    // and a background flit that were both granted must accept the
    // critical one; leaving this phase round-robin would let Level 1's
    // decision be undone one step later.
    for ( int input = 0; input < _inputs; ++input ) {
      if ( _in_req[input].empty() || ( _inmatch[input] != -1 ) ) {
        continue;
      }
      vector<pair<int, sRequest> > cands;
      for ( map<int, sRequest>::const_iterator p = _in_req[input].begin();
            p != _in_req[input].end(); ++p ) {
        int const output = p->second.port;
        if ( grants[output] == input ) {
          cands.push_back(make_pair(output, p->second));
        }
      }
      int const output = _AllocateGrant(cands, _aptrs[input], _outputs);
      if ( output < 0 ) {
        continue;
      }
      _inmatch[input]   = output;
      _outmatch[output] = input;

      // Pointer update on the first iteration only, matching iSLIP: later
      // iterations exist to fill in the matching, and letting them move
      // the pointers breaks the fairness argument.
      if ( iter == 0 ) {
        _gptrs[output] = ( input + 1 ) % _inputs;
        _aptrs[input]  = ( output + 1 ) % _outputs;
      }
    }
  }
}

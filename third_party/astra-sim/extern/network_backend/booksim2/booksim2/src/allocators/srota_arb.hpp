// ----------------------------------------------------------------------
//
//  Srota three-level arbiter -- SSM-UARCH-ROUTE-001 rev 0.3 section 11.2,
//  as a BookSim switch allocator.
//
//  This is ingredient (2) of measurable claim M3 (section 16.4): "the
//  three-level arbiter as an allocator variant replacing the default
//  islip/RR allocator". Ingredient (1) is the slack tag in the packet
//  format, which is Flit::slack / batch / golden_id; ingredient (3) is a
//  baseline run on identical traffic, which is what `sw_allocator = islip`
//  on the same trace gives.
//
//  THE CASCADE (section 11.2, verbatim in the RTL's own terms):
//
//      elig = req_vec & credit_avail & ~out_busy_mask
//      m0   = |(elig & golden_match) ? (elig & golden_match) : elig
//      m1   = m0 & (slack == min_over(m0, slack))
//      m2   = m1 & (batch == min_over(m1, batch))
//      gnt  = rr_select(m2, rr_ptr)
//
//  Each level narrows, never widens, the candidate set, and a round-robin
//  tiebreak over the survivors guarantees progress.
//
//  The m0 fallback is a correctness requirement rather than an
//  optimisation, and section 11.2 says so explicitly: applied
//  unconditionally the golden mask would grant nobody in a cycle with no
//  golden-window request, and "the fabric would idle on a schedule rather
//  than on demand." The corresponding RTL assertion is
//  a_golden_no_deadgrant: (|elig) |-> gnt_vld. _AllocateGrant() below
//  preserves that property and SrotaArbAllocator asserts it.
//
//  HOW THE THREE LEVELS DEGENERATE. Every level masks on equality against
//  a minimum, or against the rotating golden window. A field that is
//  uniform across all contending requests therefore never discriminates
//  and the level passes its whole candidate set through. Traffic with no
//  arbitration fields set (every stock BookSim traffic pattern, and any
//  trace that omits the columns) arrives with all three at zero, and this
//  allocator behaves exactly as round-robin. That is a useful property to
//  test, not a case to guard against.
//
//  MODELING DEPARTURES -- read before quoting M3 against the RTL:
//
//  1. ONE FLAT ALLOCATOR, NOT TWO COUPLED STAGES. TOPO-003 section 7.3
//     builds the router from two <=6-port allocators, srota_arb_mesh and
//     srota_arb_express, and rev 0.3 couples them: the stage that resolves
//     first publishes out_busy_mask, the second ANDs ~out_busy_mask into
//     its request vector, and precedence rotates on the golden schedule
//     (recorded as RT-R9). BookSim's IQRouter drives a single flat
//     allocator over all ports, so out_busy_mask is identically zero here
//     and the two-stage structure is absent. The three LEVELS are modeled
//     exactly; the two STAGES are not. Closing this needs a custom Router
//     subclass, which is the same vehicle the side buffer needs.
//
//  2. CREDIT IS CHECKED BY THE ROUTER, NOT HERE. `credit_avail` in the
//     expression above is already applied upstream: IQRouter only issues a
//     switch request for a VC whose target has buffer space. So `elig` is
//     the request set this allocator is handed, and the credit term is
//     satisfied by construction rather than re-evaluated.
//
//  3. THE GRANT IS A MATCHING, NOT A SINGLE VECTOR. Section 11.2 shows one
//     output's arbitration. A switch allocator has to produce a matching
//     over all ports, so the cascade runs in both phases of an
//     iSLIP-shaped grant/accept loop -- output-side to pick among
//     contending inputs, input-side to pick among the grants an input
//     received. Running it in only one phase would leave the other phase
//     round-robin and understate the arbiter.
//
// ----------------------------------------------------------------------

#ifndef _SROTA_ARB_HPP_
#define _SROTA_ARB_HPP_

#include <vector>

#include "allocator.hpp"

class SrotaArbAllocator : public SparseAllocator {

  int _iters;          // grant/accept iterations, as iSLIP's alloc_iters

  bool _en_golden;     // srota_arb_l0_golden
  bool _en_slack;      // srota_arb_l1_slack
  bool _en_stc;        // srota_arb_l2_stc

  int _golden_epoch;   // cycles per golden window (ROUTE_GOLDEN_EPOCH)
  int _golden_windows; // number of windows the rotation cycles through

  std::vector<int> _gptrs;  // round-robin pointer per output
  std::vector<int> _aptrs;  // round-robin pointer per input

  // Which golden window is open right now. Section 12.1 keeps the
  // rotation counter in the parent allocator (sequential), while the mask
  // generators themselves are purely combinational -- so it lives here.
  int _GoldenWindow() const;

  // The L0/L1/L2 cascade over one candidate set, followed by the
  // round-robin tiebreak. `cands` are (port, request) pairs; returns the
  // chosen port, or -1 if the set was empty. Guarantees a selection
  // whenever `cands` is non-empty, which is a_golden_no_deadgrant.
  int _AllocateGrant(std::vector<std::pair<int, sRequest> > const & cands,
                     int rr_offset, int modulus) const;

public:
  SrotaArbAllocator( Module *parent, const string& name,
                     int inputs, int outputs, int iters,
                     Configuration const * const config );

  virtual void Allocate( );
};

#endif

// $Id$

/*
 Copyright (c) 2007-2015, Trustees of The Leland Stanford Junior University
 All rights reserved.

 Redistribution and use in source and binary forms, with or without
 modification, are permitted provided that the following conditions are met:

 Redistributions of source code must retain the above copyright notice, this 
 list of conditions and the following disclaimer.
 Redistributions in binary form must reproduce the above copyright notice, this
 list of conditions and the following disclaimer in the documentation and/or
 other materials provided with the distribution.

 THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
 ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
 WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE 
 DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
 ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
 (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
 LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
 ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
 SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
*/

#ifndef _OUTPUTSET_HPP_
#define _OUTPUTSET_HPP_

#include <set>

class OutputSet {


public:
  struct sSetElement {
    int vc_start;
    int vc_end;
    int pri;
    int output_port;
    // MECS: tap index on a multidrop output port, or -1 when this port is
    // an ordinary single-tap channel. Carried per element rather than on
    // the flit because an adaptive route set (Srota deflection) offers
    // several ports at once, each with its own tap -- Flit::drop can only
    // hold the one that was finally chosen.
    int drop;
  };

  void Clear( );
  void Add( int output_port, int vc, int pri = 0, int drop = -1 );
  void AddRange( int output_port, int vc_start, int vc_end, int pri = 0,
                 int drop = -1 );

  bool OutputEmpty( int output_port ) const;
  int NumVCs( int output_port ) const;
  
  const set<sSetElement> & GetSet() const;

  int  GetVC( int output_port,  int vc_index, int *pri = 0 ) const;
  bool GetPortVC( int *out_port, int *out_vc ) const;

  // Tap index this route set recorded for `output_port`, or `dflt` when
  // the port is absent or carries no tap.
  int  GetDrop( int output_port, int dflt ) const;
private:
  set<sSetElement> _outputs;
};

// Higher priorities first -- but this is the comparator of a std::set, so
// it must be a strict weak ordering over the WHOLE element, not just the
// priority. Ordering on `pri` alone makes any two options of equal
// priority compare equivalent, and the set silently keeps only the first:
// a route set could never offer two ports at the same priority. Srota's
// deflection route sets do exactly that, so the tie-break below is a
// correctness requirement, not a tidiness one. Options that differ only
// in priority still order by priority, so every existing routing
// function is unaffected.
inline bool operator<(const OutputSet::sSetElement & se1, 
	       const OutputSet::sSetElement & se2) {
  if(se1.pri != se2.pri) return se1.pri > se2.pri;
  if(se1.output_port != se2.output_port) return se1.output_port < se2.output_port;
  if(se1.vc_start != se2.vc_start) return se1.vc_start < se2.vc_start;
  if(se1.vc_end != se2.vc_end) return se1.vc_end < se2.vc_end;
  return se1.drop < se2.drop;
}

#endif



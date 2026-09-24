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

#ifndef _NETWORK_HPP_
#define _NETWORK_HPP_

#include <vector>
#include <deque>

#include "module.hpp"
#include "flit.hpp"
#include "credit.hpp"
#include "router.hpp"
#include "module.hpp"
#include "timed_module.hpp"
#include "flitchannel.hpp"
#include "channel.hpp"
#include "config_utils.hpp"
#include "globals.hpp"
#include "multidropchannel.hpp"
#include "routefunc.hpp"

typedef Channel<Credit> CreditChannel;


class Network : public TimedModule {
protected:

  int _size;
  int _nodes;
  int _channels;
  int _classes;

  vector<Router *> _routers;

  vector<FlitChannel *> _inject;
  vector<CreditChannel *> _inject_cred;

  vector<FlitChannel *> _eject;
  vector<CreditChannel *> _eject_cred;

  vector<FlitChannel *> _chan;
  vector<CreditChannel *> _chan_cred;

  // MECS: shared/tapped channels a topology's _BuildNet() may allocate,
  // in addition to (not instead of) the ordinary point-to-point _chan
  // above. Unlike _chan, these aren't index-locked by _Alloc() -- a
  // topology pushes onto these itself, sizing them however its own
  // channel-grouping scheme requires, and must also push each one onto
  // _timed_modules so ReadInputs()/Evaluate()/WriteOutputs() reach it.
  vector<MultiDropChannel *> _md_chan;
  vector<MultiDropCreditChannel *> _md_chan_cred;

  deque<TimedModule *> _timed_modules;

  virtual void _ComputeSize( const Configuration &config ) = 0;
  virtual void _BuildNet( const Configuration &config ) = 0;

  void _Alloc( );

public:
  Network( const Configuration &config, const string & name );
  virtual ~Network( );

  static Network *New( const Configuration &config, const string & name );

  virtual void WriteFlit( Flit *f, int source );
  virtual Flit *ReadFlit( int dest );

  virtual void    WriteCredit( Credit *c, int dest );
  virtual Credit *ReadCredit( int source );

  inline int NumNodes( ) const {return _nodes;}

  virtual void InsertRandomFaults( const Configuration &config );
  void OutChannelFault( int r, int c, bool fault = true );

  virtual double Capacity( ) const;

  virtual void ReadInputs( );
  virtual void Evaluate( );
  virtual void WriteOutputs( );

  void Display( ostream & os = cout ) const;
  void DumpChannelMap( ostream & os = cout, string const & prefix = "" ) const;
  void DumpNodeMap( ostream & os = cout, string const & prefix = "" ) const;

  int NumChannels() const {return _channels;}
  const vector<FlitChannel *> & GetInject() {return _inject;}
  FlitChannel * GetInject(int index) {return _inject[index];}
  const vector<CreditChannel *> & GetInjectCred() {return _inject_cred;}
  CreditChannel * GetInjectCred(int index) {return _inject_cred[index];}
  const vector<FlitChannel *> & GetEject(){return _eject;}
  FlitChannel * GetEject(int index) {return _eject[index];}
  const vector<CreditChannel *> & GetEjectCred(){return _eject_cred;}
  CreditChannel * GetEjectCred(int index) {return _eject_cred[index];}
  const vector<FlitChannel *> & GetChannels(){return _chan;}
  const vector<CreditChannel *> & GetChannelsCred(){return _chan_cred;}
  const vector<Router *> & GetRouters(){return _routers;}
  Router * GetRouter(int index) {return _routers[index];}
  int NumRouters() const {return _size;}

  // VeritX (P1B-Q2): deterministic first-hop realization dump.
  // Queries the ACTIVE routing function for every (router, destination
  // node) pair and writes "src_router r dst_node d next_router m port p";
  // next_router == r means the destination is local to router r. Refuses
  // (returns false with a reason) when the active function does not yield
  // exactly one output port, so an adaptive/random realization can never
  // masquerade as a deterministic table. Zero simulation-state effect:
  // the synthetic flit is pooled and freed, no packet is injected, no
  // credit moves.
  bool DumpRoutingRealization( const Configuration & config,
			       const string & path, string & why );
  // VeritX (P1B-Q2): one (router, dest) routing query. Requires exactly
  // one output port and identical results across two independent queries
  // (an RNG/state-dependent function is refused, never certified as a
  // deterministic table). Returns false with a reason.
  bool _QueryDeterministicPort( tRoutingFunction rf,
				const string & rf_name, Router * router,
				int dest, int & port, string & why );
};

#endif 


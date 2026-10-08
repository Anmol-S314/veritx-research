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

/*network.cpp
 *
 *This class is the basis of the entire network, it contains, all the routers
 *channels in the network, and is extended by all the network topologies
 *
 */

#include <cassert>
#include <fstream>
#include <sstream>

#include "booksim.hpp"
#include "network.hpp"
#include "routefunc.hpp"

#include "kncube.hpp"
#include "fly.hpp"
#include "cmesh.hpp"
#include "flatfly_onchip.hpp"
#include "qtree.hpp"
#include "tree4.hpp"
#include "fattree.hpp"
#include "anynet.hpp"
#include "dragonfly.hpp"
#include "gec.hpp"
#include "srota.hpp"


Network::Network( const Configuration &config, const string & name ) :
  TimedModule( 0, name )
{
  _size     = -1; 
  _nodes    = -1; 
  _channels = -1;
  _classes  = config.GetInt("classes");
}

Network::~Network( )
{
  for ( int r = 0; r < _size; ++r ) {
    if ( _routers[r] ) delete _routers[r];
  }
  for ( int s = 0; s < _nodes; ++s ) {
    if ( _inject[s] ) delete _inject[s];
    if ( _inject_cred[s] ) delete _inject_cred[s];
  }
  for ( int d = 0; d < _nodes; ++d ) {
    if ( _eject[d] ) delete _eject[d];
    if ( _eject_cred[d] ) delete _eject_cred[d];
  }
  for ( int c = 0; c < _channels; ++c ) {
    if ( _chan[c] ) delete _chan[c];
    if ( _chan_cred[c] ) delete _chan_cred[c];
  }
  for ( size_t c = 0; c < _md_chan.size(); ++c ) {
    delete _md_chan[c];
  }
  for ( size_t c = 0; c < _md_chan_cred.size(); ++c ) {
    delete _md_chan_cred[c];
  }
}

Network * Network::New(const Configuration & config, const string & name)
{
  const string topo = config.GetStr( "topology" );
  Network * n = NULL;
  if ( topo == "torus" ) {
    KNCube::RegisterRoutingFunctions() ;
    n = new KNCube( config, name, false );
  } else if ( topo == "mesh" ) {
    KNCube::RegisterRoutingFunctions() ;
    n = new KNCube( config, name, true );
  } else if ( topo == "cmesh" ) {
    CMesh::RegisterRoutingFunctions() ;
    n = new CMesh( config, name );
  } else if ( topo == "fly" ) {
    KNFly::RegisterRoutingFunctions() ;
    n = new KNFly( config, name );
  } else if ( topo == "qtree" ) {
    QTree::RegisterRoutingFunctions() ;
    n = new QTree( config, name );
  } else if ( topo == "tree4" ) {
    Tree4::RegisterRoutingFunctions() ;
    n = new Tree4( config, name );
  } else if ( topo == "fattree" ) {
    FatTree::RegisterRoutingFunctions() ;
    n = new FatTree( config, name );
  } else if ( topo == "flatfly" ) {
    FlatFlyOnChip::RegisterRoutingFunctions() ;
    n = new FlatFlyOnChip( config, name );
  } else if ( topo == "anynet"){
    AnyNet::RegisterRoutingFunctions() ;
    n = new AnyNet(config, name);
  } else if ( topo == "dragonflynew"){
    DragonFlyNew::RegisterRoutingFunctions() ;
    n = new DragonFlyNew(config, name);
  } else if ( topo == "gec" ){
    GEC::RegisterRoutingFunctions() ;
    n = new GEC( config, name );
  } else if ( topo == "srota" ){
    SrotaNoC::RegisterRoutingFunctions() ;
    n = new SrotaNoC( config, name );
  } else {
    cerr << "Unknown topology: " << topo << endl;
  }
  
  /*legacy code that insert random faults in the networks
   *not sure how to use this
   */
  if ( n && ( config.GetInt( "link_failures" ) > 0 ) ) {
    n->InsertRandomFaults( config );
  }

  /* VeritX (P1B-Q2): when a routing realization dump is requested, query
   * the active routing function and write the executed first-hop table.
   * AnyNet keeps its own historical dump inside buildRoutingTable(), so
   * it is skipped here byte-for-byte.
   */
  if ( n && n->DumpsRoutingRealization() && ( topo != "anynet" ) && ( !config.GetStr( "routing_dump_file" ).empty() ) ) {
    string why;
    if ( !n->DumpRoutingRealization( config, config.GetStr( "routing_dump_file" ), why ) ) {
      cerr << "VeritX: routing realization dump refused: " << why << endl;
      exit( -1 );
    }
  }
  return n;
}


bool Network::DumpRoutingRealization( const Configuration & config,
				      const string & path, string & why )
{
  if ( path.empty() ) {
    return true;
  }
  const string rf_name = config.GetStr( "routing_function" ) + "_" +
    config.GetStr( "topology" );
  map<string, tRoutingFunction>::const_iterator it =
    gRoutingFunctionMap.find( rf_name );
  /* VeritX: most topologies register "<routing_function>_<topology>" (e.g.
   * "dim_order_mesh"). GEC registers its routing functions under their
   * BARE names ("dor_gec", "hybrid_gec"), so the composed lookup misses
   * ("dor_gec_gec"). Fall back to the bare name here rather than register
   * a doubled alias in the network: the fallback only fires when no
   * composed entry exists, so every existing lookup is unchanged. */
  if ( it == gRoutingFunctionMap.end() ) {
    it = gRoutingFunctionMap.find( config.GetStr( "routing_function" ) );
  }
  if ( it == gRoutingFunctionMap.end() ) {
    why = "routing function '" + rf_name + "' is not registered";
    return false;
  }
  tRoutingFunction rf = it->second;

  ofstream dump( path.c_str() );
  if ( !dump.is_open() ) {
    why = "cannot open routing dump file '" + path + "'";
    return false;
  }
  dump << "# VeritX routing realization dump (executed first-hop realization)\n";
  dump << "# topology " << config.GetStr( "topology" )
       << " routing_function " << config.GetStr( "routing_function" ) << "\n";
  /* VeritX: query "as if injected at this router". The injection-channel
   * index is topology-dependent: the k-ary n-cube family documents
   * in_channel == 2*gN as injected (romm/min_adapt/valiant/xy_yx guards;
   * the dor_next_torus escape trick), and mesh/anynet/flatfly/fly/
   * dragonfly functions ignore in_channel or are port-deterministic in
   * it, so 2*gN is faithful there. Fattree/qtree/tree4/gec index injection
   * differently (their nca-style asserts reject 2*gN), and their dumps
   * are uncertified, so they keep the legacy -1 query bit-identically. */
  int query_port = -1;
  const string dump_topo = config.GetStr( "topology" );
  if ( ( dump_topo == "mesh" ) || ( dump_topo == "torus" ) ||
       ( dump_topo == "cmesh" ) || ( dump_topo == "fly" ) ||
       ( dump_topo == "flatfly" ) ||
       ( dump_topo == "dragonflynew" ) || ( dump_topo == "anynet" ) ) {
    query_port = 2*gN;
  }
  /* VeritX (MECS dump): a multidrop hop needs four facts, and next_router
   * is one of them. FlitChannel::GetSink() tracks only the most recently
   * registered tap of a shared channel, so it names the wrong downstream
   * router for every tap but the last. For the multidrop families the
   * landing router therefore comes from the CHANNEL THE TAP RESOLVES TO,
   * and the tap plus the resolved VC range are emitted alongside it.
   *
   * Every other topology keeps the exact legacy columns -- their recorded
   * dump identities and qualification records depend on those bytes. */
  const bool multidrop = ( dump_topo == "gec" ) || ( dump_topo == "srota" );
  for ( int r = 0; r < _size; ++r ) {
    Router * router = _routers[r];
    for ( int d = 0; d < _nodes; ++d ) {
      int port = -1;
      int drop = -1;
      int vc_start = -1;
      int vc_end = -1;
      if ( !_QueryDeterministicPort( rf, rf_name, router, d, query_port,
			     port, drop, vc_start, vc_end, why ) ) {
	dump.close();
	return false;
      }
      int next = r;
      if ( multidrop ) {
	if ( !_ResolveTapSink( r, port, drop, next, why ) ) {
	  dump.close();
	  return false;
	}
      } else {
	const FlitChannel * ch = router->GetOutputChannel( port );
	next = ( ( ch != NULL ) && ( ch->GetSink() != NULL ) )
	  ? ch->GetSink()->GetID() : r;
      }
      dump << "src_router " << r << " dst_node " << d
	   << " next_router " << next << " port " << port;
      if ( multidrop ) {
	dump << " drop " << drop
	     << " vc_start " << vc_start
	     << " vc_end " << vc_end;
      }
      dump << "\n";
    }
  }
  dump.close();
  return true;
}


bool Network::_ResolveTapSink( int src_router, int port, int drop,
			       int & next, string & why )
{
  const FlitChannel * ch = _routers[src_router]->GetOutputChannel( port );
  if ( ch == NULL ) {
    ostringstream why_ss;
    why_ss << "router " << src_router << " port " << port
	   << " has no output channel";
    why = why_ss.str();
    return false;
  }
  const MultiDropChannel * mdc = NULL;
  for ( size_t i = 0; i < _md_chan.size(); ++i ) {
    if ( (const FlitChannel *)_md_chan[i] == ch ) {
      mdc = _md_chan[i];
      break;
    }
  }
  if ( mdc == NULL ) {
    /* Ordinary single-tap port. A tap here would name a resource that does
     * not exist, so it is refused rather than ignored. */
    if ( drop >= 0 ) {
      ostringstream why_ss;
      why_ss << "router " << src_router << " port " << port
	     << " is an ordinary single-tap channel but the routing "
	     << "function reported tap " << drop;
      why = why_ss.str();
      return false;
    }
    const Router * sink = ch->GetSink();
    next = ( sink != NULL ) ? sink->GetID() : src_router;
    return true;
  }
  if ( drop < 0 ) {
    ostringstream why_ss;
    why_ss << "router " << src_router << " port " << port
	   << " is a multidrop channel but the routing function named no "
	   << "tap; without a tap the landing router is undefined";
    why = why_ss.str();
    return false;
  }
  if ( drop >= mdc->NumSinks() ) {
    ostringstream why_ss;
    why_ss << "router " << src_router << " port " << port << " named tap "
	   << drop << " but the channel has only " << mdc->NumSinks()
	   << " sink(s)";
    why = why_ss.str();
    return false;
  }
  next = mdc->SinkRouterID( drop );
  return true;
}

bool Network::_QueryDeterministicPort( tRoutingFunction rf,
				       const string & rf_name,
				       Router * router, int dest,
			       int query_port, int & port,
			       int & drop, int & vc_start, int & vc_end,
			       string & why )
{
  int ports[2] = { -1, -1 };
  int drops[2] = { -1, -1 };
  int vc_starts[2] = { -1, -1 };
  int vc_ends[2] = { -1, -1 };
  for ( int pass = 0; pass < 2; ++pass ) {
    Flit * flit = Flit::New();
    flit->dest = dest;
    flit->type = Flit::ANY_TYPE;
    flit->head = true;
    flit->vc = 0;   /* an in-flight flit, never an injection */
    OutputSet outputs;
    rf( router, flit, query_port, &outputs, false );
    const set<OutputSet::sSetElement> & got = outputs.GetSet();
    if ( got.size() != 1 ) {
      ostringstream why_ss;
      why_ss << "routing function '" << rf_name << "' yields "
	     << got.size() << " output ports for (router,dst)=("
	     << router->GetID() << "," << dest << "); a deterministic "
	     << "first-hop table cannot be certified from an "
	     << "adaptive/ambiguous realization";
      why = why_ss.str();
      flit->Free();
      return false;
    }
    const OutputSet::sSetElement & elem = *got.begin();
    ports[pass] = elem.output_port;
    /* VeritX (MECS dump): prefer the flit's tap (dor_gec's convention) and
     * fall back to the output set's (srota's). -1 means "not a multidrop
     * port", which is the ordinary single-tap case. */
    drops[pass] = ( flit->drop >= 0 ) ? flit->drop : elem.drop;
    vc_starts[pass] = elem.vc_start;
    vc_ends[pass] = elem.vc_end;
    if ( ( ports[pass] < 0 ) || ( ports[pass] >= router->NumOutputs() ) ) {
      ostringstream why_ss;
      why_ss << "routing function '" << rf_name << "' returned port "
	     << ports[pass] << " outside [0," << router->NumOutputs()
	     << ") for (router,dst)=(" << router->GetID() << "," << dest
	     << ")";
      why = why_ss.str();
      flit->Free();
      return false;
    }
    flit->Free();
  }
  if ( ports[0] != ports[1] ) {
    ostringstream why_ss;
    why_ss << "routing function '" << rf_name << "' returned different "
	   << "ports (" << ports[0] << " vs " << ports[1] << ") for two "
	   << "identical queries of (router,dst)=(" << router->GetID()
	   << "," << dest << "); a state/RNG-dependent function has no "
	   << "deterministic first-hop table";
    why = why_ss.str();
    return false;
  }
  /* The tap and the VC range must be as reproducible as the port. A rule
   * whose tap varies between two identical queries has no deterministic
   * shared-resource table, so certifying one would be a guess. */
  if ( ( drops[0] != drops[1] ) || ( vc_starts[0] != vc_starts[1] ) ||
       ( vc_ends[0] != vc_ends[1] ) ) {
    ostringstream why_ss;
    why_ss << "routing function '" << rf_name << "' returned different "
	   << "tap/VC ranges for two identical queries of (router,dst)=("
	   << router->GetID() << "," << dest << "); a shared-resource "
	   << "realization cannot be certified from a state-dependent "
	   << "choice";
    why = why_ss.str();
    return false;
  }
  port = ports[0];
  drop = drops[0];
  vc_start = vc_starts[0];
  vc_end = vc_ends[0];
  return true;
}

void Network::_Alloc( )
{
  assert( ( _size != -1 ) && 
	  ( _nodes != -1 ) && 
	  ( _channels != -1 ) );

  _routers.resize(_size);
  gNodes = _nodes;

  /*booksim used arrays of flits as the channels which makes have capacity of
   *one. To simulate channel latency, flitchannel class has been added
   *which are fifos with depth = channel latency and each cycle the channel
   *shifts by one
   *credit channels are the necessary counter part
   */
  _inject.resize(_nodes);
  _inject_cred.resize(_nodes);
  for ( int s = 0; s < _nodes; ++s ) {
    ostringstream name;
    name << Name() << "_fchan_ingress" << s;
    _inject[s] = new FlitChannel(this, name.str(), _classes);
    _inject[s]->SetSource(NULL, s);
    _timed_modules.push_back(_inject[s]);
    name.str("");
    name << Name() << "_cchan_ingress" << s;
    _inject_cred[s] = new CreditChannel(this, name.str());
    _timed_modules.push_back(_inject_cred[s]);
  }
  _eject.resize(_nodes);
  _eject_cred.resize(_nodes);
  for ( int d = 0; d < _nodes; ++d ) {
    ostringstream name;
    name << Name() << "_fchan_egress" << d;
    _eject[d] = new FlitChannel(this, name.str(), _classes);
    _eject[d]->SetSink(NULL, d);
    _timed_modules.push_back(_eject[d]);
    name.str("");
    name << Name() << "_cchan_egress" << d;
    _eject_cred[d] = new CreditChannel(this, name.str());
    _timed_modules.push_back(_eject_cred[d]);
  }
  _chan.resize(_channels);
  _chan_cred.resize(_channels);
  for ( int c = 0; c < _channels; ++c ) {
    ostringstream name;
    name << Name() << "_fchan_" << c;
    _chan[c] = new FlitChannel(this, name.str(), _classes);
    _timed_modules.push_back(_chan[c]);
    name.str("");
    name << Name() << "_cchan_" << c;
    _chan_cred[c] = new CreditChannel(this, name.str());
    _timed_modules.push_back(_chan_cred[c]);
  }
}

void Network::ReadInputs( )
{
  for(deque<TimedModule *>::const_iterator iter = _timed_modules.begin();
      iter != _timed_modules.end();
      ++iter) {
    (*iter)->ReadInputs( );
  }
}

void Network::Evaluate( )
{
  for(deque<TimedModule *>::const_iterator iter = _timed_modules.begin();
      iter != _timed_modules.end();
      ++iter) {
    (*iter)->Evaluate( );
  }
}

void Network::WriteOutputs( )
{
  for(deque<TimedModule *>::const_iterator iter = _timed_modules.begin();
      iter != _timed_modules.end();
      ++iter) {
    (*iter)->WriteOutputs( );
  }
}

void Network::WriteFlit( Flit *f, int source )
{
  assert( ( source >= 0 ) && ( source < _nodes ) );
  _inject[source]->Send(f);
}

Flit *Network::ReadFlit( int dest )
{
  assert( ( dest >= 0 ) && ( dest < _nodes ) );
  return _eject[dest]->Receive();
}

void Network::WriteCredit( Credit *c, int dest )
{
  assert( ( dest >= 0 ) && ( dest < _nodes ) );
  _eject_cred[dest]->Send(c);
}

Credit *Network::ReadCredit( int source )
{
  assert( ( source >= 0 ) && ( source < _nodes ) );
  return _inject_cred[source]->Receive();
}

void Network::InsertRandomFaults( const Configuration &config )
{
  Error( "InsertRandomFaults not implemented for this topology!" );
}

void Network::OutChannelFault( int r, int c, bool fault )
{
  assert( ( r >= 0 ) && ( r < _size ) );
  _routers[r]->OutChannelFault( c, fault );
}

double Network::Capacity( ) const
{
  return 1.0;
}

/* this function can be heavily modified to display any information
 * neceesary of the network, by default, call display on each router
 * and display the channel utilization rate
 */
void Network::Display( ostream & os ) const
{
  for ( int r = 0; r < _size; ++r ) {
    _routers[r]->Display( os );
  }
}

void Network::DumpChannelMap( ostream & os, string const & prefix ) const
{
  os << prefix << "source_router,source_port,dest_router,dest_port" << endl;
  for(int c = 0; c < _nodes; ++c)
    os << prefix
       << "-1," 
       << _inject[c]->GetSourcePort() << ',' 
       << _inject[c]->GetSink()->GetID() << ',' 
       << _inject[c]->GetSinkPort() << endl;
  for(int c = 0; c < _channels; ++c)
    os << prefix
       << _chan[c]->GetSource()->GetID() << ',' 
       << _chan[c]->GetSourcePort() << ',' 
       << _chan[c]->GetSink()->GetID() << ',' 
       << _chan[c]->GetSinkPort() << endl;
  for(int c = 0; c < _nodes; ++c)
    os << prefix
       << _eject[c]->GetSource()->GetID() << ','
       << _eject[c]->GetSourcePort() << ','
       << "-1,"
       << _eject[c]->GetSinkPort() << endl;
  // Multidrop channels have one source but potentially many sinks, so
  // they don't fit the single source/dest row above -- emit one row per
  // (source, tap) pair instead.
  for(size_t c = 0; c < _md_chan.size(); ++c)
    for(int d = 0; d < _md_chan[c]->NumSinks(); ++d)
      os << prefix
	 << _md_chan[c]->GetSource()->GetID() << ','
	 << _md_chan[c]->GetSourcePort() << ','
	 << _md_chan[c]->SinkRouterID(d) << ','
	 << _md_chan[c]->SinkRouterPort(d) << endl;
}

void Network::DumpNodeMap( ostream & os, string const & prefix ) const
{
  os << prefix << "source_router,dest_router" << endl;
  for(int s = 0; s < _nodes; ++s)
    os << prefix
       << _eject[s]->GetSource()->GetID() << ','
       << _inject[s]->GetSink()->GetID() << endl;
}
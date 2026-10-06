// channel_activity.cpp — versioned per-channel measurement emission.
// See channel_activity.hpp for the contract.

#include <iostream>

#include "channel_activity.hpp"
#include "networks/network.hpp"
#include "routers/router.hpp"
#include "routers/iq_router.hpp"
#include "power/switch_monitor.hpp"
#include "power/buffer_monitor.hpp"

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

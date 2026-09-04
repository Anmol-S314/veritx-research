// ----------------------------------------------------------------------
//
//  File Name: multidropchannel.hpp
//
//  MultiDropChannel models a genuinely shared, tapped physical wire: one
//  source router drives it, and any number of sink routers ("taps") can
//  receive from it -- but, exactly like a real bus, only one flit can be
//  in flight on the wire per cycle. This is what makes it different from
//  wiring the same FlitChannel into several routers' input lists, which
//  would silently broadcast (every tap would pull and enqueue the same
//  flit pointer independently -- double-consumption and pointer reuse).
//
//  Bandwidth: Channel<T> already has exactly one _input/_output slot and
//  one _wait_queue, so at most one flit traverses the wire per cycle
//  regardless of how many taps are registered. That single-slot behavior
//  is inherited unchanged and IS the MECS contention model -- no extra
//  code is needed to enforce it.
//
//  Addressing: a flit is delivered to exactly one tap, chosen by the
//  flit's own Flit::drop field (set by the routing function before the
//  flit reaches this channel, the same way intm/ph are set). Every other
//  tap's ReceiveAt() call sees NULL that cycle. If two taps need the
//  wire in the same cycle, that's a switch-allocation conflict at the
//  source router and is resolved (or not) exactly like any other output
//  port contention -- this channel makes no scheduling decisions itself.
//
//  MultiDropCreditChannel is the reverse path. Unlike the forward wire,
//  BookSim does not model credit-wire contention for ordinary channels
//  either (each ordinary CreditChannel is implicitly single-sender), so
//  for MECS this class simply gives each tap its own independent
//  single-sender credit lane -- physically the closest analogue is a
//  dedicated small credit/counter wire per downstream link, which is how
//  most real designs return flow-control information rather than
//  multiplexing it onto a shared bus. If your design needs true credit
//  contention modeling, that is a documented simplification to revisit,
//  not an oversight.
//
// ----------------------------------------------------------------------

#ifndef _MULTIDROPCHANNEL_HPP_
#define _MULTIDROPCHANNEL_HPP_

#include <vector>
#include <queue>
#include <utility>

#include "flitchannel.hpp"
#include "channel.hpp"
#include "credit.hpp"

using namespace std;

class Router;

typedef Channel<Credit> CreditChannel;

class MultiDropChannel : public FlitChannel {
public:
  MultiDropChannel(Module * parent, string const & name, int classes);

  // Registers one more tap on this channel. Call once per sink router,
  // in the same build-time order the topology's routing function uses
  // to compute Flit::drop for this channel -- the returned index (0,
  // 1, 2, ...) is exactly the value the routing function must stamp
  // into f->drop for a flit addressed to this tap. Also calls
  // SetSink(), so DumpChannelMap()/debug output reflects whichever tap
  // was registered last -- informational only, not used for delivery.
  int AddSink(Router const * router, int port);

  inline int NumSinks() const { return (int)_sinks.size(); }
  inline int SinkRouterPort(int drop) const { return _sink_ports[drop]; }
  int SinkRouterID(int drop) const;

  // Returns this cycle's flit iff it is addressed to `drop`, else NULL.
  // Safe to call once per registered tap per cycle: Receive() is a pure
  // read of the single already-latched _output slot, so every tap sees
  // the same value and only the matching one keeps it.
  virtual Flit * ReceiveAt(int drop);

private:
  vector<Router const *> _sinks;
  vector<int>             _sink_ports;
};

class MultiDropCreditChannel : public CreditChannel {
public:
  MultiDropCreditChannel(Module * parent, string const & name);

  // Registers one more independent credit lane. Must be called in
  // lockstep with the corresponding MultiDropChannel::AddSink() call for
  // the same physical tap so the two drop indices agree -- see
  // Router::AddMultiDropInputChannel(), which enforces this.
  int AddLane();

  inline int NumLanes() const { return _num_lanes; }

  virtual void SendAt(Credit * c, int drop);
  virtual Credit * ReceiveAt(int drop);

  virtual void ReadInputs();
  virtual void Evaluate() {}
  virtual void WriteOutputs();

private:
  int _num_lanes;
  vector<Credit *>                          _input_lane;
  vector<queue<pair<int64_t, Credit *> > >      _wait_queue_lane;
  vector<Credit *>                          _output_lane;
};

#endif

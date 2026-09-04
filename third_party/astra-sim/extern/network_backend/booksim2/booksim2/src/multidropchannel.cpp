// ----------------------------------------------------------------------
//
//  File Name: multidropchannel.cpp
//
// ----------------------------------------------------------------------

#include "multidropchannel.hpp"

#include <cassert>

#include "globals.hpp"
#include "router.hpp"

// ----------------------------------------------------------------------
// MultiDropChannel
// ----------------------------------------------------------------------

MultiDropChannel::MultiDropChannel(Module * parent, string const & name, int classes)
  : FlitChannel(parent, name, classes) {
}

int MultiDropChannel::AddSink(Router const * router, int port) {
  _sinks.push_back(router);
  _sink_ports.push_back(port);
  SetSink(router, port);
  return (int)_sinks.size() - 1;
}

int MultiDropChannel::SinkRouterID(int drop) const {
  assert((drop >= 0) && (drop < NumSinks()));
  return _sinks[drop]->GetID();
}

Flit * MultiDropChannel::ReceiveAt(int drop) {
  assert((drop >= 0) && (drop < NumSinks()));
  Flit * const f = Receive();
  if(f && (f->drop == drop)) {
    return f;
  }
  return NULL;
}

// ----------------------------------------------------------------------
// MultiDropCreditChannel
// ----------------------------------------------------------------------

MultiDropCreditChannel::MultiDropCreditChannel(Module * parent, string const & name)
  : CreditChannel(parent, name), _num_lanes(0) {
}

int MultiDropCreditChannel::AddLane() {
  ++_num_lanes;
  _input_lane.push_back(NULL);
  _wait_queue_lane.push_back(queue<pair<int64_t, Credit *> >());
  _output_lane.push_back(NULL);
  return _num_lanes - 1;
}

void MultiDropCreditChannel::SendAt(Credit * c, int drop) {
  assert((drop >= 0) && (drop < _num_lanes));
  assert(_input_lane[drop] == NULL);
  _input_lane[drop] = c;
}

Credit * MultiDropCreditChannel::ReceiveAt(int drop) {
  assert((drop >= 0) && (drop < _num_lanes));
  return _output_lane[drop];
}

void MultiDropCreditChannel::ReadInputs() {
  for(int d = 0; d < _num_lanes; ++d) {
    if(_input_lane[d]) {
      _wait_queue_lane[d].push(make_pair(GetSimTime() + _delay - 1, _input_lane[d]));
      _input_lane[d] = NULL;
    }
  }
}

void MultiDropCreditChannel::WriteOutputs() {
  for(int d = 0; d < _num_lanes; ++d) {
    _output_lane[d] = NULL;
    if(_wait_queue_lane[d].empty()) {
      continue;
    }
    pair<int64_t, Credit *> const & item = _wait_queue_lane[d].front();
    if(GetSimTime() < item.first) {
      continue;
    }
    assert(GetSimTime() == item.first);
    _output_lane[d] = item.second;
    _wait_queue_lane[d].pop();
  }
}

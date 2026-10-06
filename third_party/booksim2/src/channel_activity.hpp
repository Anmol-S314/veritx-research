// channel_activity.hpp — versioned per-channel measurement emission.
//
// Stable, machine-readable activity counters for one simulated subnet,
// written when the `channel_activity_output` config key names a file.
// This is a MEASUREMENT artifact: per-output-port flit traversals and
// per-input buffer reads/writes counted by the router monitors over the
// whole run, grouped by traffic class.
//
// What it is NOT:
//  - not cycles-busy or occupancy: the monitors count events and router
//    cycles observed, not per-cycle busy state;
//  - not credits/stalls: no such counters exist at this layer;
//  - not VC activity: the class dimension is the traffic class, not VC;
//  - not a route: output ports are reported raw; mapping a port to a
//    certified channel is the reader's job (router id + port join the
//    topology's channel table).
//
// Schema "veritx/channel-activity/v1". Readers must refuse unknown
// major versions rather than guess.

#ifndef _CHANNEL_ACTIVITY_HPP_
#define _CHANNEL_ACTIVITY_HPP_

#include <iosfwd>

class Network;

// Dump one subnet's router activity as versioned JSON to `os`.
// Routers that are not IQRouter-derived (no switch/buffer monitors) are
// counted in `skipped_non_iq_routers`, never fabricated.
void DumpChannelActivity( Network * net, int subnet, std::ostream & os ) ;

#endif

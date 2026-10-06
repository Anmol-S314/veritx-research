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
#include <string>
#include <vector>

class Network;

// Dump one subnet's router activity as versioned JSON to `os`.
// Routers that are not IQRouter-derived (no switch/buffer monitors) are
// counted in `skipped_non_iq_routers`, never fabricated.
void DumpChannelActivity( Network * net, int subnet, std::ostream & os ) ;

// ---- Sampled per-window series (schema "veritx/channel-timeseries/v2")
//
// Same counters as the cumulative dump, windowed by wall time within
// each sim epoch: a window closes at the first poll at or past each
// `sample_period_cycles` boundary. BookSim wall time resets to 0 every
// sim (TrafficManager::Run) while the monitor counters behind the
// baselines never reset, so each backward poll-clock step closes the
// epoch's edge slice as its own window, re-baselines, and restarts
// boundaries at the new epoch's observed start. The one backward step
// per boundary is counted in `time_resets_observed`, documenting
// multi-epoch coverage. Conservation telescopes exactly across any
// number of sims: every flit is counted in exactly one window.
//
// Windows are LOSSY AGGREGATES, not a replayable trace. Every window
// carries its TRUE span in `window_cycles`: boundary windows span the
// observed interval (late polls lengthen spans — the truth is
// recorded, never the nominal period), epoch edges carry the observed
// pre-reset tail, and the trailing partial window carries the run's
// true tail. Denominators must use these spans. Spans are global (one
// sampler): a reader must refuse channels whose spans disagree. The
// residual: an epoch-edge span ends at the last observed event; idle
// cycles after a sim's last counted event are not spanned. No counted
// event can occur in that tail (every counter increment path polls
// the sim clock), so flit attribution is exact and only idle time is
// unspanned. A zero-advance edge (counters moved with no observed
// time advance) folds forward into the next window instead of
// emitting a zero-span window: spans stay positive, flits stay
// counted exactly once.
//
// `stalls_per_window` is ALWAYS null: Phase-0 spike verdict ABSENT — no
// per-channel stall counter exists in the monitor layer, TRACK_STALLS
// stdout vectors are per-router-per-class and uncompiled by default.
// A reader must render the stall column as an explicit gap, never zeros.
//
// `logical_channel_id` packs the join key the reader needs:
//   id = subnet * 100000000 + router_id * 10000 + output_port
// Decode: subnet = id / 100000000; router = (id / 10000) % 10000;
// port = id % 10000. Limits (router < 100000, ports < 10000) are
// enforced at init: exceeding them fails the run, never wraps ids.
//
// `capacity_formula` is the FROZEN utilization definition shared with
// the typed reader; changing the string breaks reader compatibility by
// design (the reader refuses unknown definitions).
struct TimeseriesConfig {
  long sample_period_cycles; // > 0, enforced by the caller
  std::string run_hash;      // non-empty, enforced by the caller
  long link_capacity_flits_per_cycle; // > 0, stated not measured
  std::string backend;       // fork identity, e.g. "booksim"
  std::string version;       // fork identity, e.g. "veritx-fork"
  std::string binary_hash;   // sha256 of the binary, non-empty
  std::vector<std::string> input_hashes;
};

// Snapshot the baseline and arm periodic sampling. Returns false when
// any (router, port) exceeds the id packing limits above.
bool TimeseriesSamplerInit( Network * const * nets, int subnets,
                             const TimeseriesConfig & cfg ) ;

// Poll from the sim-time path (cheap no-op unless armed). Captures one
// snapshot per window boundary crossed by `sim_time`.
void TimeseriesSamplerPoll( int sim_time ) ;

// Emit the whole run as one series document. `sim_end_time` is the
// traffic manager's final time; the trailing partial window is
// included with its true span whenever the run advanced past the last
// window start. Returns false (run must fail) when a window delta
// regresses, never a series that cannot telescope exactly.
bool DumpChannelTimeseries( std::ostream & os, int sim_end_time ) ;

#endif

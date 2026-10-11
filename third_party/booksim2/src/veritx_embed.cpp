#include "veritx_embed.hpp"

#include <cassert>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <set>
#include <vector>

#include "booksim.hpp"
#include "config_utils.hpp"
#include "network.hpp"
#include "random_utils.hpp"
#include "routefunc.hpp"

// Globals that live in main.cpp in the standalone build (which the embed
// library excludes); the routers / route funcs reference them. MUST be at
// global scope (unqualified ::gK etc.).
TrafficManager * trafficManager = NULL;
int GetSimTime() { return trafficManager->getTime(); }
bool gPrintActivity = false;
bool gTrace = false;
std::ostream * gWatchOut = NULL;
int gK = 0, gN = 0, gC = 0, gNodes = 0;

namespace VeritXEmbed {

EmbedTM::EmbedTM(BookSimConfig const & config, std::vector<Network *> const & net)
    : TrafficManager(config, net), _retired_q(_nodes) {}

void EmbedTM::RunCycles(int64_t cycles) {
  for (int64_t i = 0; i < cycles; ++i) _Step();
}

int EmbedTM::_BuildUnicast(int src, int dst, int size, int cl, int64_t time) {
  if (src < 0 || src >= _nodes || dst < 0 || dst >= _nodes || size <= 0)
    throw std::invalid_argument("invalid BookSim host unicast endpoints/size");
  if (_host_flit_limit <= 0)
    throw std::logic_error("BookSim host flit limit must be set before injection");
  int64_t const resident = InFlightFlitCount();
  if (size > _host_flit_limit || resident > _host_flit_limit - size)
    return -1;
  int const pid = _cur_pid++;
  ++_packets_requested;
  _unicast_flits += size;
  int const subnetwork = RandomInt(_subnets - 1);
  for (int i = 0; i < size; ++i) {
    Flit * f = Flit::New();
    f->id = _cur_id++;
    assert(_cur_id);
    f->pid = pid;
    f->watch = false;
    f->subnetwork = subnetwork;
    f->src = src;
    f->ctime = time;
    f->record = false;
    f->cl = cl;
    f->type = Flit::ANY_TYPE;
    f->head = (i == 0);
    f->tail = (i == size - 1);
    f->dest = f->head ? dst : -1;
    f->pri = 0;
    f->vc = -1;
    f->mcast = false;
    _total_in_flight_flits[f->cl].insert(std::make_pair(f->id, f));
    assert(f && "_BuildUnicast: null flit");
    _partial_packets[src][cl].push_back(f);
  }
  return pid;
}

int EmbedTM::_BuildMcastStream(int src, std::vector<int> const & dsts,
                               int cl, int64_t time) {
  if (src < 0 || src >= _nodes || dsts.size() < 2)
    throw std::invalid_argument("invalid BookSim multicast source or fanout");
  if (_host_flit_limit <= 0)
    throw std::logic_error("BookSim host flit limit must be set before injection");
  int64_t const resident = InFlightFlitCount();
  if ((int64_t)dsts.size() > _host_flit_limit
      || resident > _host_flit_limit - (int64_t)dsts.size())
    return -1;
  std::set<int> unique;
  for (size_t i = 0; i < dsts.size(); ++i) {
    if (dsts[i] < 0 || dsts[i] >= _nodes || dsts[i] == src
        || !unique.insert(dsts[i]).second)
      throw std::invalid_argument(
          "BookSim multicast destinations must be unique valid non-source nodes");
  }
  int const far_end = dsts.back();
  int const pid = _cur_pid++;
  int const subnetwork = RandomInt(_subnets - 1);

  auto make = [&](int dest, int branch_id, bool is_mcast) -> Flit * {
    Flit * f = Flit::New();
    f->id = _cur_id++;
    assert(_cur_id);
    f->pid = pid;
    f->watch = false;
    f->subnetwork = subnetwork;
    f->src = src;
    f->dest = dest;
    f->ctime = time;
    f->record = false;
    f->cl = cl;
    f->type = Flit::ANY_TYPE;
    f->head = true;
    f->tail = true;
    f->pri = 0;
    f->vc = -1;
    f->mcast = is_mcast;
    f->mcast_branch = true;
    f->mcast_branch_index = branch_id;
    _total_in_flight_flits[f->cl].insert(std::make_pair(f->id, f));
    return f;
  };

  // One operation PID owns all destination branches. The first router on the
  // source path consumes these records and queues them in its real input VC;
  // each then uses the ordinary routing, allocation, credit and link pipeline.
  ++_packets_requested;
  _mcast_deliveries += (int64_t)dsts.size();
  _mcast_branch_flits += (int64_t)dsts.size();
  Flit * stream = make(far_end, (int)dsts.size() - 1, true);
  for (size_t i = 0; i + 1 < dsts.size(); ++i) {
    Flit * branch = make(dsts[i], (int)i, false);
    branch->mcast_injector_state = _buf_states[src][subnetwork];
    stream->mcast_copies.push_back(branch);
  }
  _partial_packets[src][cl].push_back(stream);
  return pid;
}

void EmbedTM::SetHostFlitLimit(int64_t limit) {
  if (limit <= 0 || InFlightFlitCount() != 0)
    throw std::invalid_argument("host flit limit must be positive and set while idle");
  _host_flit_limit = limit;
}

int EmbedTM::InjectUnicast(int src, int dst, int size, int cl) {
  // VeritX: per-class bookkeeping containers are dimensioned by the
  // config's `classes` count. A class id at or above it means the
  // embedded config does not cover the canonical classes — the machine
  // renderer must declare classes >= max class id + 1, never silently
  // wrap or truncate the class here.
  if (cl < 0 || cl >= _classes)
    throw std::invalid_argument("BookSim host traffic class is not configured");
  return _BuildUnicast(src, dst, size, cl, _time);
}

int EmbedTM::InjectMcast(int src, std::vector<int> const & dsts, int cl) {
  if (cl < 0 || cl >= _classes)
    throw std::invalid_argument("BookSim host multicast traffic class is not configured");
  return _BuildMcastStream(src, dsts, cl, _time);
}

void EmbedTM::_RetireFlit(Flit * f, int dest) {
  TrafficManager::_RetireFlit(f, dest);
  ++_flits_retired;
  if (f->tail) ++_tails_retired;
  // Packet-complete signal: the tail flit (single-flit packets are
  // head&&tail, so every mcast copy fires here as well).
  if (f->tail) {
    Retired r;
    r.atime = _time;
    r.cl = f->cl;
    r.src = f->src;
    r.dst = dest;
    r.pid = f->pid;
    r.itime = f->ctime;
    r.multicast = f->mcast_branch;
    r.branch_id = f->mcast_branch_index;
    r.route_steps = f->hops;
    r.route_trace = f->mcast_route_trace;
    r.physical_link_flits = 0;
    if (r.multicast) {
      // Native multicast V1 is restricted to the row-major 2D mesh, whose
      // local eject output follows the four dimension-direction outputs.
      if (r.route_trace.empty() || r.route_trace.back().first != dest
          || r.route_trace.back().second != 4)
        throw std::logic_error("multicast route trace lacks its destination eject step");
      if ((int)r.route_trace.size() != r.route_steps)
        throw std::logic_error("multicast route-step count differs from its trace");
      r.physical_link_flits = (int)r.route_trace.size() - 1;
      ++_mcast_branch_flits_retired;
      _mcast_branch_physical_link_flits += r.physical_link_flits;
    }
    _retired_q[dest].push_back(r);
  }
}

std::vector<Retired> EmbedTM::DrainRetired(int node) {
  std::vector<Retired> out;
  out.swap(_retired_q[node]);
  return out;
}

EmbedTM * CreateEmbeddedTM(std::string const & cfg_file,
                           std::vector<std::string> const & overrides) {
  // Replicate main.cpp's CLI arg vector: config file + param=value overrides.
  std::vector<char *> argv;
  std::vector<std::string> args;
  args.push_back("booksim");
  args.push_back(cfg_file);
  for (size_t i = 0; i < overrides.size(); ++i) args.push_back(overrides[i]);
  for (size_t i = 0; i < args.size(); ++i)
    argv.push_back(const_cast<char *>(args[i].c_str()));

  BookSimConfig config;
  if (!ParseArgs(&config, argv.size(), &argv[0])) {
    std::cerr << "veritx_embed: failed to parse cfg '" << cfg_file << "'"
              << std::endl;
    return NULL;
  }

  InitializeRoutingMap(config);

  std::vector<Network *> net;
  int subnets = config.GetInt("subnets");
  net.resize(subnets);
  for (int i = 0; i < subnets; ++i) {
    std::ostringstream name;
    name << "network_" << i;
    net[i] = Network::New(config, name.str());
  }

  EmbedTM * tm = new EmbedTM(config, net);
  (void)net;  // ownership transferred to the TrafficManager

  trafficManager = tm;
  if (config.GetIntMap().count("k")) gK = config.GetInt("k");
  if (config.GetIntMap().count("n")) gN = config.GetInt("n");
  if (config.GetIntMap().count("c")) gC = config.GetInt("c");
  return tm;
}

}  // namespace VeritXEmbed

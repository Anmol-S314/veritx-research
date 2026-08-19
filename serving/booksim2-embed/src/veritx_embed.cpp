#include "veritx_embed.hpp"

#include <cassert>
#include <iostream>
#include <sstream>
#include <string>
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

void EmbedTM::RunCycles(int cycles) {
  for (int i = 0; i < cycles; ++i) _Step();
}

void EmbedTM::_BuildUnicast(int src, int dst, int size, int cl, int time) {
  assert(size > 0);
  assert(dst >= 0 && dst < _nodes);
  int const pid = _cur_pid++;
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
    _partial_packets[src][cl].push_back(f);
  }
}

void EmbedTM::_BuildMcastStream(int src, std::vector<int> const & dsts,
                                int cl, int time) {
  assert(!dsts.empty());
  int const far_end = dsts.back();
  assert(far_end >= 0 && far_end < _nodes);
  int const pid = _cur_pid++;
  int const subnetwork = RandomInt(_subnets - 1);

  auto make = [&](int dest, bool is_mcast) -> Flit * {
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
    _total_in_flight_flits[cl].insert(std::make_pair(f->id, f));
    return f;
  };

  // One stream flit to the far end; every other dest is a pre-registered
  // copy that the router fork ejects at its node along the path.
  Flit * stream = make(far_end, true);
  for (size_t i = 0; i + 1 < dsts.size(); ++i)
    stream->mcast_copies.push_back(make(dsts[i], false));
  _partial_packets[src][cl].push_back(stream);
}

void EmbedTM::InjectUnicast(int src, int dst, int size, int cl) {
  _BuildUnicast(src, dst, size, cl, _time);
}

void EmbedTM::InjectMcast(int src, std::vector<int> const & dsts, int cl) {
  _BuildMcastStream(src, dsts, cl, _time);
}

void EmbedTM::_RetireFlit(Flit * f, int dest) {
  TrafficManager::_RetireFlit(f, dest);
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

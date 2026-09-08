#include "veritx_embed.hpp"

#include <cassert>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "json/json.hpp"  // -I extern/helper (fabric target); standalone Makefile does not compile this TU

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

void EmbedTM::_BuildUnicast(int src, int dst, int size, int cl, int64_t time) {
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
    assert(f && "_BuildUnicast: null flit");
    _partial_packets[src][cl].push_back(f);
  }
}

void EmbedTM::_BuildMcastStream(int src, std::vector<int> const & dsts,
                                int cl, int64_t time) {
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
  // The ASTRA-sim frontend passes network.json (which names the real .cfg
  // in its booksim-config-file member); older callers pass a raw BookSim
  // .cfg directly. Feeding JSON to the yacc grammar dies with a bare
  // "Parse error on line 1", so unwrap first. Either way, booksim_cfg
  // below is always a genuine .cfg by the time ParseArgs sees it.
  std::string booksim_cfg = cfg_file;
  {
    std::ifstream probe(cfg_file.c_str(), std::ios::binary);
    if (!probe.is_open()) {
      std::cerr << "veritx_embed: cannot open config '" << cfg_file << "'"
                << std::endl;
      return NULL;
    }
    // Skip UTF-8 BOM + whitespace; JSON must start with '{'.
    char bom[3] = {0, 0, 0};
    probe.read(bom, 3);
    bool has_bom = (probe.gcount() == 3 && (unsigned char)bom[0] == 0xEF &&
                    (unsigned char)bom[1] == 0xBB && (unsigned char)bom[2] == 0xBF);
    if (!has_bom) probe.clear(), probe.seekg(0);
    probe >> std::ws;
    if (probe.peek() == '{') {
      nlohmann::json j;
      try {
        probe >> j;
      } catch (std::exception const & e) {
        std::cerr << "veritx_embed: invalid JSON in '" << cfg_file
                  << "': " << e.what() << std::endl;
        return NULL;
      }
      if (!j.contains("booksim-config-file") ||
          !j["booksim-config-file"].is_string() ||
          j["booksim-config-file"].get<std::string>().empty()) {
        std::cerr << "veritx_embed: JSON config '" << cfg_file
                  << "' lacks a non-empty string member "
                     "\"booksim-config-file\"" << std::endl;
        return NULL;
      }
      booksim_cfg = j["booksim-config-file"].get<std::string>();
      if (booksim_cfg.empty() || booksim_cfg[0] != '/') {
        std::string dir = cfg_file;
        std::string::size_type slash = dir.find_last_of('/');
        dir = (slash == std::string::npos) ? "." : dir.substr(0, slash);
        booksim_cfg = dir + "/" + booksim_cfg;
      }
    }
  }
  // Replicate main.cpp's CLI arg vector: config file + param=value overrides.
  std::vector<char *> argv;
  std::vector<std::string> args;
  args.push_back("booksim");
  args.push_back(booksim_cfg);
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

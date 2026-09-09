#include "veritx_ext.hpp"
#include "routefunc.hpp"

#include "matrixtraffic.hpp"
#include "yxroute.hpp"
// #include "snakeroute.hpp"  // Removed: requires multicast support

#include <fstream>
#include <sstream>
#include <vector>
#include <algorithm>
#include <cassert>

// ===========================================================================
//  TRACE TRAFFIC PATTERN  --  replays event-stream traces.
//  Format:  cycle src class dst size_bytes   (whitespace-delimited)
//  Example: 0 3 0 17 64
//            127 17 0 3 64
// ===========================================================================

// TraceEntry and TraceTrafficPattern declared in veritx_ext.hpp
// Methods defined below; keep static g_trace_pattern for trafficmanager hook

// Binary trace format: 12 bytes per entry (cycle:uint64, src:uint16, cl:uint16, dst:uint16, size:uint16)
static const uint32_t BINARY_MAGIC = 0x54524143;  // "TRAC"

TraceTrafficPattern::TraceTrafficPattern(int nodes, std::string const & filename)
    : TrafficPattern(nodes), _lastDest(nodes, -1)
{
    // Try binary format first (check magic number)
    std::ifstream fin(filename, std::ios::binary);
    if (!fin.is_open()) {
        std::cerr << "Error: cannot open trace file: " << filename << std::endl;
        exit(-1);
    }

    uint32_t magic = 0;
    fin.read(reinterpret_cast<char*>(&magic), sizeof(magic));
    
    if (magic == BINARY_MAGIC) {
        // Binary format: header + packed records
        uint32_t count = 0;
        fin.read(reinterpret_cast<char*>(&count), sizeof(count));
        
        // Pre-allocate vector
        _trace.reserve(count);
        
        // Read all records in one bulk read (fast!)
        struct BinaryRecord {
            uint64_t cycle;
            uint16_t src;
            uint16_t cl;
            uint16_t dst;
            uint16_t size;
        } __attribute__((packed));
        
        std::vector<BinaryRecord> records(count);
        fin.read(reinterpret_cast<char*>(records.data()), count * sizeof(BinaryRecord));
        
        // Convert to TraceEntry (preserves existing API)
        _trace.reserve(count);
        for (const auto & r : records) {
            TraceEntry e;
            e.cycle = r.cycle;
            e.src = r.src;
            e.cl = r.cl;
            e.dst = r.dst;
            e.size = r.size;
            
            if (e.src >= 0 && e.src < nodes && e.dst >= 0 && e.dst < nodes) {
                _trace.push_back(e);
            }
        }
        
        std::cout << "Loaded binary trace: " << _trace.size() << " packets from " << filename << std::endl;
    } else {
        // Text format (original parser)
        fin.close();
        std::ifstream text_fin(filename);
        
        std::string line;
        int64_t lineno = 0;
        while (std::getline(text_fin, line)) {
            lineno++;
            if (line.empty() || line[0] == '#' || line[0] == '%') continue;

            std::istringstream iss(line);
            TraceEntry e;
            if (!(iss >> e.cycle >> e.src >> e.cl >> e.dst >> e.size)) {
                std::cerr << "Warning: skipping malformed trace line " << lineno << std::endl;
                continue;
            }

            if (e.src < 0 || e.src >= nodes || e.dst < 0 || e.dst >= nodes) {
                std::cerr << "Warning: skipping out-of-range trace entry (src=" << e.src
                          << " dst=" << e.dst << " nodes=" << nodes << ") at line " << lineno << std::endl;
                continue;
            }

            _trace.push_back(e);
        }
        
        std::cout << "Loaded text trace: " << _trace.size() << " packets from " << filename << std::endl;
    }

    // Sort by cycle for deterministic replay
    std::sort(_trace.begin(), _trace.end(),
              [](const TraceEntry & a, const TraceEntry & b) { return a.cycle < b.cycle; });

    if (!_trace.empty()) {
        std::cout << "  Time range: [" << _trace.front().cycle << ", "
                  << _trace.back().cycle << "]" << std::endl;
        std::cout << "  Packet size range: [" << _trace.front().size << ", "
                  << _trace.back().size << "]" << std::endl;
    }

    // Build last-dest map for BookSim's dest() interface
    for (auto const & e : _trace) {
        _lastDest[e.src] = e.dst;
    }
}

int TraceTrafficPattern::dest(int source) {
    // BookSim calls dest() to find destination for a given source.
    // If source is not in the trace, return source (self-loop) — these
    // non-participating nodes should never actually inject; they're just
    // BookSim iterating over all N nodes.
    if (source >= 0 && source < (int)_lastDest.size() && _lastDest[source] >= 0)
        return _lastDest[source];
    return source;  // self-loop: non-participating node
}

void TraceTrafficPattern::reset() {
    _ptr = 0;
}
int64_t TraceTrafficPattern::nextCycle() const { return _ptr < _trace.size() ? _trace[_ptr].cycle : -1; }
int TraceTrafficPattern::nextSrc() const { return _ptr < _trace.size() ? _trace[_ptr].src : -1; }
int TraceTrafficPattern::nextDst() const { return _ptr < _trace.size() ? _trace[_ptr].dst : -1; }
int TraceTrafficPattern::nextCl() const { return _ptr < _trace.size() ? _trace[_ptr].cl : 0; }
int TraceTrafficPattern::nextSize() const { return _ptr < _trace.size() ? _trace[_ptr].size : 0; }
void TraceTrafficPattern::advance() { _ptr++; }
bool TraceTrafficPattern::done() const { return _ptr >= _trace.size(); }
size_t TraceTrafficPattern::count() const { return _trace.size(); }

// Global instance for traffic manager to access (set when creating trace pattern)
static TraceTrafficPattern * g_trace_pattern = nullptr;

TraceTrafficPattern * GetTracePattern() { return g_trace_pattern; }
int g_trace_dst = -1;
int g_trace_size = -1;
bool g_trace_active = false;
int64_t g_trace_reqtime = -1;

// ===========================================================================
//  TRAFFIC PATTERNS  --  add a branch, return NULL for anything not yours.
//  Selected in a .cfg with:  traffic = <name>(<args>);
// ===========================================================================
TrafficPattern * VeritXNewTraffic(std::string const & name,
                                  std::vector<std::string> const & params,
                                  int nodes,
                                  Configuration const * const config)
{
  if (name == "matrix") {
    if (params.empty()) {
      cout << "Error: matrix traffic pattern requires a filename: matrix(<file>)" << endl;
      exit(-1);
    }
    return new MatrixTrafficPattern(nodes, params[0]);
  }

  if (name == "trace") {
    if (params.empty()) {
      cout << "Error: trace traffic pattern requires a filename: trace(<file>)" << endl;
      exit(-1);
    }
    auto * tp = new TraceTrafficPattern(nodes, params[0]);
    g_trace_pattern = tp;
    return tp;
  }

  return NULL; // not ours -> Booksim reports "Unknown traffic pattern"
}

// ===========================================================================
//  ROUTING FUNCTIONS  --  one line each.
// ===========================================================================
void VeritXRegisterRouting()
{
  gRoutingFunctionMap["yx_mesh"] = &yx_mesh;
  // gRoutingFunctionMap["snake_mesh"] = &snake_mesh;  // Removed: requires multicast support
}

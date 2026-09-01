#ifndef _VERITX_EXT_HPP_
#define _VERITX_EXT_HPP_

#include <string>
#include <vector>
#include <cstdint>

#include "traffic.hpp"
#include "config_utils.hpp"

// Trace replay: cycle-accurate injection from {cyc src cl dst sz} file
struct TraceEntry {
    int64_t cycle;
    int     src;
    int     cl;
    int     dst;
    int     size;
};

class TraceTrafficPattern : public TrafficPattern {
public:
    TraceTrafficPattern(int nodes, std::string const & filename);
    virtual int dest(int source) override;
    virtual void reset() override;
    int64_t nextCycle() const;
    int nextSrc() const;
    int nextDst() const;
    int nextCl() const;
    int nextSize() const;
    void advance();
    bool done() const;
    size_t count() const;
    const std::vector<TraceEntry>& trace() const { return _trace; }
private:
    std::vector<TraceEntry> _trace;
    size_t _ptr = 0;
    std::vector<int> _lastDest;
};
TraceTrafficPattern * GetTracePattern();
// globals for cycle-accurate trace injection (set by trafficmanager::_Inject)
extern int g_trace_dst;
extern int g_trace_size;
extern bool g_trace_active;

// VeritX extension registry.
//
// Booksim's two factories (TrafficPattern::New in traffic.cpp, InitializeRoutingMap
// in routefunc.cpp) redirect into the functions below. Those redirects live as
// ordinary edits in the vendored subtree -- to add a traffic pattern or routing
// function you edit veritx_ext.cpp, not the factory files. See VERITX.md.

// Called from TrafficPattern::New() when Booksim doesn't recognise a pattern.
// Return NULL for a name you don't own; Booksim then reports it as unknown.
TrafficPattern * VeritXNewTraffic(std::string const & name,
                                  std::vector<std::string> const & params,
                                  int nodes,
                                  Configuration const * const config);

// Called at the end of InitializeRoutingMap(), after Booksim's own entries.
void VeritXRegisterRouting();

#endif

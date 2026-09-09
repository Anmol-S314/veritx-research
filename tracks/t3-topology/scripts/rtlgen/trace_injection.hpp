// trace_injection.hpp — Trace-based injection process for BookSim
// Reads cycle-stamped trace files and injects packets at the correct time.
// Format: "cycle src dst [class]" per line (whitespace-separated)

#ifndef _TRACE_INJECTION_HPP_
#define _TRACE_INJECTION_HPP_

#include <string>
#include <vector>
#include <map>
#include <fstream>
#include <iostream>
#include <cassert>
#include "injection.hpp"

using namespace std;

struct TraceEntry {
  int cycle;
  int src;
  int dst;
  int cl;  // class (0 = default)
};

class TraceInjectionProcess : public InjectionProcess {
private:
  // Map from (cycle, source) -> list of (dst, class) pairs
  map<int, map<int, vector<pair<int, int>>>> _schedule;
  int _current_cycle;
  int _max_cycle;
  int _total_packets;
  
public:
  TraceInjectionProcess(int nodes, const string& trace_file);
  virtual ~TraceInjectionProcess() {}
  
  virtual bool test(int source);
  virtual void reset();
  
  int max_cycle() const { return _max_cycle; }
  int total_packets() const { return _total_packets; }
  
  // Get next destination for a source at current time (for _GeneratePacket)
  int next_dst(int source, int& cl);
};

#endif

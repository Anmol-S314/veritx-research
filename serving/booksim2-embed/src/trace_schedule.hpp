// trace_schedule.hpp — Simple trace schedule for BookSim
// Loads cycle-stamped traces and provides next-packet lookup

#ifndef _TRACE_SCHEDULE_HPP_
#define _TRACE_SCHEDULE_HPP_

#include <string>
#include <vector>
#include <map>
#include <fstream>
#include <iostream>

using namespace std;

struct TracePacket {
  int dst;
  int cl;
  int size;
};

class TraceSchedule {
private:
  // schedule[cycle][source] = list of packets
  map<int, map<int, vector<TracePacket>>> _sched;
  int _max_cycle;
  int _total;

public:
  TraceSchedule() : _max_cycle(0), _total(0) {}
  
  bool load(const string& filename) {
    ifstream fin(filename.c_str());
    if (!fin.is_open()) return false;
    
    string line;
    while (getline(fin, line)) {
      if (line.empty() || line[0] == '%' || line[0] == '#') continue;
      istringstream iss(line);
      int cycle, src, cl = 0, dst, sz = 1;
      if (iss >> cycle >> src >> cl >> dst) {
        iss >> sz;
        if (sz < 1) sz = 1;
        if (src >= 0 && dst >= 0) {
          TracePacket p; p.dst = dst; p.cl = cl; p.size = sz;
          _sched[cycle][src].push_back(p);
          if (cycle > _max_cycle) _max_cycle = cycle;
          _total++;
        }
      }
    }
    return true;
  }
  
  bool has_packet(int cycle, int source) const {
    auto it = _sched.find(cycle);
    if (it == _sched.end()) return false;
    auto src_it = it->second.find(source);
    return (src_it != it->second.end() && !src_it->second.empty());
  }
  
  TracePacket next(int cycle, int source) {
    TracePacket p = {-1, 0, 1};
    auto it = _sched.find(cycle);
    if (it != _sched.end()) {
      auto src_it = it->second.find(source);
      if (src_it != it->second.end() && !src_it->second.empty()) {
        p = src_it->second.front();
        src_it->second.erase(src_it->second.begin());
      }
    }
    return p;
  }
  
  int max_cycle() const { return _max_cycle; }
  int total() const { return _total; }
};

#endif

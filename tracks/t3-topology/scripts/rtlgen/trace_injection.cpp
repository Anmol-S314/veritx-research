// trace_injection.cpp — Trace-based injection process for BookSim

#include "trace_injection.hpp"
#include <sstream>
#include <algorithm>

TraceInjectionProcess::TraceInjectionProcess(int nodes, const string& trace_file)
  : InjectionProcess(nodes, 0.0), _current_cycle(0), _max_cycle(0), _total_packets(0)
{
  ifstream fin(trace_file.c_str());
  if (!fin.is_open()) {
    cerr << "Error: Could not open trace file: " << trace_file << endl;
    exit(-1);
  }
  
  string line;
  while (getline(fin, line)) {
    // Skip comments and empty lines
    if (line.empty() || line[0] == '%') continue;
    
    istringstream iss(line);
    int cycle, src, dst, cl = 0;
    if (iss >> cycle >> src >> dst) {
      iss >> cl;  // optional class
      
      if (src >= 0 && src < _nodes && dst >= 0 && dst < _nodes) {
        _schedule[cycle][src].push_back(make_pair(dst, cl));
        _max_cycle = max(_max_cycle, cycle);
        _total_packets++;
      }
    }
  }
  
  fin.close();
  _current_cycle = 0;
  
  cout << "TraceInjectionProcess: loaded " << _total_packets 
       << " packets, max cycle = " << _max_cycle << endl;
}

bool TraceInjectionProcess::test(int source)
{
  // Check if there's a packet for this source at the current cycle
  auto it = _schedule.find(_current_cycle);
  if (it != _schedule.end()) {
    auto src_it = it->second.find(source);
    if (src_it != it->second.end() && !src_it->second.empty()) {
      return true;
    }
  }
  return false;
}

void TraceInjectionProcess::reset()
{
  _current_cycle = 0;
}

int TraceInjectionProcess::next_dst(int source, int& cl)
{
  // Get next destination for this source at current cycle
  auto it = _schedule.find(_current_cycle);
  if (it != _schedule.end()) {
    auto src_it = it->second.find(source);
    if (src_it != it->second.end() && !src_it->second.empty()) {
      pair<int, int> entry = src_it->second.front();
      src_it->second.erase(src_it->second.begin());
      cl = entry.second;
      return entry.first;
    }
  }
  cl = 0;
  return -1;
}

// Factory function to create trace injection process
InjectionProcess * TraceInjectionProcess::New(string const & inject, int nodes,
                                               double load, 
                                               Configuration const * const config)
{
  // Parse: "trace_input=<file>"
  size_t eq_pos = inject.find('=');
  if (eq_pos != string::npos) {
    string filename = inject.substr(eq_pos + 1);
    return new TraceInjectionProcess(nodes, filename);
  }
  
  // Or: "trace_input(<file>)"
  size_t left = inject.find('(');
  if (left != string::npos) {
    size_t right = inject.find(')');
    if (right != string::npos) {
      string filename = inject.substr(left + 1, right - left - 1);
      return new TraceInjectionProcess(nodes, filename);
    }
  }
  
  cerr << "Error: Invalid trace_input format: " << inject << endl;
  exit(-1);
  return NULL;
}

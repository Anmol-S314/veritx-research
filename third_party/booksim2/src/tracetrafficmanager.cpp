#include "tracetrafficmanager.hpp"

#include <algorithm>
#include <sstream>
#include <cstdlib>

TraceTrafficManager::TraceTrafficManager(Configuration const & config,
                                          vector<Network *> const & net)
  : TrafficManager(config, net), _last_issue_source(-1)
{
  _trace_queue.resize(_nodes);
  _pending_event.resize(_nodes);
  _pending_valid.assign(_nodes, false);

  // Swap out whatever TrafficManager's base constructor built from
  // `traffic = ...;` (protected member, so this is legal from here) for
  // our own pattern. This is the only thing that decides WHERE a packet
  // goes, and it's virtual, so no BookSim source patch is needed for it.
  for (int c = 0; c < _classes; ++c) {
    delete _traffic_pattern[c];
    _traffic_pattern[c] = new TraceFileTrafficPattern(_nodes, this);
  }

  string trace_file = config.GetStr("trace_file");
  if (trace_file.empty()) {
    Error("TraceTrafficManager: 'trace_file' not set in config "
          "(add e.g. trace_file = trace.csv; )");
  }
  _LoadTraceFile(trace_file);

  string out_file = config.GetStr("trace_packet_log");
  if (!out_file.empty()) {
    _packets_csv.open(out_file.c_str());
    _packets_csv << "packet_id,transaction_id,src,dst,type,packet_size_flits,"
                    "request_time,injection_time,arrival_time,"
                    "source_queue_delay,network_latency,total_latency,hops\n";
  }
}

TraceTrafficManager::~TraceTrafficManager()
{
  if (_packets_csv.is_open()) {
    _packets_csv.close();
  }
}

void TraceTrafficManager::_LoadTraceFile(string const & filename)
{
  std::ifstream in(filename.c_str());
  if (!in.is_open()) {
    Error("TraceTrafficManager: could not open trace file " + filename);
  }

  std::string line;
  int line_no = 0;
  bool first_line = true;

  while (std::getline(in, line)) {
    ++line_no;
    if (line.empty()) continue;

    if (first_line) {
      first_line = false;
      // Optional header row support: "timestamp,src,dst,..." - if the
      // first field isn't a number, treat the line as a header and skip it.
      std::string first_field = line.substr(0, line.find(','));
      if (first_field.find_first_not_of("0123456789") != std::string::npos) {
        continue;
      }
    }

    std::stringstream ss(line);
    std::string field;
    std::vector<std::string> fields;
    while (std::getline(ss, field, ',')) {
      fields.push_back(field);
    }

    // Required: timestamp,src,dst,type,packet_size
    // Optional 6th column: transaction_id
    if (fields.size() < 5) {
      std::ostringstream err;
      err << "TraceTrafficManager: malformed trace line " << line_no
          << " (need at least timestamp,src,dst,type,packet_size): " << line;
      Error(err.str());
    }

    TraceEvent ev;
    ev.timestamp = strtoull(fields[0].c_str(), NULL, 10);
    ev.src       = atoi(fields[1].c_str());
    ev.dst       = atoi(fields[2].c_str());
    ev.txn_type  = (fields[3] == "WRITE") ? 1 : (fields[3] == "READ") ? 0 : 2;
    ev.packet_size = atoi(fields[4].c_str());
    ev.transaction_id = (fields.size() > 5)
                           ? strtoull(fields[5].c_str(), NULL, 10)
                           : (uint64_t) line_no;

    if (ev.src < 0 || ev.src >= _nodes || ev.dst < 0 || ev.dst >= _nodes) {
      std::ostringstream err;
      err << "TraceTrafficManager: trace line " << line_no
          << " references a node outside [0, " << (_nodes - 1) << "]";
      Error(err.str());
    }
    if (ev.packet_size <= 0) {
      std::ostringstream err;
      err << "TraceTrafficManager: trace line " << line_no
          << " has non-positive packet_size";
      Error(err.str());
    }

    _trace_queue[ev.src].push_back(ev);
  }

  // Trace lines for a given source don't have to appear in cycle order in
  // the file; sort each source's queue so _IssuePacket() only ever has to
  // look at the front element.
  for (int s = 0; s < _nodes; ++s) {
    std::stable_sort(_trace_queue[s].begin(), _trace_queue[s].end(),
                      [](TraceEvent const & a, TraceEvent const & b) {
                        return a.timestamp < b.timestamp;
                      });
  }
}

int TraceTrafficManager::_IssuePacket(int source, int cl)
{
  // TrafficManager::_Inject() (trafficmanager.cpp) only calls
  // _IssuePacket(source, cl) when _partial_packets[source][cl] is already
  // empty, i.e. the previous packet from this source has fully left the
  // source injection buffer. So it's always safe to start a new one here
  // -- multiple close-together trace events from the *same* source will
  // naturally serialize exactly like a real single injection port would.
  if (_trace_queue[source].empty()) return 0;

  TraceEvent const & ev = _trace_queue[source].front();
  if ((uint64_t) _time < ev.timestamp) return 0; // not ready yet

  _pending_event[source] = ev;
  _pending_valid[source] = true;
  _last_issue_source     = source;
  _trace_queue[source].pop_front();

  // Replicate the two side effects stock _IssuePacket() would have had.
  // NEEDS TESTING: confirm nothing downstream depends on these matching
  // exactly what the statistical path would have produced.
  _packet_seq_no[source]++;
  _requestsOutstanding[source]++;

  return 1; // any nonzero, non-read/write stype -> generate a normal packet
}

int TraceTrafficManager::PendingDestination(int source) const
{
  return _pending_valid[source] ? _pending_event[source].dst : 0;
}

int TraceTrafficManager::_GetNextPacketSize(int cl) const
{
  // _GeneratePacket() calls _IssuePacket(source, cl) and then
  // _GetNextPacketSize(cl) for the *same* source with nothing else run in
  // between (trafficmanager.cpp::_Inject() is a plain nested loop, no
  // reentrancy) -- so _last_issue_source is reliable here.
  // NEEDS TESTING: verify this with a 2-3 line trace and printed pids
  // before trusting it on a full run.
  if (_last_issue_source >= 0 && _pending_valid[_last_issue_source]) {
    return _pending_event[_last_issue_source].packet_size;
  }
  return TrafficManager::_GetNextPacketSize(cl); // fallback; shouldn't hit
}

void TraceTrafficManager::_OnPacketGenerated(int pid, int source, int cl,
                                              int time)
{
  if (_pending_valid[source]) {
    _pid_to_event[pid] = _pending_event[source];
    _pending_valid[source] = false;
  }
}

void TraceTrafficManager::_RetireFlit(Flit * f, int dest)
{
  if (f->tail && _packets_csv.is_open()) {
    std::map<int, TraceEvent>::iterator it = _pid_to_event.find(f->pid);
    if (it != _pid_to_event.end()) {
      TraceEvent const & ev = it->second;
      // f->atime is assigned by TrafficManager just before _RetireFlit()
      // is called (trafficmanager.cpp), so it's already valid here.
      int request_time   = (int) ev.timestamp;
      int injection_time = f->itime;
      int arrival_time   = f->atime;

      _packets_csv << f->pid << "," << ev.transaction_id << ","
                   << f->src << "," << dest << ","
                   << (ev.txn_type == 0 ? "READ" : ev.txn_type == 1 ? "WRITE" : "OTHER") << ","
                   << ev.packet_size << ","
                   << request_time << "," << injection_time << "," << arrival_time << ","
                   << (injection_time - request_time) << ","
                   << (arrival_time - injection_time) << ","
                   << (arrival_time - request_time) << ","
                   << f->hops << "\n";

      _pid_to_event.erase(it);
    }
  }

  // Preserve all of BookSim's normal latency/hop/pair-stat bookkeeping.
  TrafficManager::_RetireFlit(f, dest);
}

#include "tracetrafficmanager.hpp"

#include <algorithm>
#include <cassert>
#include <sstream>
#include <cstdlib>

TraceTrafficManager::TraceTrafficManager(Configuration const & config,
                                          vector<Network *> const & net)
  : TrafficManager(config, net)
{
  _trace_queue.resize(_nodes);

  // Swap out whatever TrafficManager's base constructor built from
  // `traffic = ...;` (protected member, so this is legal from here) for
  // our own pattern. This is the only thing that decides WHERE a packet
  // goes, and it's virtual, so no BookSim source patch is needed for it.
  for (int c = 0; c < _classes; ++c) {
    delete _traffic_pattern[c];
    _traffic_pattern[c] = new TraceFileTrafficPattern(_nodes);
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
  bool is_csv = true;  // decided by the first data line (see below)

  while (std::getline(in, line)) {
    ++line_no;
    if (line.empty() || line[0] == '#' || line[0] == '%') continue;

    if (first_line) {
      first_line = false;
      // Format sniff: a comma means the CSV dialect
      // (timestamp,src,dst,type,packet_size[,transaction_id], optional
      // header row); otherwise the veritx whitespace dialect
      // (cyc src cl dst sz, no header).
      if (line.find(',') == std::string::npos) {
        is_csv = false;
      } else {
        // Optional header row support: "timestamp,src,dst,..." - if the
        // first field isn't a number, treat the line as a header and skip it.
        std::string first_field = line.substr(0, line.find(','));
        if (first_field.find_first_not_of("0123456789") != std::string::npos) {
          continue;
        }
      }
    }

    TraceEvent ev;
    if (!is_csv) {
      // veritx text format: cyc src cl dst sz
      std::istringstream vss(line);
      int cl = 0;
      if (!(vss >> ev.timestamp >> ev.src >> cl >> ev.dst >> ev.packet_size)) {
        std::ostringstream err;
        err << "TraceTrafficManager: malformed trace line " << line_no
            << " (need cyc src cl dst sz): " << line;
        Error(err.str());
      }
      ev.cl = cl;
      ev.txn_type = 2;  // OTHER (metadata only)
      ev.transaction_id = (uint64_t) line_no;
    } else {
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

    ev.timestamp = strtoull(fields[0].c_str(), NULL, 10);
    ev.src       = atoi(fields[1].c_str());
    ev.dst       = atoi(fields[2].c_str());
    ev.txn_type  = (fields[3] == "WRITE") ? 1 : (fields[3] == "READ") ? 0 : 2;
    ev.packet_size = atoi(fields[4].c_str());
    ev.transaction_id = (fields.size() > 5)
                           ? strtoull(fields[5].c_str(), NULL, 10)
                           : (uint64_t) line_no;
    }

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

  // Stage the event on this class's own pattern object (see header note).
  // The slot necessarily belongs to the (source, class) pair _GeneratePacket
  // is about to consume: _Inject() calls _IssuePacket and _GeneratePacket
  // adjacently per (input, class) with nothing run in between.
  TraceFileTrafficPattern * pat =
      static_cast<TraceFileTrafficPattern*>(_traffic_pattern[cl]);
  pat->SetPending(ev);
  _trace_queue[source].pop_front();

  // Replicate the two side effects stock _IssuePacket() would have had.
  _packet_seq_no[source]++;
  _requestsOutstanding[source]++;

  return 1; // any nonzero, non-read/write stype -> generate a normal packet
}

int TraceTrafficManager::_GetNextPacketSize(int cl) const
{
  // Reads this class's own pattern object -- set by _IssuePacket() for the
  // same (source, class) immediately before _GeneratePacket() runs. No
  // source routing needed (that was the old _last_issue_source hack).
  TraceFileTrafficPattern const * pat =
      static_cast<TraceFileTrafficPattern const *>(_traffic_pattern[cl]);
  if (pat->HasPending()) {
    return pat->Pending().packet_size;
  }
  return TrafficManager::_GetNextPacketSize(cl); // fallback; shouldn't hit
}

void TraceTrafficManager::_OnPacketGenerated(int pid, int source, int cl,
                                              int time)
{
  (void)time;
  TraceFileTrafficPattern * pat =
      static_cast<TraceFileTrafficPattern*>(_traffic_pattern[cl]);
  if (pat->HasPending()) {
    // The pending slot must belong to the packet being generated -- fail
    // loudly on protocol misuse instead of misattributing sizes.
    assert(pat->Pending().src == source);
    _pid_to_event[pid] = pat->Pending();
    // Feed the shared honest-baseline map as well: base _RetireFlit scores
    // this packet as arrival - request_time (same value as the CSV above),
    // so both trace paths converge on one ruler with a single push site.
    _trace_reqtime[pid] = (int64_t)pat->Pending().timestamp;
    pat->ClearPending();
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

      // NOTE: no _all_latencies push here on purpose. The base-class retire
      // below records this packet once, baselined on _trace_reqtime (fed by
      // _OnPacketGenerated just above). Pushing here too would double-count
      // every packet and corrupt percentiles.
      _pid_to_event.erase(it);
    }
  }

  // Preserve all of BookSim's normal latency/hop/pair-stat bookkeeping.
  TrafficManager::_RetireFlit(f, dest);
}

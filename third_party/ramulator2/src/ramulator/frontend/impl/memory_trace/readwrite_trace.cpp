#include <filesystem>
#include <fmt/format.h>
#include <fstream>
#include <iostream>

#include "ramulator/base/param.h"
#include "ramulator/frontend/i_frontend.h"

namespace Ramulator {

namespace fs = std::filesystem;

class ReadWriteTrace : public IFrontEnd, public Implementation {
  RAMULATOR_REGISTER_IMPLEMENTATION(IFrontEnd, ReadWriteTrace, "ReadWriteTrace")

 private:
  struct Trace {
    bool is_write;
    AddrVec_t addr_vec;
    bool has_flat_addr;   // VeritX: extended 3-token form carries the
    Addr_t flat_addr;     // flat byte address (the coalescing/forwarding key)
  };
  std::vector<Trace> m_trace;

  size_t m_trace_length = 0;
  size_t m_curr_trace_idx = 0;
  size_t m_trace_count = 0;
  std::string m_trace_path;

  // VeritX: EOF is not completion. Independent monotonic lifecycle
  // counters — accepted increments when send() takes the request,
  // completed increments in the request completion callback. Monotonic
  // (never a single outstanding gauge) because a coalesced write can
  // invoke its callback synchronously inside send(), i.e. before the
  // matching accept is recorded — temporarily completed == accepted + 1,
  // reconciled by the time is_finished() is evaluated.
  size_t m_accepted_count = 0;
  size_t m_completed_count = 0;

  // VeritX: frontend stats (diagnostic gauges, registered by reference).
  size_t s_trace_requests = 0;
  size_t s_accepted_requests = 0;
  size_t s_completed_requests = 0;
  size_t s_outstanding_requests = 0;

 public:
  void init() override {
    RAMULATOR_PARSE_PARAM(m_clock_ratio, unsigned int, "clock_ratio").required();
    RAMULATOR_PARSE_PARAM(m_trace_path, std::string, "path").required();

    m_logger.info(fmt::format("Loading trace file {} ...", m_trace_path));
    init_trace(m_trace_path);
    m_logger.info(fmt::format("Loaded {} lines.", m_trace.size()));

    // VeritX: lifecycle accounting + drain-aware completion (see tick(),
    // is_finished()). Stats registered here by member reference.
    s_trace_requests = m_trace_length;
    m_stats.add("trace_requests", s_trace_requests);
    m_stats.add("accepted_requests", s_accepted_requests);
    m_stats.add("completed_requests", s_completed_requests);
    m_stats.add("outstanding_requests", s_outstanding_requests);
  };

  void tick() override {
    // VeritX: empty input finishes immediately (the old code dereferenced
    // m_trace[0] unconditionally); a fully injected trace stops injecting
    // but keeps returning so the run loop keeps ticking the memory system
    // until the accepted requests drain via their callbacks.
    if (m_trace_length == 0 || m_trace_count >= m_trace_length) {
      return;
    }
    const Trace& t = m_trace[m_curr_trace_idx];
    Request req(t.addr_vec, t.is_write ? Request::Type::Write : Request::Type::Read);
    req.size_bytes = m_memory_system->get_tx_bytes();
    // VeritX (req.addr correctness, 2026-09-18): the addr-vector Request
    // constructor leaves req.addr == -1, and ControllerBase keys write
    // coalescing / read forwarding on req.addr — every request aliased to
    // one key, so a buffered write to bank0/row7 could coalesce an
    // unrelated write to bank3/row54. VeriX traces carry the flat byte
    // address explicitly (3-token form); legacy 2-token traces get a
    // unique per-line negative sentinel: no real address collides with a
    // sentinel and sentinels never collide with each other, so legacy
    // traces conservatively NEVER coalesce/forward (the aliased behavior
    // they previously got was wrong, not a feature).
    req.addr = t.has_flat_addr ? t.flat_addr : static_cast<Addr_t>(-(static_cast<long long>(m_curr_trace_idx) + 1));
    // VeritX: completion callback — the controller invokes it when the
    // request reaches its terminal state (reads: after modeled latency;
    // writes: at the terminal command; coalesced writes: synchronously
    // inside send(), hence the monotonic counters above).
    req.callback = [this](Request&) {
      ++m_completed_count;
      ++s_completed_requests;
    };
    bool sent = m_memory_system->send(req);
    if (sent) {
      ++m_accepted_count;
      ++s_accepted_requests;
      // VeritX (outstanding gauge, 2026-09-18): DERIVED from the monotonic
      // truth at the one point where completed <= accepted is guaranteed
      // (a coalesced write's callback fires inside send(), before the
      // accept increment below — mutating the gauge there wrapped the
      // size_t through 2^64). The gauge is only read at finalize.
      s_outstanding_requests = m_accepted_count - m_completed_count;
      m_curr_trace_idx = (m_curr_trace_idx + 1) % m_trace_length;
      m_trace_count++;
    }
    // VeritX: send() == false is backpressure — the index does not
    // advance, so the same record retries on a later tick (unchanged
    // upstream behavior, preserved by the early return above).
  };

 private:
  // Trace format (VeritX): one memory access per line, space-separated.
  //   VeriX extended form:  <op> <flat_byte_addr> <addr_vec>   (3 tokens)
  //   upstream legacy form: <op> <addr_vec>                    (2 tokens)
  //
  // - op:       R (read) or W (write)
  // - flat:     flat byte address of the transaction — the equality key
  //             the controller uses for write coalescing / read forwarding
  //             (flat = tx_index * transaction_bytes from the lowerer)
  // - addr_vec: comma-separated integers forming a multi-dimensional address
  //             vector (e.g., channel,rank,bankgroup,bank,row,column)
  //
  // Examples:
  //   R 4096 0,1,2,100,32
  //   W 4160 0,0,3,200,16
  //
  // Legacy 2-token lines are accepted for upstream compatibility; their
  // coalescing key is a unique per-line sentinel (see tick()), i.e. they
  // conservatively never coalesce or forward. Single pass (no cyclic
  // replay): after the last record is accepted, tick() stops injecting
  // and is_finished() additionally requires every accepted request to
  // have completed via its callback (VeritX drain semantics — EOF alone
  // is not completion).
  void init_trace(const std::string& file_path_str) {
    fs::path trace_path(file_path_str);
    if (!fs::exists(trace_path)) {
      throw std::runtime_error(fmt::format("Trace {} does not exist!", file_path_str));
    }

    std::ifstream trace_file(trace_path);
    if (!trace_file.is_open()) {
      throw std::runtime_error(fmt::format("Trace {} cannot be opened!", file_path_str));
    }

    std::string line;
    int line_num = 0;
    while (std::getline(trace_file, line)) {
      line_num++;
      std::vector<std::string> tokens;
      tokenize(tokens, line, " ");

      if (tokens.size() != 2 && tokens.size() != 3) {
        throw std::runtime_error(
            fmt::format("Trace {} line {}: expected 2 or 3 tokens, got {}", file_path_str, line_num, tokens.size()));
      }

      bool is_write = false;
      if (tokens[0] == "R") {
        is_write = false;
      } else if (tokens[0] == "W") {
        is_write = true;
      } else {
        throw std::runtime_error(
            fmt::format("Trace {} line {}: unknown type '{}' (expected R or W)", file_path_str, line_num, tokens[0]));
      }

      // VeritX: 3-token form = <op> <flat_byte_addr> <addr_vec>.
      const bool has_flat = (tokens.size() == 3);
      const size_t vec_tok = has_flat ? 2 : 1;
      Addr_t flat_addr = -1;
      if (has_flat) {
        try {
          flat_addr = static_cast<Addr_t>(std::stoll(tokens[1]));
        } catch (const std::exception&) {
          throw std::runtime_error(
              fmt::format("Trace {} line {}: flat address '{}' is not an integer", file_path_str, line_num, tokens[1]));
        }
        if (flat_addr < 0) {
          throw std::runtime_error(
              fmt::format("Trace {} line {}: flat address must be >= 0", file_path_str, line_num));
        }
      }

      std::vector<std::string> addr_vec_tokens;
      tokenize(addr_vec_tokens, tokens[vec_tok], ",");

      AddrVec_t addr_vec;
      for (const auto& token : addr_vec_tokens) {
        addr_vec.push_back(static_cast<int>(std::stoll(token)));
      }

      m_trace.push_back({is_write, addr_vec, has_flat, flat_addr});
    }

    trace_file.close();

    m_trace_length = m_trace.size();
  };

  bool is_finished() override {
    // VeritX: DONE = input fully accepted AND every accepted request
    // completed (not merely consumed). An empty trace is trivially done.
    if (m_trace_length == 0) {
      return true;
    }
    return m_trace_count >= m_trace_length &&
           m_completed_count == m_accepted_count;
  };
};

}  // namespace Ramulator
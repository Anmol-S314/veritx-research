#pragma once

// Minimal callback tracker mirroring the analytical backend's semantics:
// sim_send/sim_recv register callbacks on a shared entry keyed by
// (tag, src, dst, count, chunk_id); the entry fires when the transmission
// completes. Self-contained (no dependency on the analytical backend).

#include <functional>
#include <map>
#include <tuple>

namespace VeritX {

using Callback = void (*)(void *);

class TrackerEntry {
 public:
  TrackerEntry() : _send(NULL), _recv(NULL), _finished(false) {}

  void register_send_callback(Callback cb, void * arg) {
    _send = cb;
    _send_arg = arg;
  }
  void register_recv_callback(Callback cb, void * arg) {
    _recv = cb;
    _recv_arg = arg;
  }
  bool is_transmission_finished() const { return _finished; }
  void set_transmission_finished() { _finished = true; }
  bool both_callbacks_registered() const { return _send != NULL && _recv != NULL; }
  bool has_send_callback() const { return _send != NULL; }

  void invoke_send_handler() {
    if (_send) _send(_send_arg);
  }
  void invoke_recv_handler() {
    if (_recv) _recv(_recv_arg);
  }

 private:
  Callback _send;
  void * _send_arg;
  Callback _recv;
  void * _recv_arg;
  bool _finished;
};

// Unique chunk id per (tag, src, dst, count) CALL: the nth send and the nth
// recv of the same key share an id (mirrors the analytical ChunkIdGenerator).
class ChunkIdGenerator {
 public:
  using Key = std::tuple<int, int, int, uint64_t>;

  int create_send_chunk_id(int tag, int src, int dst, uint64_t count) {
    Entry & e = _entries[std::make_tuple(tag, src, dst, count)];
    return e.send_id++;
  }
  int create_recv_chunk_id(int tag, int src, int dst, uint64_t count) {
    Entry & e = _entries[std::make_tuple(tag, src, dst, count)];
    return e.recv_id++;
  }

 private:
  struct Entry {
    int send_id = 0;
    int recv_id = 0;
  };
  std::map<Key, Entry> _entries;
};

class CallbackTracker {
 public:
  using EntryKey = std::tuple<int, int, int, uint64_t, int>;  // tag,src,dst,count,chunk_id

  TrackerEntry * search_entry(int tag, int src, int dst, uint64_t count,
                              int chunk_id) {
    auto it = _entries.find(_key(tag, src, dst, count, chunk_id));
    return it == _entries.end() ? NULL : &it->second;
  }

  TrackerEntry * create_new_entry(int tag, int src, int dst, uint64_t count,
                                  int chunk_id) {
    return &(_entries.emplace(_key(tag, src, dst, count, chunk_id),
                              TrackerEntry())
                 .first->second);
  }

  void pop_entry(int tag, int src, int dst, uint64_t count, int chunk_id) {
    _entries.erase(_key(tag, src, dst, count, chunk_id));
  }

 private:
  static EntryKey _key(int tag, int src, int dst, uint64_t count, int chunk_id) {
    return std::make_tuple(tag, src, dst, count, chunk_id);
  }

  std::map<EntryKey, TrackerEntry> _entries;
};

}  // namespace VeritX

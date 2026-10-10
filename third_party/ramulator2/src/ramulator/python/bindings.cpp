#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>

#include <cmath>
#include <memory>
#include <sstream>
#include <stdexcept>

#include "ramulator/base/factory.h"
#include "ramulator/frontend/i_frontend.h"
#include "ramulator/memory_system/i_memory_system.h"
#include "ramulator/base/request.h"
#include "ramulator/python/binding_utils.h"

// ---- Simulation wrapper ----

class Simulation {
  std::unique_ptr<IFrontEnd> m_frontend;
  std::unique_ptr<IMemorySystem> m_memory_system;
  bool m_finalized = false;
  uint64_t m_memory_ticks = 0;

  void update_stats() {
    m_frontend->update_stats_recursive();
    m_memory_system->update_stats_recursive();
  }

 public:
  explicit Simulation(nb::dict config) {
    ConfigNode cfg = py_to_confignode(config);

    m_frontend.reset(Factory::create_frontend(cfg));
    m_memory_system.reset(Factory::create_memory_system(cfg));

    m_frontend->connect_memory_system(m_memory_system.get());
    m_memory_system->connect_frontend(m_frontend.get());
  }

  Simulation(const Simulation&) = delete;
  Simulation& operator=(const Simulation&) = delete;

  ~Simulation() noexcept {
    try {
      finalize();
    } catch (...) {
    }
  }

  bool send(uint64_t addr, int type, int size_bytes, int source_id,
            int ingress_id, nb::callable callback) {
    if (m_finalized) throw std::runtime_error("simulation is finalized");
    if (type != Ramulator::Request::Type::Read &&
        type != Ramulator::Request::Type::Write)
      throw std::invalid_argument("request type must be Read=0 or Write=1");
    if (size_bytes <= 0 || size_bytes > m_memory_system->get_tx_bytes())
      throw std::invalid_argument("request size must fit one native transaction");
    if (source_id < 0 || ingress_id < 0)
      throw std::invalid_argument("source and ingress ids must be nonnegative");
    Ramulator::Request request(static_cast<Ramulator::Addr_t>(addr), type);
    request.size_bytes = size_bytes;
    request.source_id = source_id;
    request.ingress_id = ingress_id;
    request.callback = [callback = nb::object(callback)](Ramulator::Request& done) {
      nb::gil_scoped_acquire acquire;
      callback(static_cast<uint64_t>(done.addr), done.type_id, done.size_bytes);
    };
    return m_memory_system->send(request);
  }

  void tick() {
    if (m_finalized) throw std::runtime_error("simulation is finalized");
    m_memory_system->tick();
    ++m_memory_ticks;
  }

  uint64_t memory_ticks() const { return m_memory_ticks; }

  int64_t tCK_ps() const {
    float const tck_ns = m_memory_system->get_tCK();
    if (!std::isfinite(tck_ns) || tck_ns <= 0)
      throw std::runtime_error("memory system has no valid tCK");
    double const ps = static_cast<double>(tck_ns) * 1000.0;
    int64_t const rounded = static_cast<int64_t>(std::llround(ps));
    if (std::abs(ps - static_cast<double>(rounded)) > 0.0001)
      throw std::runtime_error("native tCK is not representable as integer ps");
    return rounded;
  }

  int tx_bytes() const { return m_memory_system->get_tx_bytes(); }

  void run() {
    int fe_tick = m_frontend->get_clock_ratio();
    int mem_tick = m_memory_system->get_clock_ratio();
    if (fe_tick <= 0 || mem_tick <= 0) {
      throw std::runtime_error("clock_ratio must be > 0 for both frontend and memory system");
    }

    int fe_count = mem_tick - 1, mem_count = fe_tick - 1;
    for (;;) {
      if (++fe_count >= mem_tick) {
        fe_count = 0;
        m_frontend->tick();
      }

      if (m_frontend->is_finished()) {
        break;
      }

      if (++mem_count >= fe_tick) {
        mem_count = 0;
        m_memory_system->tick();
      }
    }
  }

  void finalize() {
    if (m_finalized) {
      return;
    }
    m_frontend->finalize();
    m_memory_system->finalize();
    m_finalized = true;
  }

  nb::dict get_stats() {
    update_stats();
    ConfigNode::Map root;
    root["frontend"] = m_frontend->collect_stats();
    root["memory_system"] = m_memory_system->collect_stats();

    return nb::cast<nb::dict>(confignode_to_py(ConfigNode(std::move(root))));
  }

  std::string get_stats_yaml() {
    update_stats();
    std::ostringstream ss;
    m_frontend->print_stats(ss);
    m_memory_system->print_stats(ss);
    return ss.str();
  }
};

// ---- nanobind module ----

NB_MODULE(_ramulator, m) {
  m.doc() = "Ramulator2 Python bindings";

  nb::class_<Simulation>(m, "Simulation")
      .def(nb::init<nb::dict>(), nb::arg("config"), "Create a simulation from a configuration dict.")
      .def("run", &Simulation::run, "Run the simulation to completion.")
      .def("send", &Simulation::send, nb::arg("addr"), nb::arg("type"),
           nb::arg("size_bytes"), nb::arg("source_id"), nb::arg("ingress_id"),
           nb::arg("callback"), "Submit one native request; false means retryable backpressure.")
      .def("tick", &Simulation::tick, "Advance the memory system by one native cycle.")
      .def_prop_ro("memory_ticks", &Simulation::memory_ticks)
      .def_prop_ro("tCK_ps", &Simulation::tCK_ps)
      .def_prop_ro("tx_bytes", &Simulation::tx_bytes)
      .def("finalize", &Simulation::finalize, "Finalize the simulation and flush final outputs.")
      .def("get_stats", &Simulation::get_stats, "Update derived stats and return them as a dict.")
      .def("get_stats_yaml", &Simulation::get_stats_yaml, "Update derived stats and return them as a YAML string.");
}

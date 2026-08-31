/******************************************************************************
VeritX — BookSim2 fabric wrapper implementation (see Booksim2Fabric.hh).
*******************************************************************************/

#include "Booksim2Fabric.hh"

#include <iostream>
#include <sstream>

namespace VeritX {

BookSim2Fabric::BookSim2Fabric(std::string const & cfg_file,
                               std::vector<std::string> const & overrides,
                               double ns_per_cycle, int flit_bytes)
    : _tm(NULL), _ns_per_cycle(ns_per_cycle), _flit_bytes(flit_bytes) {
  _tm = VeritXEmbed::CreateEmbeddedTM(cfg_file, overrides);
  if (_tm == NULL) {
    std::cerr << "Booksim2Fabric: CreateEmbeddedTM failed for '" << cfg_file
              << "'" << std::endl;
    exit(1);
  }
}

BookSim2Fabric::~BookSim2Fabric() {
  if (_tm) {
    VeritXEmbed::EmbedTM * tm = _tm;
    _tm = NULL;
    delete tm;
  }
}

}  // namespace VeritX

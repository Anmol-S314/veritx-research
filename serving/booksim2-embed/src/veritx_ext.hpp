#ifndef _VERITX_EXT_HPP_
#define _VERITX_EXT_HPP_

#include <string>
#include <vector>

#include "traffic.hpp"
#include "config_utils.hpp"

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

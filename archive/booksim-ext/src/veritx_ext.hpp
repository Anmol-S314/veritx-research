#ifndef _VERITX_EXT_HPP_
#define _VERITX_EXT_HPP_

#include <string>
#include <vector>

#include "traffic.hpp"
#include "config_utils.hpp"

// VeritX extension registry.
//
// `veritx_hooks.patch` wires Booksim's two factories into the functions below.
// That patch is written once and never touched again -- to add a traffic
// pattern or routing function you edit veritx_ext.cpp, NOT the patch.

// Called from TrafficPattern::New() when Booksim doesn't recognise a pattern.
// Return NULL for a name you don't own; Booksim then reports it as unknown.
TrafficPattern * VeritXNewTraffic(std::string const & name,
                                  std::vector<std::string> const & params,
                                  int nodes,
                                  Configuration const * const config);

// Called at the end of InitializeRoutingMap(), after Booksim's own entries.
void VeritXRegisterRouting();

#endif

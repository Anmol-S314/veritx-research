#include "veritx_ext.hpp"
#include "routefunc.hpp"

#include "matrixtraffic.hpp"
#include "yxroute.hpp"
#include "snakeroute.hpp"

// ===========================================================================
//  TRAFFIC PATTERNS  --  add a branch, return NULL for anything not yours.
//  Selected in a .cfg with:  traffic = <name>(<args>);
// ===========================================================================
TrafficPattern * VeritXNewTraffic(std::string const & name,
                                  std::vector<std::string> const & params,
                                  int nodes,
                                  Configuration const * const config)
{
  if (name == "matrix") {
    if (params.empty()) {
      cout << "Error: matrix traffic pattern requires a filename: matrix(<file>)" << endl;
      exit(-1);
    }
    return new MatrixTrafficPattern(nodes, params[0]);
  }

  // >>> ADD YOUR TRAFFIC PATTERN HERE <<<

  return NULL; // not ours -> Booksim reports "Unknown traffic pattern"
}

// ===========================================================================
//  ROUTING FUNCTIONS  --  one line each.
//  Booksim appends the topology name, so key "yx_mesh" is selected in a .cfg
//  with `routing_function = yx;` on a mesh. Get this wrong and it looks up
//  "yx_mesh_mesh" and aborts with "Invalid routing function".
// ===========================================================================
void VeritXRegisterRouting()
{
  gRoutingFunctionMap["yx_mesh"] = &yx_mesh;
  gRoutingFunctionMap["snake_mesh"] = &snake_mesh;   // Hamiltonian broadcast (prefix multicast)

  // >>> ADD YOUR ROUTING FUNCTION HERE <<<
}

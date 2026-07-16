#include <fstream>
#include <sstream>
#include <iostream>
#include <cstdlib>
#include <cassert>
#include "random_utils.hpp"
#include "matrixtraffic.hpp"

using namespace std;

MatrixTrafficPattern::MatrixTrafficPattern(int nodes, string const & filename)
  : TrafficPattern(nodes)
{
  ifstream in(filename.c_str());
  if(!in) {
    cout << "Error: cannot open traffic matrix file: " << filename << endl;
    exit(-1);
  }

  vector<double> vals;
  string line;
  while(getline(in, line)) {
    size_t h = line.find('#');
    if(h != string::npos) line = line.substr(0, h);
    istringstream ss(line);
    double v;
    while(ss >> v) {
      if(v < 0.0) {
        cout << "Error: negative entry in traffic matrix " << filename << endl;
        exit(-1);
      }
      vals.push_back(v);
    }
  }

  if((int)vals.size() != nodes * nodes) {
    cout << "Error: traffic matrix " << filename << " has " << vals.size()
         << " entries, expected " << nodes << "x" << nodes << " = "
         << nodes * nodes << " (must match topology node count)." << endl;
    exit(-1);
  }

  _matrix.assign(nodes, vector<double>(nodes, 0.0));
  _row_total.assign(nodes, 0.0);
  for(int s = 0; s < nodes; ++s) {
    for(int d = 0; d < nodes; ++d) {
      double v = vals[s * nodes + d];
      _matrix[s][d] = v;
      _row_total[s] += v;
    }
  }
}

int MatrixTrafficPattern::dest(int source)
{
  assert((source >= 0) && (source < _nodes));

  // A source with no outgoing traffic still injects at the global rate; send it
  // to itself (zero-hop, effectively idle). ponytail: per-node injection rates
  // would drop these entirely; add that if an all-zero row ever skews results.
  if(_row_total[source] <= 0.0) {
    return source;
  }

  double r = RandomFloat(_row_total[source]);
  double acc = 0.0;
  for(int d = 0; d < _nodes; ++d) {
    acc += _matrix[source][d];
    if(r < acc) return d;
  }
  return _nodes - 1;  // floating-point rounding fallback
}

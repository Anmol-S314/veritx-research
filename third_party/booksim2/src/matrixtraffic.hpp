#ifndef _MATRIXTRAFFIC_HPP_
#define _MATRIXTRAFFIC_HPP_

#include <string>
#include <vector>
#include "traffic.hpp"

// Traffic driven by an N x N matrix loaded from a file: each packet's dest is
// sampled from row `source`, weighted by the entries (e.g. bytes tile s -> d).
// This is the Booksim side of the Timeloop -> Booksim bridge (tracks/t3-topology).
// File: N*N non-negative numbers, row-major (row=source, col=dest); '#' comments ok.
class MatrixTrafficPattern : public TrafficPattern {
  std::vector<std::vector<double> > _matrix;
  std::vector<double> _row_total;
public:
  MatrixTrafficPattern(int nodes, std::string const & filename);
  virtual int dest(int source);
};

#endif

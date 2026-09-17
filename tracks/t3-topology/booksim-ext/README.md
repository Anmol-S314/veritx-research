# booksim-ext/ — LANDED, do not re-apply

`matrix_traffic.patch` + `matrixtraffic.{cpp,hpp}` added matrix-traffic
support to BookSim. That change already lives in the vendored tree:

- `third_party/booksim2/src/traffic.cpp` (`#include "matrixtraffic.hpp"`,
  matrix-traffic branches)
- `third_party/booksim2/src/matrixtraffic.{cpp,hpp}`

This directory is kept as provenance (what the patch was, for review
history). Re-applying `matrix_traffic.patch` onto the vendored tree will
conflict/fail — that is expected, not a bug.

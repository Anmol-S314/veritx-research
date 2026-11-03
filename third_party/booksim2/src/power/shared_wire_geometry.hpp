#ifndef VERITX_SHARED_WIRE_GEOMETRY_HPP
#define VERITX_SHARED_WIRE_GEOMETRY_HPP

#include <cmath>
#include <set>
#include <stdexcept>
#include <vector>

namespace native_power {

// Full trunk, including both branches when the driver lies between taps.
// Adjacent coordinates partition one shared wire; they are not private links.
inline std::vector<double> SharedWireSegments(int side, int source,
    const std::vector<int>& taps, double pitch_mm) {
  if (side < 2 || side > 46340 || source < 0 || source >= side * side
      || taps.empty() || !std::isfinite(pitch_mm) || pitch_mm <= 0)
    throw std::invalid_argument("Invalid shared-wire grid, source or pitch");
  const int sx = source % side, sy = source / side;
  bool row = true, column = true;
  std::set<int> unique;
  for (int tap : taps) {
    if (tap < 0 || tap >= side * side || tap == source || !unique.insert(tap).second)
      throw std::invalid_argument("Invalid or duplicate shared-wire tap");
    row = row && tap / side == sy;
    column = column && tap % side == sx;
  }
  if (!row && !column)
    throw std::invalid_argument("Shared-wire taps are not collinear with driver");
  std::set<int> positions;
  positions.insert(row ? sx : sy);
  for (int tap : taps) positions.insert(row ? tap % side : tap / side);
  std::vector<double> segments;
  int previous = *positions.begin();
  for (auto it = ++positions.begin(); it != positions.end(); ++it) {
    segments.push_back((*it - previous) * pitch_mm);
    previous = *it;
  }
  return segments;
}

}  // namespace native_power
#endif

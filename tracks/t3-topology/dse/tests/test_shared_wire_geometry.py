"""Exercise the same C++ geometry helper used by the native power pass."""
from pathlib import Path
import subprocess

import pytest

REPO = Path(__file__).resolve().parents[4]


@pytest.fixture(scope='module')
def geometry_binary(tmp_path_factory):
    root = tmp_path_factory.mktemp('shared-wire-geometry')
    source = root / 'check.cpp'
    source.write_text('''#include "power/shared_wire_geometry.hpp"
#include <iostream>
#include <cstdlib>
int main(int argc, char** argv) {
  try {
    std::vector<int> taps;
    for (int i=4; i<argc; ++i) taps.push_back(std::atoi(argv[i]));
    std::vector<double> lengths = native_power::SharedWireSegments(
      std::atoi(argv[1]), std::atoi(argv[2]), taps, std::atof(argv[3]));
    for (double length : lengths) std::cout << length << " ";
    return 0;
  } catch (const std::exception& e) { std::cerr << e.what(); return 2; }
}''')
    binary = root / 'check'
    subprocess.run(['g++', '-std=c++11', '-I' + str(REPO / 'third_party/booksim2/src'),
                    str(source), '-o', str(binary)], check=True, capture_output=True, text=True)
    return binary


def run(binary, side, source, pitch, taps):
    return subprocess.run([str(binary), str(side), str(source), str(pitch), *map(str, taps)],
                          capture_output=True, text=True)


@pytest.mark.parametrize('source,taps,segments', [
    (0, [1, 2, 3], [2, 2, 2]),
    (1, [0, 2, 3], [2, 2, 2]),  # two branches: union span, not farthest distance
    (0, [3, 1], [2, 4]),       # no duplicate trunk per receiver
    (0, [4, 12], [2, 4]),      # vertical
    (3, [0, 1, 2], [2, 2, 2]),
])
def test_actual_grid_segments(geometry_binary, source, taps, segments):
    result = run(geometry_binary, 4, source, 2, taps)
    assert result.returncode == 0, result.stderr
    assert list(map(float, result.stdout.split())) == segments


def test_pitch_changes_only_lengths(geometry_binary):
    result = run(geometry_binary, 4, 1, .5, [0, 2, 3])
    assert list(map(float, result.stdout.split())) == [.5, .5, .5]


@pytest.mark.parametrize('side,source,pitch,taps', [
    (4, 0, 2, [5]), (4, 0, 2, [1, 4]), (4, 0, 2, [1, 1]),
    (4, 0, 2, [0]), (4, 16, 2, [1]), (4, 0, 2, [16]),
    (4, 0, 2, []), (1, 0, 2, [1]), (4, 0, 0, [1]),
    (4, 0, -1, [1]), (4, 0, 'nan', [1]), (4, 0, 'inf', [1]),
])
def test_unsupported_geometry_refuses(geometry_binary, side, source, pitch, taps):
    assert run(geometry_binary, side, source, pitch, taps).returncode != 0

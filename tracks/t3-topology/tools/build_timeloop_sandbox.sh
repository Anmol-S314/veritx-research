#!/usr/bin/env bash
# Build the preexisting vendored Timeloop without modifying the checkout.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  printf 'Usage: bash %s NEW_BUILD_DIRECTORY\n' "$0" >&2
  exit 2
fi
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
for tool in scons g++ python3; do
  command -v "$tool" >/dev/null || { printf 'Missing prerequisite: %s\n' "$tool" >&2; exit 2; }
done
# mkdir without -p deliberately refuses an existing build directory.
mkdir -- "$1"
build=$(cd "$1" && pwd)
cp -a "$root/third_party/timeloop/." "$build/"
python3 - "$build" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
changes = [
    ('include/loop-analysis/point.hpp', '#include <vector>', '#include <cstdint>\n#include <vector>'),
    ('src/compound-config/compound-config.cpp',
     'for (const std::string& m: LNode->lookup(name))',
     'for (const std::string m: LNode->lookup(name))'),
    ('src/compound-config/compound-config.cpp',
     'for (const std::string& m: *LNode)', 'for (const std::string m: *LNode)'),
]
evidence = []
for relative, before, after in changes:
    path = root / relative
    text = path.read_text()
    if text.count(before) != 1:
        raise SystemExit(f'Refusing unexpected vendored source: {relative}')
    original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    path.write_text(text.replace(before, after))
    evidence.append({'file': relative, 'before': before, 'after': after,
                     'input_sha256': original_hash,
                     'output_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
(root / 'srota-build-patches.json').write_text(json.dumps(evidence, indent=2) + '\n')
PY
cd "$build"
scons -j2 >build.log 2>&1 || { tail -60 build.log >&2; exit 1; }
printf 'Timeloop built in %s\nBinary: %s/build/timeloop-mapper\n' "$build" "$build"
printf 'LD_LIBRARY_PATH=%s/lib\nPatch record: %s/srota-build-patches.json\n' "$build" "$build"

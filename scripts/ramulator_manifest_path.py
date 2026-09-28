#!/usr/bin/env python3
"""Print the repo-relative Ramulator manifest path when it exists.

The extension filename is interpreter-tagged, so no Makefile may
hardcode a CPython suffix: this helper asks the same discovery
authority the release build used. Prints nothing and exits 1 when the
extension (or its manifest) is absent.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tracks" / "t3-topology" / "dse"))

from veritx_dse.core.build_manifest import manifest_path_for  # noqa: E402
from veritx_dse.simulation.ramulator import discover  # noqa: E402


def main() -> int:
    try:
        backend = discover()
    except Exception:  # noqa: BLE001
        return 1
    if not backend.ready:
        return 1
    manifest = manifest_path_for(backend.ext_path)
    if not manifest.is_file():
        return 1
    print(manifest.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

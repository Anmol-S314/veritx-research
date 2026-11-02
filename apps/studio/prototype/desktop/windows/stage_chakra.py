"""Build real Python protobuf bindings the frozen gateway can import as `chakra`.

Chakra is normally pip-installed with optional ML extras. The gateway only needs
the generated protobuf schema (and its small protolib helper), so those files are
copied into a namespace package instead of installing an unrelated ML stack.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
VENDOR = REPO / "third_party/astra-sim/extern/graph_frontend/chakra"
TARGET = REPO / "apps/studio/prototype/.desktop-build/windows/chakra/chakra"
SOURCES = {
    "schema/protobuf": ["et_def_pb2.py", "et_def_pb2.pyi"],
    "src/third_party/utils": ["protolib.py"],
}


def main() -> int:
    if TARGET.exists():
        shutil.rmtree(TARGET)
    for relative, names in SOURCES.items():
        destination = TARGET / relative
        destination.mkdir(parents=True, exist_ok=True)
        for name in names:
            source = VENDOR / relative / name
            if not source.is_file():
                raise SystemExit(f"missing vendored Chakra source: {source}")
            shutil.copy2(source, destination / name)
    (TARGET / "__init__.py").write_text(
        '"""Chakra protobuf schema bundled for the Srota desktop gateway."""\n')
    for relative in SOURCES:
        parts = Path(relative).parts
        for index in range(1, len(parts) + 1):
            init = TARGET.joinpath(*parts[:index]) / "__init__.py"
            init.parent.mkdir(parents=True, exist_ok=True)
            init.touch()
    print(TARGET.parent)
    return 0


if __name__ == "__main__":
    sys.exit(main())

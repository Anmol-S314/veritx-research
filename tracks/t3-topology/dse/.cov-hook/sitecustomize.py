"""Coverage process-startup hook (subprocess measurement for the test suite).

`coverage run -m pytest` cannot see code that runs in *subprocesses* — and a
large share of this suite exercises the CLI through `python -m veritx_dse.cli
...`. To include them, coverage's documented recipe is COVERAGE_PROCESS_START
plus a module that calls `coverage.process_startup()` at interpreter startup.

This file is that module, kept OUT of the import path by default so normal
runs are untouched. `tests/conftest.py` copies it to `<tmpdir>/sitecustomize.py`
and prepends that dir to PYTHONPATH for spawned CLI processes whenever the
parent pytest run is itself under measurement (COVERAGE_PROCESS_START set).
The copy shadows the system sitecustomize only inside those measured
subprocesses; without COVERAGE_PROCESS_START it is a strict no-op.
"""
import os

if os.environ.get("COVERAGE_PROCESS_START"):
    try:
        import coverage
        coverage.process_startup()
    except Exception:  # never break the measured program
        pass

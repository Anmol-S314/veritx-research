# `_root` — extracted module rationale

Extracted from the module docstrings of `veritx_dse/{name}` by the 2026-09-29 debloat. Code keeps a one-line pointer; this is the original long-form text.

## `tracks/t3-topology/dse/veritx_dse/__init__.py`

```text
veritx_dse — AI-Noc Design Space Exploration toolkit.

This package re-exports all public APIs for backward compatibility.
New code should import from subpackages directly:
    from veritx_dse.model import CompileRequest
    from veritx_dse.simulation import run_booksim
```

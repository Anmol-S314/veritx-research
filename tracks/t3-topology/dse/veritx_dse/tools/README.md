# veritx_dse.tools — historical one-off scripts

These are **not** part of the supported CLI surface. They are one-shot
milestone/analysis scripts folded into the package on 2026-09-16 (formerly
`dse/scripts/`) so the package is the single Python seam.

| Script | Purpose | Invoked by |
|---|---|---|
| `chakra_to_dse.py` | Chakra ET → DSE trace converter | `veritx trace-chakra` (cli.py) |
| `deadlock_routing.py` | anynet parse + deadlock diagnostics | `veritx` deadlock cmds (cli.py, subprocess) |
| `flow_certifier.py` | Flow-class certification engine (ex-`milestone_c.py`) | `veritx` certify cmds (cli.py, subprocess) |
| `multi_workload_pareto.py` | Pareto replay across workloads | `veritx` mwp cmds (cli.py, `eval_once` import) |
| `memory_miss_model.py` | Memory miss-model one-off | manual (historical) |
| `_cov_sitecustomize.py` | coverage plumbing | moved to `dse/tests/` |

Notes:
- `scripts/log.py` (duplicate logging seam) was **deleted**; the one logging
  seam is `veritx_dse.core.logging`. Nothing imported it except
  `flow_certifier.py` (ex-`milestone_c.py`), which never called it.
- Path math in `flow_certifier.py` was updated for the new depth
  (`parent.parent.parent.parent` for track-level `scripts/rtlgen`).
- Don't add new scripts here — new functionality goes in the proper
  subpackage (`simulation/`, `synthesis/`, ...) behind the CLI.

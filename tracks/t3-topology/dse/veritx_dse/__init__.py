"""veritx_dse — VeritX Design Space Exploration engine.

Modules:
- cli:            Thin CLI dispatch layer (arg parsing only)
- logging:        Structured logging with Ctx, verbosity, JSON output
- presets:        Topology dataclass + SWEEP_TOPOS + DENSE_PRESETS + WORKLOAD_PRESETS
- booksim:        BookSim2 config generation, execution, result parsing
- traces:         Trace validation, analysis, extraction, conversion
- pipeline:       High-level orchestration (run/compare/sweep/diff/report)
- compile_model:  PRD §11 — E1-E5 data model, guardrails, VC derivation
- reports:        PRD §7 — area/power/timing reports
- artifact:       PRD §12 — artifact signing and design manifests
- commands_trace: CLI commands for trace info/validate/extract/model/chakra
- uvm_gen:        UVM testbench generation from CompileRequest
- config:         BookSim config generation from Topology
- constants:      Centralized magic numbers
- errors:         Structured error hierarchy
- recovery:       Atomic writes and temp directory management
- paths:          Single-source path resolution for all tools
"""

__version__ = "0.3.0"

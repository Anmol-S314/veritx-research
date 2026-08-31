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
- evaluator:      BookSim simulation runner with caching (legacy)
- bo_synthesizer: Bayesian optimization topology synthesis
- traffic_model:  Unified phase-aware traffic model
- milestone_b/c/d: Synthesis, certification, ASTRA-sim validation
"""

__version__ = "0.3.0"

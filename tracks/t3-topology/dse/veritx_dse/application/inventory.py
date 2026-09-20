"""veritx_dse.application.inventory — Wave-C migration ledger (Phase 1/30).

One row per known execution surface: where it lives, what it does,
its classification, and its Wave-C replacement. AUTHORITATIVE rows are
the only product-certified paths. LEGACY_INTERNAL rows keep working
for historical research flows but are not reachable from certified
surfaces. TEST_ONLY rows never execute product intent.
"""
from __future__ import annotations

from typing import Any

# Each row: (path, symbol, responsibility, classification, replacement)
LEDGER: tuple[dict[str, Any], ...] = (
    {
        "path": "veritx_dse/application/service.py",
        "symbol": "SrotaControlPlane",
        "responsibility": "sole product orchestration",
        "classification": "AUTHORITATIVE",
        "replacement": "itself",
    },
    {
        "path": "veritx_dse/cli/service_cli.py",
        "symbol": "service compile/evaluate/compare/inspect",
        "responsibility": "CLI transport adapter",
        "classification": "AUTHORITATIVE",
        "replacement": "itself",
    },
    {
        "path": "veritx_dse/api.py",
        "symbol": "service_compile/service_evaluate/service_compare/"
                  "service_inspect",
        "responsibility": "API transport adapter",
        "classification": "AUTHORITATIVE",
        "replacement": "itself",
    },
    {
        "path": "veritx_dse/application/surfaces.py",
        "symbol": "python_intent/api_intent/t3_intent/cli_intent",
        "responsibility": "surface intent constructors",
        "classification": "AUTHORITATIVE",
        "replacement": "itself",
    },
    {
        "path": "veritx_dse/backend/booksim.py",
        "symbol": "run_qualified_booksim",
        "responsibility": "sealed qualified execution",
        "classification": "AUTHORITATIVE",
        "replacement": "itself (called only by the service)",
    },
    {
        "path": "veritx_dse/core/experiment.py",
        "symbol": "run_experiment",
        "responsibility": "Slice-A legacy experiment runner "
                          "(simulation.booksim path)",
        "classification": "LEGACY_INTERNAL",
        "replacement": "application.service.SrotaControlPlane.evaluate",
    },
    {
        "path": "veritx_dse/simulation/booksim.py",
        "symbol": "run_topology_eval/run_booksim/build_config/BASE_PARAMS",
        "responsibility": "legacy handcrafted BookSim configs + subprocess",
        "classification": "LEGACY_INTERNAL",
        "replacement": "backend.booksim via the application service",
    },
    {
        "path": "veritx_dse/cli/cli.py",
        "symbol": "cmd_run/cmd_sweep/cmd_compare/cmd_evaluate_*",
        "responsibility": "historical product commands with independent "
                          "semantics",
        "classification": "LEGACY_INTERNAL",
        "replacement": "cli.service_cli service commands",
    },
    {
        "path": "veritx_dse/api.py",
        "symbol": "execute/compare/get_run/get_results",
        "responsibility": "legacy spec-dict API over run_experiment/Runs",
        "classification": "LEGACY_INTERNAL",
        "replacement": "api.service_* wrappers",
    },
    {
        "path": "veritx_dse/synthesis/",
        "symbol": "compiler/evaluator/bridge",
        "responsibility": "requirements-driven search with handcrafted "
                          "BookSim configs and direct subprocess",
        "classification": "LEGACY_INTERNAL",
        "replacement": "none in Wave C (synthesis science is Wave E)",
    },
    {
        "path": "veritx_dse/core/comparison.py",
        "symbol": "fingerprint_from_run/evaluate_comparability/"
                  "pareto_with_scope",
        "responsibility": "legacy result-directory fingerprint comparison",
        "classification": "LEGACY_INTERNAL",
        "replacement": "application.comparison gate over typed results",
    },
    {
        "path": "veritx_dse/cli/cli.py",
        "symbol": "legacy certify-flow/certify-rtl/certify-full",
        "responsibility": "historical flow/RTL certification "
                          "(re-entry deferred to B3.6R/B3.8-HW)",
        "classification": "LEGACY_INTERNAL",
        "replacement": "none in Wave C (blocked legacy namespace)",
    },
    {
        "path": "veritx_dse/cli/cli.py",
        "symbol": "api validate/plan/... (service mirrors)",
        "responsibility": "agent CLI surface aliased to the service",
        "classification": "AUTHORITATIVE",
        "replacement": "itself",
    },
    {
        "path": "veritx_dse/model/presets.py",
        "symbol": "WORKLOAD_PRESETS/topology presets/resolve_fabric",
        "responsibility": "mutable legacy preset dicts",
        "classification": "LEGACY_INTERNAL",
        "replacement": "application.presets immutable registries",
    },
    {
        "path": "tracks/t3-topology/scripts/",
        "symbol": "Timeloop/BookSim analysis pipeline",
        "responsibility": "Makefile-driven research analysis",
        "classification": "LEGACY_INTERNAL",
        "replacement": "none in Wave C (research-only, not product)",
    },
    {
        "path": "veritx_dse/backend/booksim.py",
        "symbol": "_run_qualified_booksim_with_runner_for_test",
        "responsibility": "injected-transport unit-test seam",
        "classification": "TEST_ONLY",
        "replacement": "none (never product)",
    },
    {
        "path": "veritx_dse/core/experiment_serving.py",
        "symbol": "run_serving_experiment",
        "responsibility": "serving experiment flow (execution BLOCKED)",
        "classification": "LEGACY_INTERNAL",
        "replacement": "none in Wave C (serving stays BLOCKED)",
    },
)

VALID_CLASSIFICATIONS = ("AUTHORITATIVE", "MIGRATE", "LEGACY_INTERNAL",
                         "TEST_ONLY", "DELETE")


def ledger_table() -> list[dict[str, Any]]:
    """The migration ledger as plain data (docs + tests consume this)."""
    for row in LEDGER:
        assert row["classification"] in VALID_CLASSIFICATIONS, row
    return [dict(row) for row in LEDGER]


__all__ = ["LEDGER", "VALID_CLASSIFICATIONS", "ledger_table"]

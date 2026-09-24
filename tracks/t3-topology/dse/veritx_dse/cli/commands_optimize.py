"""veritx_dse.cli.commands_optimize — ``veritx optimize`` product surface.

Thin CLI over the existing optimizer: grid/random search over GUIDED
fabric parameters, every candidate through the real certified evaluator
(compile → qualified BookSim → authenticated evidence), Pareto +
selection, schema-valid study view. No new search, no new evaluator, no
new metric — the optimizer owns all of that.
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any


def _parse_int_list(text: str | None) -> tuple[int, ...] | None:
    if text is None:
        return None
    values = tuple(int(tok) for tok in str(text).split(",") if tok.strip())
    if not values:
        raise ValueError("empty value list")
    return values


def _parse_clock_hz(text: Any) -> int | None:
    """Transport parsing for --network-clock-hz (exact Hz required).

    The evaluation core accepts only exact int/None clocks (float Hz
    would make wall-time claims inexact). An integral decimal/scientific
    string such as "1e9" is parsed EXACTLY (``Fraction``), never through
    binary float: ``float("9007199254740993")`` silently becomes
    9007199254740992, so a frequency would move without anyone changing
    it. Non-integral or non-finite strings refuse here at the CLI
    boundary, never inside the science.
    """
    from fractions import Fraction

    if text is None:
        return None
    if isinstance(text, bool):
        raise ValueError("network clock must be a number")
    if isinstance(text, int):
        value = text
    else:
        try:
            number = Fraction(text)
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            raise ValueError(
                f"network clock {text!r} is not an exact number") from exc
        if number.denominator != 1:
            raise ValueError(
                f"network clock {text!r} Hz is not an exact integer "
                "count — refusing inexact wall-time claims")
        value = number.numerator
    if value <= 0:
        raise ValueError("network clock must be positive")
    return value


def _invocation_root(run_root: str | Path) -> Path:
    """Per-invocation evidence root: same second+pid prefix, counter suffix.

    Two invocations in the same second share the prefix and differ only
    in the monotonic counter, so evidence slots are per-invocation and
    never reused while scientific identities stay content-based.
    """
    base = Path(run_root)
    base.mkdir(parents=True, exist_ok=True)
    prefix = (datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
              + f"-{os.getpid()}")
    taken = set()
    for child in base.iterdir():
        name = child.name
        if child.is_dir() and name.startswith(prefix + "-"):
            try:
                taken.add(int(name.rsplit("-", 1)[1]))
            except ValueError:
                continue
    counter = 0
    while counter in taken:
        counter += 1
    root = base / f"{prefix}-{counter}"
    root.mkdir(parents=True, exist_ok=False)
    return root


def cmd_optimize(ctx: Any, args: Any) -> None:
    """Run a certified optimization study and write the study view."""
    from ..core.logging import banner, fail, log, ok, output
    from ..core.paths import BOOKSIM_BIN
    from ..model.compile_model import CompileRequestV3
    from ..optimization.definition import (
        Constraint, DomainParam, Objective, OptimizationDefinition,
    )
    from ..optimization.result import CertifiedBackendConfig, Optimizer

    banner(ctx, "veritx optimize (certified)")
    try:
        doc = json.loads(Path(args.fixture).read_text())
    except Exception as exc:
        fail(ctx, f"cannot read fixture {args.fixture}: {exc}")
        return
    try:
        base_request = CompileRequestV3.from_dict(doc)
    except Exception as exc:
        fail(ctx, f"fixture is not a v3 CompileRequest: {exc}")
        return

    try:
        widths = _parse_int_list(getattr(args, "link_widths", None))
        concentrations = _parse_int_list(
            getattr(args, "concentrations", None))
    except ValueError as exc:
        fail(ctx, f"bad search domain: {exc}")
        return
    domain: list[Any] = []
    if widths:
        domain.append(DomainParam("link_width", widths))
    if concentrations:
        domain.append(DomainParam("concentration", concentrations))
    if not domain:
        fail(ctx, "no search domain: pass --link-widths and/or "
                  "--concentrations")
        return
    constraints: list[Any] = []
    ceiling = getattr(args, "latency_ceiling", None)
    if ceiling is not None:
        constraints.append(
            Constraint("completion_cycles", "<=", float(ceiling)))
    budget: dict[str, Any] = {}
    max_candidates = getattr(args, "max_candidates", None)
    if max_candidates is not None:
        budget["max_candidates"] = int(max_candidates)
    try:
        definition = OptimizationDefinition(
            domain=tuple(domain),
            objectives=(Objective("completion_cycles", "MIN"),),
            constraints=tuple(constraints),
            method=getattr(args, "search", None) or "grid",
            budget=budget,
            seed=getattr(args, "seed", None),
        )
    except Exception as exc:
        fail(ctx, f"invalid optimization definition: {exc}")
        return

    binary = getattr(args, "binary", None) or str(BOOKSIM_BIN)
    if not Path(binary).is_file():
        fail(ctx, f"BookSim binary not found: {binary}")
        return
    try:
        network_clock_hz = _parse_clock_hz(
            getattr(args, "network_clock_hz", None))
    except ValueError as exc:
        fail(ctx, f"bad --network-clock-hz: {exc}")
        return
    try:
        invocation_root = _invocation_root(args.run_root)
    except Exception as exc:
        fail(ctx, f"cannot create invocation root: {exc}")
        return
    config = CertifiedBackendConfig(
        binary=binary, run_root=invocation_root,
        network_clock_hz=network_clock_hz,
        timeout_s=int(getattr(args, "timeout", 600) or 600),
        repo_root=None)
    log(ctx, f"search={definition.method} "
             f"domain={[(p.name, list(p.values)) for p in domain]} "
             f"root={invocation_root}")
    try:
        result = Optimizer().optimize_certified(
            base_request, definition, backend_config=config)
    except Exception as exc:
        fail(ctx, f"optimization failed: {type(exc).__name__}: {exc}")
        return
    view = result.to_study_view()
    try:
        Path(args.study_out).write_text(json.dumps(view, indent=2) + "\n")
    except Exception as exc:
        fail(ctx, f"cannot write study {args.study_out}: {exc}")
        return
    ok(ctx, f"study: {len(view['candidates'])} candidates, "
            f"{len(view['pareto_ids'])} pareto, "
            f"selected={view['selected_candidate_id']}")
    output(ctx, {"study_out": str(args.study_out),
                 "optimization_result_id": view["optimization_result_id"],
                 "pareto_ids": view["pareto_ids"],
                 "selected_candidate_id": view["selected_candidate_id"]})

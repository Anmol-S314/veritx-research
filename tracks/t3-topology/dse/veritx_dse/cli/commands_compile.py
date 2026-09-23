"""veritx_dse.cli.commands_compile — thin CLI adapter for canonical compile.

Transport and presentation ONLY for the public ``veritx compile`` command:

    CLI declaration
          |
          v
    CompileIntent
          |
          v
    SrotaControlPlane.compile()
          |
          v
    canonical service path
          |
          v
    CompileOutcome

``cli.py`` owns the argparse declaration and dispatch;
``SrotaControlPlane`` owns orchestration. This module owns exactly:

* parsing ``--set PATH=JSON_SCALAR`` override strings;
* loading an exact persisted CompileIntent (``--intent``);
* constructing ``CompileIntent`` / ``ResourceStore`` / ``SrotaControlPlane``;
* calling ``compile()``;
* formatting the presentation summary.

It never compiles anything itself: no CompileRequest construction, no
topology/routing/VC derivation, no canonical compiler call, no BookSim, no
verification, no UVM/RTL/report generation. BookSim execution is a later,
separate slice.

Expected declaration errors (malformed ``--set``, invalid intent document,
service failure, store failure) propagate to the CLI's top-level handler,
which reports them cleanly and exits non-zero without a traceback. This
module does not catch broad exceptions and does not swallow programmer
bugs.
"""
from __future__ import annotations

import json
from pathlib import Path

from veritx_dse.application.compile_intent import CompileIntent
from veritx_dse.application.service import SrotaControlPlane
from veritx_dse.application.store import ResourceStore
from veritx_dse.core.logging import Ctx, log, ok, output, print_human

STATUS_RESOLVED = "RESOLVED"

# Optional preset-only declaration options are refused together with
# --intent: this mode consumes an exact persisted snapshot, never a merge.
# (label, argparse attribute) pairs.
_PRESET_ONLY_OPTIONS = (("--policy", "policy"), ("--set", "overrides"),
                        ("--name", "name"))


class CompileCommandError(ValueError):
    """The CLI declaration itself is malformed (a user error)."""


def _parse_override(text: str) -> tuple[str, object]:
    """Parse ``dotted.path=<strict JSON scalar>``.

    The RHS is parsed with strict JSON scalar semantics. Strings must be
    quoted (``noc_config.arbitration="rr"``); unquoted words are rejected so
    a typo can never silently become a string. Arrays, objects, NaN and
    Infinity are refused.
    """
    if not isinstance(text, str) or "=" not in text:
        raise CompileCommandError(
            f"--set expects PATH=JSON_SCALAR, got {text!r}")
    path, raw = text.split("=", 1)
    if not path:
        raise CompileCommandError(
            f"--set requires a non-empty dotted path, got {text!r}")
    if any(not segment for segment in path.split(".")):
        raise CompileCommandError(
            f"--set path {path!r} has an empty segment")
    try:
        value = json.loads(raw, parse_constant=_reject_constant)
    except ValueError as exc:
        raise CompileCommandError(
            f"--set {path!r} value is not a JSON scalar ({raw!r}); quote "
            f"strings, e.g. {path}=\"rr\": {exc}") from exc
    if not _is_json_scalar(value):
        raise CompileCommandError(
            f"--set {path!r} must be a JSON scalar (null, bool, int, finite "
            f"float or string), got {type(value).__name__}")
    return path, value


def _reject_constant(token: str):
    raise ValueError(f"{token} is not a JSON value")


def _is_json_scalar(value) -> bool:
    if value is None or type(value) is bool or type(value) is int \
            or isinstance(value, str):
        return True
    if type(value) is float:
        return value == value and value not in (float("inf"), float("-inf"))
    return False


def _intent_from_preset(args) -> CompileIntent:
    from veritx_dse.compiler.candidate_policy import CandidatePolicy

    if not args.policy:
        raise CompileCommandError(
            "--policy is required with --preset (declared candidate policy)")
    overrides = tuple(_parse_override(text)
                      for text in (args.overrides or []))
    return CompileIntent(
        name=args.name or f"cli:{args.preset}",
        fabric_preset=args.preset,
        fabric_overrides=overrides,
        candidate_policy=CandidatePolicy(args.policy),
    )


def _intent_from_file(path_text: str) -> CompileIntent:
    path = Path(path_text)
    if not path.is_file():
        raise CompileCommandError(f"compile intent file not found: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"),
                              parse_constant=_reject_constant)
    except ValueError as exc:
        raise CompileCommandError(
            f"compile intent file is not valid JSON: {path}: {exc}") from exc
    return CompileIntent.from_dict(document)


def _summary(outcome) -> dict:
    compiled = outcome.compiled
    return {
        "status": STATUS_RESOLVED,
        "intent_id": outcome.intent_id,
        "design_hash": outcome.design_hash,
        "fabric_hash": compiled.fabric.fabric_hash,
        "resolved_fabric_hash": outcome.resolved_fabric_hash,
        "topology_hash": compiled.topology.topology_hash(),
        "mapping_hash": compiled.mapping.mapping_hash(),
        "vc_count": compiled.vc_resource.vc_count,
    }


def _print_summary(data: dict) -> None:
    print(f"\n  \033[1mCompile Result\033[0m")
    print(f"  {'─' * 55}")
    print(f"  Compile state:     {data['status']}")
    print(f"  intent_id:         {data['intent_id']}")
    print(f"  design_hash:       {data['design_hash']}")
    print(f"  topology_hash:     {data['topology_hash']}")
    print(f"  mapping_hash:      {data['mapping_hash']}")
    print(f"  vc_count:          {data['vc_count']}")
    print(f"  fabric_hash:       {data['fabric_hash']}")
    print(f"  resolved_fabric:   {data['resolved_fabric_hash']}")
    print(f"  {'─' * 55}")
    print("  Backend execution: not performed")
    print("  Verification:      not performed")
    print(f"  {'─' * 55}\n")


def cmd_compile(ctx: Ctx, args) -> None:
    """Canonical product compile: CompileIntent -> committed ResolvedFabric."""
    if args.intent:
        refused = [label for label, attribute in _PRESET_ONLY_OPTIONS
                   if getattr(args, attribute, None)]
        if refused:
            raise CompileCommandError(
                "--intent consumes an exact persisted CompileIntent; "
                f"{', '.join(refused)} cannot be combined with it")
        intent = _intent_from_file(args.intent)
    else:
        intent = _intent_from_preset(args)

    store = ResourceStore(args.store)
    log(ctx, f"Store: {Path(args.store)}")
    log(ctx, f"Preset: {intent.fabric_preset} | policy: "
             f"{intent.candidate_policy.value}")

    outcome = SrotaControlPlane(store=store).compile(intent)
    summary = _summary(outcome)
    ok(ctx, f"Compiled: state={summary['status']} "
            f"resolved={summary['resolved_fabric_hash'][:16]}...")
    output(ctx, summary, human_fn=lambda data: (
        _print_summary(data), print_human(
            ctx, "Backend execution and verification are not performed by "
                 "the canonical compile command.")))

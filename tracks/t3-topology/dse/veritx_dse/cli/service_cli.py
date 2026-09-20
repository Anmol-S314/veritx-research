"""veritx_dse.cli.service_cli — Wave-C service adapters (thin by contract).

Each handler: parse transport args -> build the application service ->
call exactly one service operation -> emit the typed result envelope.
No backend imports, no semantics, no subprocess: importing anything from
``veritx_dse.backend`` or ``veritx_dse.simulation`` here is a product
boundary violation (enforced by architecture tests).
"""
from __future__ import annotations

import json
import sys
from typing import Any


def _service_from_args(args: Any):
    from ..application.service import SrotaControlPlane
    kwargs: dict[str, Any] = {}
    store = getattr(args, "store", None)
    if store:
        kwargs["store_root"] = store
    repo = getattr(args, "repo", None)
    if repo:
        kwargs["repo_root"] = repo
    binary = getattr(args, "binary", None)
    if binary:
        kwargs["binary"] = binary
    return SrotaControlPlane(**kwargs)


def _emit_ok(ctx: Any, payload: dict[str, Any]) -> None:
    from ..core.logging import emit
    # Service payloads carry their own typed "status"; nest under
    # "result" so the envelope status stays transport-level.
    emit(ctx, json.dumps({"status": "OK", "result": payload},
                         indent=2, sort_keys=True))


def _emit_error(ctx: Any, exc: BaseException) -> None:
    from ..application.errors import ControlPlaneError
    from ..core.logging import emit
    if isinstance(exc, ControlPlaneError):
        envelope = {"status": "ERROR", **exc.to_dict()}
    else:
        envelope = {"status": "ERROR",
                    "code": "INTERNAL_ERROR",
                    "message": f"{type(exc).__name__}: {exc}"}
    emit(ctx, json.dumps(envelope, indent=2, sort_keys=True))
    sys.exit(1)


def _load_request(args: Any) -> Any:
    """CLI surface constructor: file -> canonical intent document.

    Goes through ``surfaces.cli_intent`` (the tested CLI surface entry)
    and back through the canonical dict form, so CLI transport cannot
    poison semantic identity.
    """
    from ..application.surfaces import cli_intent
    return cli_intent(request_file=args.request).to_dict()


def _load_document(args: Any) -> Any:
    """Raw JSON request document (study/compare requests).

    Intent-bearing requests go through ``_load_request`` (the canonical
    intent surface). Study and compare requests carry their own schemas
    and are validated by the service; transport must not reinterpret
    them as intents.
    """
    import json
    from pathlib import Path
    from ..application.errors import intent_error
    try:
        return json.loads(Path(args.request).read_text())
    except (OSError, ValueError) as exc:
        raise intent_error(
            f"cli: cannot read request file {args.request}: {exc}",
            operation="cli", cause_type=type(exc).__name__) from exc


def cmd_service_compile(ctx: Any, args: Any):
    """Compile intent -> design + workload (no execution)."""
    try:
        service = _service_from_args(args)
        out = service.compile(_load_request(args))
    except Exception as exc:
        _emit_error(ctx, exc)
        return
    _emit_ok(ctx, out)


def cmd_service_evaluate(ctx: Any, args: Any):
    """Evaluate intent -> typed result (reuse or qualified run)."""
    try:
        service = _service_from_args(args)
        out = service.evaluate(_load_request(args))
    except Exception as exc:
        _emit_error(ctx, exc)
        return
    _emit_ok(ctx, out)


def cmd_service_compare(ctx: Any, args: Any):
    """Compare two persisted results through the compatibility gate."""
    try:
        service = _service_from_args(args)
        out = service.compare(_load_document(args))
    except Exception as exc:
        _emit_error(ctx, exc)
        return
    _emit_ok(ctx, out)


def cmd_service_inspect(ctx: Any, args: Any):
    """Inspect a resource by stable ID (read-only)."""
    try:
        service = _service_from_args(args)
        out = service.inspect(args.resource_id)
    except Exception as exc:
        _emit_error(ctx, exc)
        return
    _emit_ok(ctx, out)


def cmd_service_validate(ctx: Any, args: Any):
    """Validate intent (pure; no compile, no execution)."""
    try:
        service = _service_from_args(args)
        out = service.validate(_load_request(args))
    except Exception as exc:
        _emit_error(ctx, exc)
        return
    _emit_ok(ctx, out)


def cmd_service_plan(ctx: Any, args: Any):
    """Plan intent -> EvaluationPlan (no execution)."""
    try:
        service = _service_from_args(args)
        out = service.plan(_load_request(args))
    except Exception as exc:
        _emit_error(ctx, exc)
        return
    _emit_ok(ctx, out)


def cmd_service_study(ctx: Any, args: Any):
    """Run a study (sequential candidates + optional comparisons)."""
    try:
        service = _service_from_args(args)
        out = service.run_study(_load_document(args))
    except Exception as exc:
        _emit_error(ctx, exc)
        return
    _emit_ok(ctx, out)


def cmd_service_capabilities(ctx: Any, args: Any):
    """Show the derived capability registry."""
    try:
        service = _service_from_args(args)
        out = service.capabilities()
    except Exception as exc:
        _emit_error(ctx, exc)
        return
    _emit_ok(ctx, out)


def cmd_service_diagnose(ctx: Any, args: Any):
    """Operational health (no experiment)."""
    try:
        service = _service_from_args(args)
        out = service.diagnose()
    except Exception as exc:
        _emit_error(ctx, exc)
        return
    _emit_ok(ctx, out)


def cmd_service_list(ctx: Any, args: Any):
    """List persisted results (capped index)."""
    try:
        service = _service_from_args(args)
        out = service.list_results(limit=args.limit)
    except Exception as exc:
        _emit_error(ctx, exc)
        return
    _emit_ok(ctx, out)


__all__ = [
    "cmd_service_capabilities",
    "cmd_service_compare",
    "cmd_service_compile",
    "cmd_service_diagnose",
    "cmd_service_evaluate",
    "cmd_service_inspect",
    "cmd_service_list",
    "cmd_service_plan",
    "cmd_service_study",
    "cmd_service_validate",
]

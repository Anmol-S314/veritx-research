"""CLI surface for the scoped abstract data-movement experiment."""
import json
from pathlib import Path

from veritx_dse.application.data_movement import PROFILE, evaluate_experiment
from veritx_dse.core.errors import Refusal, SemanticError
from veritx_dse.core.logging import output, fail


def cmd_data_movement(ctx, args):
    try:
        result = evaluate_experiment(json.loads(Path(args.experiment).read_text()))
    except (Refusal, SemanticError, OSError, json.JSONDecodeError) as exc:
        fail(ctx, str(exc))
        output(ctx, {"status": "REFUSED", "profile": PROFILE, "reason": str(exc)})
        raise SystemExit(1) from None
    output(ctx, result.to_dict())

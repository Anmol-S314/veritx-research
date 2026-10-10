"""CLI surface for the scoped abstract data-movement experiment."""
import json
from pathlib import Path

from veritx_dse.application.data_movement import evaluate_experiment, refusal_document
from veritx_dse.core.errors import Refusal, SemanticError
from veritx_dse.core.logging import output, fail


def cmd_data_movement(ctx, args):
    try:
        result = evaluate_experiment(json.loads(Path(args.experiment).read_text()))
    except (Refusal, SemanticError, OSError, json.JSONDecodeError) as exc:
        fail(ctx, str(exc))
        output(ctx, refusal_document(exc))
        raise SystemExit(1) from None
    output(ctx, result.to_dict())

"""OptimizationDefinition selection identity (§4 port).

The selection policy is explicit in the definition identity: changing
it moves the definition id. There is no ``selection_metric_order``
field in this tree (lexicographic selection orders by the declared
objective sequence), so the ported assertion covers the policies that
exist: ``min_first_objective`` vs ``lexicographic`` vs ``none``.

No production change was needed: ``definition_id()`` already binds
``selection``.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.optimization.definition import (  # noqa: E402
    DomainParam, Objective, OptimizationDefinition,
)


def _defn(**kw):
    base = dict(
        domain=(DomainParam("link_width", (32, 128)),),
        objectives=(Objective("completion_cycles", "MIN"),),
        method="grid")
    base.update(kw)
    return OptimizationDefinition(**base)


def test_selection_none_moves_definition_identity():
    base = _defn()
    assert base.selection == "min_first_objective"
    none = dataclasses.replace(base, selection="none")
    lex = dataclasses.replace(base, selection="lexicographic")
    assert base.definition_id() != none.definition_id()
    assert base.definition_id() != lex.definition_id()
    assert none.definition_id() != lex.definition_id()


def test_selection_none_selects_nothing():
    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).resolve().parent))
    from test_p2_real_adapter import _base as _real_base  # noqa: E402
    from veritx_dse.optimization.result import Optimizer  # noqa: E402
    from veritx_dse.optimization.evaluators import (  # noqa: E402
        FakeDeterministicEvaluator)
    result = Optimizer().optimize(
        _real_base(), _defn(selection="none"),
        FakeDeterministicEvaluator(seed=7))
    assert result.selected_candidate_id is None

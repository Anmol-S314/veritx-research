"""RT-final repair B-P1.4 — unexpected errors must escape as bugs.

The evaluator's seams are narrowed to their documented exception
taxonomy: a programming bug (KeyError / AttributeError / TypeError)
injected into a wrapped seam propagates instead of being laundered into
a scientifically adjudicated FAILED/UNSUPPORTED status. Documented
refusals (BookSimError etc.) still map to FAILED — see
test_p1b_fabric_evaluator.py::TestFailures.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]

from test_p1b_fabric_evaluator import (  # noqa: E402
    _anynet_bundle_2node,
    _compilation_for,
    _fake_binary,
    _lowered,
)

from veritx_dse.application.fabric_evaluator import (  # noqa: E402
    EvaluationOptions,
    FabricEvaluator,
)


class TestUnexpectedErrorsEscape:
    def test_projection_programming_error_escapes(self, monkeypatch):
        import veritx_dse.backend.projection as projection
        chain, bundle = _anynet_bundle_2node()
        comp = _compilation_for(chain, bundle)

        def _boom(physical, *, seed=None):
            raise KeyError("injected programming bug")

        monkeypatch.setattr(projection, "prepare_waved_booksim", _boom)
        with pytest.raises(KeyError):
            FabricEvaluator().evaluate(
                comp, _lowered(comp),
                EvaluationOptions(traffic_class="A"))

    def test_execution_programming_error_escapes(self, monkeypatch,
                                                 tmp_path):
        import veritx_dse.backend.projection as projection
        fake_bin, _ = _fake_binary(tmp_path)
        chain, bundle = _anynet_bundle_2node()
        comp = _compilation_for(chain, bundle)

        def _boom(prepared, **kwargs):
            raise AttributeError("injected programming bug")

        monkeypatch.setattr(projection, "run_waved_booksim", _boom)
        with pytest.raises(AttributeError):
            FabricEvaluator().evaluate(
                comp, _lowered(comp),
                EvaluationOptions(traffic_class="A", binary=fake_bin,
                                  run_dir=str(tmp_path / "run")))

    def test_documented_booksim_error_still_maps_to_failed(
            self, monkeypatch, tmp_path):
        """Positive control: the narrowing did not remove the documented
        mapping — a BookSimError from the same seam is a FAILED outcome."""
        import veritx_dse.backend.projection as projection
        from veritx_dse.core.errors import BookSimError
        fake_bin, _ = _fake_binary(tmp_path)
        chain, bundle = _anynet_bundle_2node()
        comp = _compilation_for(chain, bundle)

        def _fail(prepared, **kwargs):
            raise BookSimError("documented simulator crash")

        monkeypatch.setattr(projection, "run_waved_booksim", _fail)
        out = FabricEvaluator().evaluate(
            comp, _lowered(comp),
            EvaluationOptions(traffic_class="A", binary=fake_bin,
                              run_dir=str(tmp_path / "run")))
        assert out.status == "FAILED"
        assert "documented simulator crash" in (out.reason or "")

    def test_fabric_evaluator_has_no_broad_except(self):
        source = (DSE / "veritx_dse" / "application" /
                  "fabric_evaluator.py").read_text()
        assert "except Exception" not in source
        tree = ast.parse(source)
        broad = [node.lineno for node in ast.walk(tree)
                 if isinstance(node, ast.ExceptHandler)
                 and node.type is None]
        assert broad == [], broad

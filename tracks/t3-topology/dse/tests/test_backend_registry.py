"""Federation Commit 06 — the registry: explicit, duplicate-refusing,
and honest that registration is not readiness."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.backend.adapter import (  # noqa: E402
    BackendAssessment, BackendCapability, BackendContractError,
    BackendReadiness, ModelFidelity, PreparedExecution, SupportLevel,
)
from veritx_dse.backend.booksim_adapter import BookSimAdapter  # noqa: E402
from veritx_dse.backend.registry import (  # noqa: E402
    BackendRegistry, BackendRegistryError, default_backend_registry,
)


class _StubAdapter:
    def __init__(self, backend_id: str):
        self._id = backend_id

    @property
    def backend_id(self) -> str:
        return self._id

    def capabilities(self) -> tuple[BackendCapability, ...]:
        return ()

    def assess(self, context: object,
               question: EvaluationQuestion) -> BackendAssessment:
        raise AssertionError("stub should not be assessed")

    def prepare(self, context: object,
                question: EvaluationQuestion) -> PreparedExecution:
        raise AssertionError("stub should not prepare")

    def execute(self, prepared: PreparedExecution,
                options: object) -> object:
        raise AssertionError("stub should not execute")


def test_register_get_require_round_trip():
    registry = BackendRegistry()
    adapter = _StubAdapter("FAKE_A")
    registry.register(adapter)
    assert registry.get("FAKE_A") is adapter
    assert registry.require("FAKE_A") is adapter
    assert "FAKE_A" in registry
    assert len(registry) == 1


def test_duplicate_registration_refused():
    registry = BackendRegistry((_StubAdapter("FAKE_A"),))
    with pytest.raises(BackendRegistryError, match="already registered"):
        registry.register(_StubAdapter("FAKE_A"))


def test_duplicate_in_constructor_refused():
    with pytest.raises(BackendRegistryError, match="duplicate"):
        BackendRegistry((_StubAdapter("FAKE_A"), _StubAdapter("FAKE_A")))


def test_unknown_backend_get_none_require_raises():
    registry = BackendRegistry()
    assert registry.get("NOPE") is None
    with pytest.raises(BackendRegistryError, match="no backend registered"):
        registry.require("NOPE")


def test_adapters_order_is_registration_order():
    registry = BackendRegistry((
        _StubAdapter("A"), _StubAdapter("B"), _StubAdapter("C")))
    assert [a.backend_id for a in registry.adapters()] == ["A", "B", "C"]


def test_default_registry_has_booksim():
    registry = default_backend_registry()
    adapter = registry.require("BOOKSIM_STANDALONE")
    assert isinstance(adapter, BookSimAdapter)
    caps = adapter.capabilities()
    assert len(caps) == 1
    assert caps[0].question is EvaluationQuestion.NETWORK_COMPLETION
    assert caps[0].support is SupportLevel.SUPPORTED
    assert caps[0].fidelity is ModelFidelity.NETWORK_PACKET_SIMULATION


def test_non_adapter_registration_is_not_magically_validated():
    """The registry trusts structural conformance (Protocol typing tests
    own that law); it owns only identity uniqueness."""
    registry = BackendRegistry()
    registry.register(_StubAdapter("FAKE_A"))  # duck-typed: fine
    assert "FAKE_A" in registry

"""Tests for API contract correctness — things that SHOULD fail but don't.

These tests verify that CompileRequest handles all valid input forms,
including the common mistake of passing a plain list instead of DependencyGraph.
This is the class of bug that hides when tests always use the 'correct' form.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.model.compile_model import (
    CompileRequest, Workload, Agent, NocConfig, Dependency,
    DependencyGraph, ModelFamily, AgentKind, TopologyFamily, DepKind,
)
from veritx_dse.reports.artifact import DesignManifest


class TestCompileRequestApiContract:
    """CompileRequest must accept all valid input forms."""

    def _minimal_cr(self, **overrides):
        defaults = dict(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=4)],
            dependencies=[],
            noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        )
        defaults.update(overrides)
        return CompileRequest(**defaults)

    def test_empty_list_dependencies(self):
        """dependencies=[] should work (auto-converted to DependencyGraph)."""
        cr = self._minimal_cr(dependencies=[])
        assert isinstance(cr.dependencies, DependencyGraph)

    def test_dependency_list_converted(self):
        """dependencies=[Dependency(...)] should auto-convert to DependencyGraph."""
        deps = [Dependency(source="a", target="b", kind=DepKind.BLOCKING)]
        cr = self._minimal_cr(dependencies=deps)
        assert isinstance(cr.dependencies, DependencyGraph)
        assert len(cr.dependencies.dependencies) == 1

    def test_dependency_graph_passthrough(self):
        """DependencyGraph should pass through unchanged."""
        dg = DependencyGraph([Dependency(source="a", target="b", kind=DepKind.BLOCKING)])
        cr = self._minimal_cr(dependencies=dg)
        assert cr.dependencies is dg

    def test_guardrail_hash_works_with_list_deps(self):
        """guardrail_hash() should work even when deps started as a list."""
        cr = self._minimal_cr(
            dependencies=[Dependency(source="a", target="b", kind=DepKind.BLOCKING)]
        )
        h = cr.guardrail_hash()
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex

    def test_design_manifest_works_with_list_deps(self):
        """DesignManifest.create() should work with list deps."""
        cr = self._minimal_cr(
            dependencies=[Dependency(source="a", target="b", kind=DepKind.BLOCKING)]
        )
        dm = DesignManifest.create(cr, secret_key="test-key")
        assert dm.revision == 1
        assert len(dm.guardrail_hash) == 64

    def test_validate_works_with_list_deps(self):
        """validate() should work with list deps."""
        from veritx_dse.model.compile_model import validate
        cr = self._minimal_cr(
            dependencies=[Dependency(source="a", target="b", kind=DepKind.BLOCKING)]
        )
        result = validate(cr)
        assert result.ok

    def test_requirements_as_list(self):
        """requirements=[] (list) should auto-convert to tuple."""
        from veritx_dse.model.compile_model import Requirement, QoSClass
        cr = self._minimal_cr(requirements=[
            Requirement(qos_class=QoSClass.LATENCY_CRITICAL, latency_ceiling_cycles=100)
        ])
        assert isinstance(cr.requirements, tuple)

    def test_agents_as_list(self):
        """agents=[] (list) should auto-convert to tuple."""
        cr = self._minimal_cr()
        assert isinstance(cr.agents, tuple)

    def test_frozen_after_construction(self):
        """CompileRequest should be immutable after construction."""
        cr = self._minimal_cr()
        with pytest.raises(AttributeError):
            cr.workload = Workload(model_family=ModelFamily.DENSE)

    def test_total_nodes(self):
        """total_nodes sums agent counts."""
        cr = self._minimal_cr(agents=[
            Agent(kind=AgentKind.COMPUTE_TILE, count=16),
            Agent(kind=AgentKind.HBM_CONTROLLER, count=4),
        ])
        assert cr.total_nodes == 20

    def test_empty_agents_rejected(self):
        """agents=[] should raise ValueError."""
        with pytest.raises(ValueError, match="agents list cannot be empty"):
            self._minimal_cr(agents=[])

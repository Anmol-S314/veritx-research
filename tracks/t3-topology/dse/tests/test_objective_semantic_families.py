"""§1/§16 — units are not dimensions.

The certified registry names three metrics. They are NOT three independent
optimization dimensions: all three read the same canonical artifact
(`verified["network_binding"]`, the authenticated network completion window).
`completion_cycles` and `completion_time` even share a producer id.

So a study over "cycles vs ns" is ONE quantity expressed twice, and rendering
it as a Pareto frontier would manufacture a trade-off that does not exist.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.optimization import metric_registry as MR  # noqa: E402
from veritx_dse.optimization.capabilities import (  # noqa: E402
    independent_objective_families, objective_semantic_family,
    optimization_capabilities,
)

def test_all_certified_metrics_read_the_same_binding():
    """The DERIVATION of the family: every certified producer resolves the
    SAME canonical artifact — `network_binding`, the authenticated completion
    window. If a future metric reads something else, this fails and the family
    mapping must be revisited rather than assumed.

    `_completion_cycles` reaches it through `authenticated_network_cycles`, so
    the chain is followed rather than the literal string matched.
    """
    from veritx_dse.application import requirements as R
    sources = {
        "_completion_ns": inspect.getsource(MR._completion_ns),
        "authenticated_network_cycles":
            inspect.getsource(R.authenticated_network_cycles),
    }
    for name, src in sources.items():
        assert "network_binding" in src, name
    assert "authenticated_network_cycles" in \
        inspect.getsource(MR._completion_cycles)

def test_cycles_and_time_share_a_producer():
    authorities = MR.CERTIFIED_METRIC_REGISTRY.authorities
    assert (authorities["completion_cycles"].producer_id
            == authorities["completion_time"].producer_id)

def test_the_completion_units_are_ONE_family():
    """THE §1 LAW, asserted directly: cycles/time/ns are one family.

    This is deliberately NOT a frozen list of the registry's families — the
    registry may grow genuinely independent metrics (Wave-E's makespan and
    critical_path are exactly that), and folding them into `completion` would
    be the opposite error.
    """
    assert objective_semantic_family("completion_cycles") == "completion"
    assert objective_semantic_family("completion_time") == "completion"
    assert objective_semantic_family("completion_ns") == "completion"

def test_metrics_from_a_different_producer_are_not_folded_in():
    """`completion` is ONE family because those three read the same binding.
    A metric with a different producer is its own family."""
    from veritx_dse.optimization.metric_registry import (
        CERTIFIED_METRIC_REGISTRY as R,
    )
    for name, authority in R.authorities.items():
        if authority.producer_id == "authenticated-network-window-cycles":
            assert objective_semantic_family(name) == "completion", name
        elif authority.producer_id != "authenticated-network-window-wall-time-ns":
            assert objective_semantic_family(name) != "completion", (
                f"{name} comes from {authority.producer_id} and must not be "
                "folded into the completion family")

def test_multi_objective_availability_is_derived_from_the_family_count():
    """Not a constant: a registry with one family must report False, and this
    one currently reports True because Wave-E metrics are independent."""
    caps = optimization_capabilities()
    families = caps["independent_objective_families"]
    assert caps["multi_objective_available"] is (len(families) > 1)
    assert "completion" in families

def test_an_unknown_metric_gets_its_OWN_family():
    """Assuming independence is the safe direction: it merely declines to
    claim redundancy, so a genuinely new metric is never silently folded in."""
    assert objective_semantic_family("area_mm2") == "area_mm2"
    assert objective_semantic_family("energy_pj") == "energy_pj"

def test_the_payload_explains_why_ranking_not_pareto():
    caps = optimization_capabilities()
    assert "ONE semantic objective" in caps["objective_note"]
    assert "RANKING" in caps["objective_note"]

def test_families_are_derived_from_the_live_registry_not_restated():
    """Adding a certified metric must change the family list without anyone
    editing a constant."""
    names = MR.CERTIFIED_METRIC_REGISTRY.metric_names()
    derived = {objective_semantic_family(n) for n in names}
    assert derived == set(independent_objective_families())

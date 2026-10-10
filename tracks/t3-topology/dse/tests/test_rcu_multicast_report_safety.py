"""Removed physical features cannot manufacture report costs or capabilities."""
import pytest

from test_canonical_compiler import _design, _det
from veritx_dse.core.errors import MissingCapability
from veritx_dse.model.compile_model import CompileRequest
from veritx_dse.reports.reports import estimate_fabric_area, generate_report


@pytest.mark.parametrize("kwargs", [{"has_rcu": True}, {"n_rcu": 1}, {"n_rcu": -1}, {"has_rcu": True, "n_rcu": 0}])
def test_shared_area_estimator_refuses_unmodeled_rcu(kwargs):
    with pytest.raises(MissingCapability) as exc:
        estimate_fabric_area(4, 8, 4, **kwargs)
    assert exc.value.capability == "rcu_hardware"
    assert exc.value.stage == "EVALUATE"


def _legacy(noc):
    return CompileRequest.from_dict({
        "schema_version": 2, "compiler_semantics_version": 2,
        "workload": {"model_family": "dense_transformer", "tp": 4,
                     "dp": 1, "serving_mode": "mixed"},
        "agents": [{"kind": "compute_tile", "count": 4}],
        "noc_config": noc,
    })


@pytest.mark.parametrize("value", [None, False])
def test_nonrequesting_rcu_roundtrip_compile_and_report(value):
    cr = _legacy({"rcu_enabled": value})
    reloaded = CompileRequest.from_dict(cr.to_dict())
    assert reloaded.noc_config.rcu_enabled is value
    assert generate_report(reloaded)["area"]["rcu_mm2"] == 0
    assert _det(_design(compute=4, tp=4, noc_kw={"rcu_enabled": value})).resolved_fabric


@pytest.mark.parametrize("noc, capability", [
    ({"rcu_enabled": True}, "rcu_hardware"),
    ({"mcast_groups": 1}, "multicast_group_hardware"),
    ({"mcast_groups": 4}, "multicast_group_hardware"),
    ({"mcast_setup_cycles": 0}, "multicast_setup_state"),
    ({"mcast_setup_cycles": 3}, "multicast_setup_state"),
])
def test_legacy_report_and_canonical_compiler_refuse_same_capability(noc, capability):
    cr = _legacy(noc)
    assert CompileRequest.from_dict(cr.to_dict()).noc_config == cr.noc_config
    with pytest.raises(MissingCapability) as exc:
        generate_report(cr)
    assert exc.value.capability == capability
    assert exc.value.stage == "EVALUATE"
    with pytest.raises(MissingCapability) as exc:
        _det(_design(compute=4, tp=4, noc_kw=noc))
    assert exc.value.capability == capability
    assert exc.value.stage == "RESOLVED_FABRIC"


def test_ordinary_report_does_not_assume_ideal_multicast_or_physical_group_counts():
    report = generate_report(_legacy({}))
    collective = report["collectives"]
    for name in ("multicast_groups_required", "multicast_groups_available",
                 "multicast_fallback_to_unicast", "multicast_setup_cost_cycles_estimate"):
        assert collective[name] is None
    assert "SOURCE_REPLICATION" in collective["multicast_note"]
    assert "unavailable" in collective["multicast_note"]
    assert "None-valued knobs mean ideal" not in collective["multicast_note"]

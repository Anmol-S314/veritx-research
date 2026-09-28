"""Energy/power fidelity registry — six quantities, never one number.

Each estimator carries its own fidelity, units, inputs, source and scope.
combine_estimates() always raises: merging a hops-proxy with a serving
power model is a category error, not a feature.

BookSim native power is INVALID for GEC-MECS until multidrop activity is
included: Power_Module walks Network::GetChannels() (_chan only) while
MECS shared links live in _md_chan.
"""
from __future__ import annotations

BOOKSIM_NATIVE_POWER_FOR_MECS = "INVALID_INCOMPLETE"

#: Placeholder-calibrated bridge coefficient, verbatim from
#: tracks/t3-topology/timeloop/noc_ERT.yaml (traversal 2.5 + buffer_read
#: 0.8 + buffer_write 0.9 + link transfer 1.2). PLACEHOLDER until
#: DSENT/ORION/synthesis/datasheet calibration.
BRIDGE_PJ_PER_HOP = 5.4
BRIDGE_ERT_STATUS = "PLACEHOLDER"

ESTIMATORS = (
    {
        "id": "hops_packet_proxy",
        "fidelity": "PROXY",
        "units": "hop-bits (relative)",
        "inputs": ("hops_avg", "packet_size_bits"),
        "source": "BookSim sweep hops_avg",
        "scope": "research Pareto input only",
    },
    {
        "id": "timeloop_accelergy",
        "fidelity": "TOOL_DERIVED",
        "units": "uJ (accelerator-side)",
        "inputs": ("timeloop_stats", "accelergy_ERT"),
        "source": "Timeloop/Accelergy tools",
        "scope": "compute/accelerator energy, never NoC signoff",
    },
    {
        "id": "noc_energy_bridge",
        "fidelity": "TOOL_CALIBRATED_PROXY",
        "units": "pJ",
        "inputs": ("hops_avg", "packet_size_flits", "ERT_STATUS=PLACEHOLDER"),
        "source": "Accelergy 1-hop run x BookSim hops",
        "scope": "research estimate at 5.4 pJ/hop nominal",
    },
    {
        "id": "analytical_reports",
        "fidelity": "ANALYTICAL_ESTIMATE",
        "units": "mm^2 / W (estimate, not signoff)",
        "inputs": ("process_nm", "published scaling refs"),
        "source": "reports.py (DAC22/CMN-600/JEDEC scaling)",
        "scope": "comparison metric only, never Pareto objective",
    },
    {
        "id": "booksim_native_power",
        "fidelity": "BACKEND_ACTIVITY",
        "units": "W (sim_power=1 activity)",
        "inputs": ("SwitchMonitor/BufferMonitor activity", "_chan only"),
        "source": "BookSim Power_Module",
        "scope": "point-to-point topologies only; INVALID for MECS",
    },
    {
        "id": "llmservingsim_power",
        "fidelity": "DOWNSTREAM_MODEL",
        "units": "W / J (serving system)",
        "inputs": ("provisioned node configs", "nvidia-smi profiles"),
        "source": "LLMServingSim power_model",
        "scope": "serving leg only, never fabric energy",
    },
)

_MECS_TOKENS = ("gec", "mecs", "multidrop", "tapped", "hybrid")


def booksim_native_verdict(family: str) -> tuple[str, str]:
    """Fidelity verdict for BookSim native power on one topology family."""
    name = (family or "").lower()
    if not name:
        return ("REFUSED", "empty family — refusing to qualify power")
    if any(t in name for t in _MECS_TOKENS):
        return (
            "INVALID",
            f"{BOOKSIM_NATIVE_POWER_FOR_MECS}: Power_Module walks "
            "GetChannels() (_chan); MECS shared links live in _md_chan",
        )
    return ("VALID_SCOPE", "point-to-point backend-activity scope only")


def combine_estimates(*args, **kwargs):
    raise ValueError(
        "energy estimators must never be merged into one number — "
        "report each fidelity separately"
    )


__all__ = [
    "BOOKSIM_NATIVE_POWER_FOR_MECS",
    "BRIDGE_PJ_PER_HOP",
    "BRIDGE_ERT_STATUS",
    "ESTIMATORS",
    "booksim_native_verdict",
    "combine_estimates",
]

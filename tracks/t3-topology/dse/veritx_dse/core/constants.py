"""veritx_dse.constants — Centralized magic numbers.

Rationale: docs/decisions/modules/core.md
"""
from veritx_dse.core.paths import REPO, DSE_DIR, BOOKSIM_BIN, RUNS_DIR

def env_int(name: str, default: int) -> int:
    """Read an integer env var with fail-fast validation.

    Unset -> default. Set-but-not-integer -> ValueError (never silently
    coerce: a typo'd env var must not become a mystery default).
    """
    import os
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"environment variable {name} must be an integer, "
                         f"got {raw!r}") from exc

BOOKSIM_DEFAULTS = {
    "packet_size": 8,
    "vc_buf_size": 4,
    "num_vcs": 2,
    "latency_thres": -1.0,
    "wait_for_tail_credit": 1,
    "use_noc_latency": 0,
    "routing_delay": 1,
}

ROUTER_AREA_MM2_7NM = 0.005
LINK_AREA_MM2_PER_MM = 0.0001
LINK_AREA_MM2_256B_7NM = 0.0003
NIC_AREA_MM2 = 0.002
NIC_AREA_MM2_7NM = 0.008
RCU_AREA_MM2_7NM = 0.012
MECS_AREA_MM2_7NM = 0.002
ENERGY_PER_BIT_PER_HOP = 0.15
VOLTAGE_DEFAULT = 0.75
FREQ_DEFAULT_GHZ = 1.0
CAPACITANCE_PER_BIT_FF = 0.5
ROUTER_DYNAMIC_MW_PER_MHZ = 0.010
LEAKAGE_PER_ROUTER_MW = 0.5
ROUTER_STAGE_DELAY_PS = {
    "input_buffer": 80,
    "routing_computation": 60,
    "vc_allocation": 80,
    "switch_allocation": 100,
    "crossbar_traversal": 60,
}
WIRE_DELAY_PS_PER_MM = 3.5
TOPO_WIRE_MM = {
    "mesh": 0.5,
    "torus": 0.4,
    "flatfly": 0.3,
    "gec": 0.35,
    "anynet": 0.45,
}
FMAX_DERATING = 0.75

DEFAULT_SEED = 0
BOOKSIM_SEED = 42
DEFAULT_NODES = 64
DEFAULT_K = 8
DEFAULT_TIMEOUT = 60
DEFAULT_PROCESS_NM = 7
# Shared canonical VC bound. GEC-hybrid native witnesses exercise 10/12/14/16
# VCs with route observations and all four analyses; this is not RTL signoff.
PLANE_C_MAX_VC = env_int("VERITX_MAX_VC", 16)

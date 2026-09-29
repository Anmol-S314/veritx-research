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
    "packet_size": 8,           # flits per packet
    "vc_buf_size": 4,           # buffers per VC
    "num_vcs": 2,               # default virtual channels
    "latency_thres": -1.0,      # -1 = disabled
    "wait_for_tail_credit": 1,  # enable backpressure
    "use_noc_latency": 0,       # 0 for trace-replay
    "routing_delay": 1,         # deferred routing for GEC
}

ROUTER_AREA_MM2_7NM = 0.005    # per router at 7nm
LINK_AREA_MM2_PER_MM = 0.0001  # per mm wire length (wire-only; needs length x count)
LINK_AREA_MM2_256B_7NM = 0.0003
NIC_AREA_MM2 = 0.002           # bare NIC (minimal adapter, no DMA)
# Full NIC area (mm2) per NIC at 7nm — protocol adapter + DMA engine.
# Intentionally diverges from NIC_AREA_MM2: reports model the full NIC.
NIC_AREA_MM2_7NM = 0.008
RCU_AREA_MM2_7NM = 0.012      # per RCU at 7nm (in-network reduction unit)
MECS_AREA_MM2_7NM = 0.002     # per MECS endpoint at 7nm (express channel endpoint)
ENERGY_PER_BIT_PER_HOP = 0.15  # pJ/bit/hop (standard NoC)
VOLTAGE_DEFAULT = 0.75         # V
FREQ_DEFAULT_GHZ = 1.0         # GHz
CAPACITANCE_PER_BIT_FF = 0.5   # fF per bit (wire capacitance only)
ROUTER_DYNAMIC_MW_PER_MHZ = 0.010  # mW per MHz at 100% activity, 256-bit (CMN-600/DAC cal.)
LEAKAGE_PER_ROUTER_MW = 0.5    # mW per router at 7nm (sub-threshold + gate)
# Per-stage router pipeline delay at 7nm (picoseconds).
ROUTER_STAGE_DELAY_PS = {
    "input_buffer": 80,
    "routing_computation": 60,
    "vc_allocation": 80,
    "switch_allocation": 100,
    "crossbar_traversal": 60,
}
WIRE_DELAY_PS_PER_MM = 3.5  # speed of light ~50% in copper
# Average wire length per topology (mm).
TOPO_WIRE_MM = {
    "mesh": 0.5,
    "torus": 0.4,     # wraparound reduces avg distance
    "flatfly": 0.3,   # concentrated
    "gec": 0.35,      # express channels
    "anynet": 0.45,   # unknown, assume mesh-like
}
FMAX_DERATING = 0.75  # 25% margin is conservative for 7nm

# ── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_SEED = 0               # 0 = auto-generate
BOOKSIM_SEED = 42              # fixed BookSim config seed (NOT DEFAULT_SEED:
                               # simulation seeds must be reproducible, never auto)
DEFAULT_NODES = 64
DEFAULT_K = 8
DEFAULT_TIMEOUT = 60           # seconds
DEFAULT_PROCESS_NM = 7         # technology node
PLANE_C_MAX_VC = env_int("VERITX_MAX_VC", 8)

"""veritx_dse.constants — Centralized magic numbers.

Single source of truth for all hardcoded values.
Every 'magic number' in the codebase should reference these.
"""
from veritx_dse.paths import REPO, DSE_DIR, BOOKSIM_BIN, RUNS_DIR

# ── BookSim defaults ─────────────────────────────────────────────────────────
BOOKSIM_DEFAULTS = {
    "packet_size": 8,           # flits per packet
    "vc_buf_size": 4,           # buffers per VC
    "num_vcs": 2,               # default virtual channels
    "latency_thres": -1.0,      # -1 = disabled
    "wait_for_tail_credit": 1,  # enable backpressure
    "use_noc_latency": 0,       # 0 for trace-replay
    "routing_delay": 1,         # deferred routing for GEC
}

# ── Area/power estimates ─────────────────────────────────────────────────────
ROUTER_AREA_MM2_7NM = 0.005    # per router at 7nm
LINK_AREA_MM2_PER_MM = 0.0001  # per mm wire length
NIC_AREA_MM2 = 0.002           # per NIC
ENERGY_PER_BIT_PER_HOP = 0.15  # pJ/bit/hop (standard NoC)
VOLTAGE_DEFAULT = 0.75         # V
FREQ_DEFAULT_GHZ = 1.0         # GHz

# ── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_SEED = 0               # 0 = auto-generate
DEFAULT_NODES = 64
DEFAULT_K = 8
DEFAULT_TIMEOUT = 60           # seconds
DEFAULT_ITERS = 20             # BO iterations
DEFAULT_PROCESS_NM = 7         # technology node
PLANE_C_MAX_VC = 8             # max VCs per plane

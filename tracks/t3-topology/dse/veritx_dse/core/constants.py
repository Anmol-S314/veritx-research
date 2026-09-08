"""veritx_dse.constants — Centralized magic numbers.

Single source of truth for all hardcoded values.
Every 'magic number' in the codebase should reference these.
Environment-overridable bounds use env_int() (fail fast on garbage).
"""
from veritx_dse.core.paths import REPO, DSE_DIR, BOOKSIM_BIN, RUNS_DIR


def env_int(name: str, default: int) -> int:
    """Read an integer env var with fail-fast validation.

    Unset → default. Set-but-not-integer → ValueError (never silently
    coerce: a typo'd env var must not become a mystery default).
    """
    import os
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(
            f"{name}={raw!r} is not an integer")

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
# Max VCs per plane. Env-overridable: fabrics with shared-pool or
# high-radix VC budgets (e.g. PCIe6 VC0-VC7 + shared pool) need > 8.
# Import-time read (documented): changing it requires process restart.
PLANE_C_MAX_VC = env_int("VERITX_MAX_VC", 8)

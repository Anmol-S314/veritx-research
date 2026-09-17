"""veritx_dse.reports — PRD §7: Formal area, power, timing estimates.

Per-block area models based on published NoC synthesis results at
various technology nodes. Power model uses standard CMOS dynamic +
leakage estimation. Timing model estimates Fmax from pipeline depth
and wire delay.

References:
  - M. A. A. Faruque et al., "Thermal Budget Allocation for
    Network-on-Chip", DAC 2022 (area per router)
  - ARM CMN-600 datasheet (router area at 7nm)
  - JEDEC HBM3 spec (interface widths)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.constants import (
    BOOKSIM_DEFAULTS,
    CAPACITANCE_PER_BIT_FF,
    ENERGY_PER_BIT_PER_HOP,
    FMAX_DERATING,
    FREQ_DEFAULT_GHZ,
    LEAKAGE_PER_ROUTER_MW,
    LINK_AREA_MM2_256B_7NM,
    MECS_AREA_MM2_7NM,
    NIC_AREA_MM2_7NM,
    RCU_AREA_MM2_7NM,
    ROUTER_AREA_MM2_7NM,
    ROUTER_DYNAMIC_MW_PER_MHZ,
    ROUTER_STAGE_DELAY_PS,
    TOPO_WIRE_MM,
    VOLTAGE_DEFAULT,
    WIRE_DELAY_PS_PER_MM,
)
from ..model.compile_model import CompileRequest


# ══════════════════════════════════════════════════════════════════════════════
# §7.1 — Area Model (canonical values from core.constants)
# ══════════════════════════════════════════════════════════════════════════════

# Backward-compat aliases — canonical homes live in core.constants.
# _ROUTER_AREA_7NM == ROUTER_AREA_MM2_7NM (0.005, identical).
_ROUTER_AREA_7NM = ROUTER_AREA_MM2_7NM

# _LINK_AREA_REF == LINK_AREA_MM2_256B_7NM (0.0003). Intentionally diverges
# from LINK_AREA_MM2_PER_MM (0.0001/mm wire-only): per-link (repeaters +
# shielding) vs per-mm abstraction — do NOT substitute.
_LINK_AREA_REF = LINK_AREA_MM2_256B_7NM

# _NIC_AREA_7NM == NIC_AREA_MM2_7NM (0.008 full NIC + DMA). Intentionally
# diverges from NIC_AREA_MM2 (0.002 bare NIC) — reports model the full NIC.
_NIC_AREA_7NM = NIC_AREA_MM2_7NM

_RCU_AREA_7NM = RCU_AREA_MM2_7NM

_MECS_AREA_7NM = MECS_AREA_MM2_7NM


def _scale_factor(process_nm: int | None) -> float:
    """Area scaling factor relative to 7nm reference.

    Simplified Dennard/FinFET scaling: area ∝ (node / 7)².
    Defaults to 7nm (1.0x) when process node is not specified.
    """
    if process_nm is None:
        return 1.0
    return (process_nm / 7.0) ** 2


def estimate_router_area(count: int, process_nm: int = 7) -> float:
    """PRD §7.1: Estimate total router area.

    Args:
        count: Number of routers.
        process_nm: Technology node in nanometers.

    Returns:
        Total router area in mm².
    """
    return count * _ROUTER_AREA_7NM * _scale_factor(process_nm)


def estimate_link_area(count: int, data_width: int = 256, process_nm: int = 7) -> float:
    """PRD §7.1: Estimate total link area.

    Args:
        count: Number of links.
        data_width: Link width in bits.
        process_nm: Technology node in nm.

    Returns:
        Total link area in mm².
    """
    width_scale = data_width / 256.0
    return count * _LINK_AREA_REF * width_scale * _scale_factor(process_nm)


def estimate_nic_area(count: int, data_width: int = 256, process_nm: int = 7) -> float:
    """PRD §7.1: Estimate total NIC area.

    Args:
        count: Number of NICs.
        data_width: Interface width in bits.
        process_nm: Technology node in nm.

    Returns:
        Total NIC area in mm².
    """
    width_scale = data_width / 256.0
    return count * _NIC_AREA_7NM * width_scale * _scale_factor(process_nm)


def estimate_fabric_area(
    n_routers: int,
    n_links: int,
    n_nics: int,
    data_width: int = 256,
    process_nm: int = 7,
    has_rcu: bool = False,
    has_mecs: bool = False,
    n_rcu: int = 0,
    n_mecs: int = 0,
) -> dict[str, float]:
    """PRD §7.1: Total fabric area — per-block and total.

    Returns dict with keys: routers_mm2, links_mm2, nics_mm2,
    rcu_mm2, mecs_mm2, total_mm2.
    """
    sf = _scale_factor(process_nm)
    ws = data_width / 256.0
    routers = n_routers * _ROUTER_AREA_7NM * sf
    links = n_links * _LINK_AREA_REF * ws * sf
    nics = n_nics * _NIC_AREA_7NM * ws * sf
    # If has_rcu/mecs but count not specified, default to n_routers
    effective_rcu = n_rcu if n_rcu > 0 else (n_routers if has_rcu else 0)
    effective_mecs = n_mecs if n_mecs > 0 else (n_routers if has_mecs else 0)
    rcu = effective_rcu * _RCU_AREA_7NM * sf
    mecs = effective_mecs * _MECS_AREA_7NM * sf
    total = routers + links + nics + rcu + mecs
    return {
        "routers_mm2": round(routers, 6),
        "links_mm2": round(links, 6),
        "nics_mm2": round(nics, 6),
        "rcu_mm2": round(rcu, 6),
        "mecs_mm2": round(mecs, 6),
        "total_mm2": round(total, 6),
    }


# ══════════════════════════════════════════════════════════════════════════════
# §7.2 — Power Model
# ══════════════════════════════════════════════════════════════════════════════

# Technology parameters at 7nm (canonical: core.constants).
_DEFAULT_VOLTAGE = VOLTAGE_DEFAULT
_CAPACITANCE_PER_BIT_FF = CAPACITANCE_PER_BIT_FF

# Published per-router power at 7nm, ~1GHz, 30% utilization:
#   ARM CMN-600:     ~8-12 mW per mesh port (128-port config)
#   Melia et al.:    ~5-15 mW per 5-stage pipelined router (DAC 2010)
#   TUM survey:      ~10 mW typical for 64-node mesh at 7nm (2022)
# We use a per-router dynamic power model calibrated to these references.
_ROUTER_DYNAMIC_MW_PER_MHZ = ROUTER_DYNAMIC_MW_PER_MHZ  # mW per MHz at 100% activity, 256-bit
_DEFAULT_LEAKAGE_PER_ROUTER_MW = LEAKAGE_PER_ROUTER_MW  # mW per router at 7nm


def estimate_dynamic_power(
    activity_rate: float,
    data_width: int,
    n_hops: float,
    voltage: float = _DEFAULT_VOLTAGE,
    freq_ghz: float = FREQ_DEFAULT_GHZ,
    n_routers: int = 1,
) -> float:
    """PRD §7.2: Dynamic power in watts.

    Uses calibrated per-router model (not first-principles wire capacitance).
    Per-router dynamic power = activity × base_power_per_mhz × freq_mhz
    where base_power is calibrated to published CMN-600 / DAC survey data.

    Args:
        activity_rate: Switching activity [0, 1].
        data_width: Link width in bits (scales base_power linearly).
        n_hops: Average hop count.
        voltage: Supply voltage in V.
        freq_ghz: Clock frequency in GHz.
        n_routers: Number of routers.

    Returns:
        Dynamic power in watts.
    """
    freq_mhz = freq_ghz * 1000
    width_scale = data_width / 256.0  # normalize to 256-bit reference
    # Per-router dynamic power at given activity and frequency
    per_router_mw = activity_rate * _ROUTER_DYNAMIC_MW_PER_MHZ * freq_mhz * width_scale
    router_power = n_routers * per_router_mw * 1e-3  # convert mW → W
    # Add link wire switching (small but real)
    c_link = data_width * _CAPACITANCE_PER_BIT_FF * 1e-15
    link_power = activity_rate * c_link * (voltage ** 2) * (freq_ghz * 1e9) * n_hops
    return router_power + link_power


def estimate_leakage_power(n_routers: int, process_nm: int = 7) -> float:
    """PRD §7.2: Leakage power in watts.

    Leakage scales exponentially with process node, but for the
    7nm reference we use a simple linear approximation from
    published ARM CMN-600 data.
    """
    sf = _scale_factor(process_nm)
    return n_routers * _DEFAULT_LEAKAGE_PER_ROUTER_MW * 1e-3 * sf


def compute_energy_per_bit(data_width: int = 256, avg_hops: float = 4.0) -> float:
    """PRD §8.4: Energy per bit in pJ/bit.

    Typical on-chip NoC: 0.1–1.0 pJ/bit.
    """
    # ENERGY_PER_BIT_PER_HOP (canonical) is the published 7nm NoC reference.
    return ENERGY_PER_BIT_PER_HOP * avg_hops


def estimate_total_power(
    n_routers: int,
    data_width: int,
    activity_rate: float,
    avg_hops: float,
    voltage: float = _DEFAULT_VOLTAGE,
    freq_ghz: float = FREQ_DEFAULT_GHZ,
    process_nm: int = 7,
) -> dict[str, float]:
    """PRD §7.2: Total power — dynamic + leakage.

    Returns dict with keys: dynamic_w, leakage_w, total_w.
    """
    dyn = estimate_dynamic_power(
        activity_rate, data_width, avg_hops, voltage, freq_ghz, n_routers=n_routers,
    )
    leak = estimate_leakage_power(n_routers, process_nm)
    total = dyn + leak
    return {
        "dynamic_w": round(dyn, 4),
        "leakage_w": round(leak, 4),
        "total_w": round(total, 4),
    }


# ══════════════════════════════════════════════════════════════════════════════
# §7.3 — Timing Model
# ══════════════════════════════════════════════════════════════════════════════

# Canonical timing knobs live in core.constants; aliases kept for backward compat.
_ROUTER_STAGE_DELAY_PS = ROUTER_STAGE_DELAY_PS

_WIRE_DELAY_PS_PER_MM = WIRE_DELAY_PS_PER_MM

_TOPO_WIRE_MM = TOPO_WIRE_MM


def router_pipeline_stages() -> list[dict[str, Any]]:
    """PRD §7.3: Router pipeline stages with delays.

    Returns list of dicts with keys: name, delay_ps.
    """
    return [
        {"name": name, "delay_ps": delay}
        for name, delay in _ROUTER_STAGE_DELAY_PS.items()
    ]


def estimate_critical_path_ps(
    topology: str = "mesh",
    process_nm: int = 7,
    data_width: int = 256,
) -> float:
    """PRD §7.3: Critical path delay in picoseconds.

    Critical path = sum of router pipeline stages + wire delay
    for one hop.
    """
    sf = _scale_factor(process_nm)
    # Router pipeline delay (sum of all stages)
    router_delay = sum(_ROUTER_STAGE_DELAY_PS.values()) * sf
    # Wire delay per hop
    wire_mm = _TOPO_WIRE_MM.get(topology, 0.5)
    wire_delay = wire_mm * _WIRE_DELAY_PS_PER_MM
    return router_delay + wire_delay


# Derating factor: real Fmax = ideal Fmax × derating.
# Accounts for clock skew, setup/hold margins, IR drop, PVT variation.
# Reference: Synopsys timing closure reports for 7nm NoC designs.
# Canonical: core.constants FMAX_DERATING (alias kept for backward compat).
_FMAX_DERATING = FMAX_DERATING


def estimate_max_frequency(
    topology: str = "mesh",
    process_nm: int = 7,
    data_width: int = 256,
    derated: bool = True,
) -> float:
    """PRD §7.3: Maximum frequency in MHz.

    Args:
        topology: Topology type.
        process_nm: Technology node.
        data_width: Link width.
        derated: If True, apply realistic derating. If False, return ideal.

    Returns:
        Fmax in MHz. Ideal (upper bound) if derated=False,
        realistic if derated=True.
    """
    cp_ps = estimate_critical_path_ps(topology, process_nm, data_width)
    if cp_ps <= 0:
        return 1000.0
    fmax_ghz = 1.0 / (cp_ps * 1e-12) / 1e9
    fmax_mhz = fmax_ghz * 1000
    if derated:
        fmax_mhz *= _FMAX_DERATING
    return round(fmax_mhz, 0)  # MHz


# ══════════════════════════════════════════════════════════════════════════════
# §7 — Full Report Generation
# ══════════════════════════════════════════════════════════════════════════════

def generate_report(
    cr: CompileRequest,
    sim_result: dict[str, Any] | None = None,
    activity_rate: float = 0.3,
    n_edges: int | None = None,
) -> dict[str, Any]:
    """PRD §7: Generate complete report from CompileRequest + sim result.

    Args:
        cr: The CompileRequest (provides agent counts, topology, physical ctx).
        sim_result: Simulation result dict (may be None if no trace provided).
        activity_rate: Assumed switching activity for power estimation.
        n_edges: Actual edge count from topology (if known). If None, estimated.

    Returns:
        Report dict with area, power, timing, guardrail_hash.
    """
    if sim_result is None:
        sim_result = {"latency_mean": 0.0, "hops": 4.0, "throughput": 0.0}
    n_agents = sum(a.count for a in cr.agents)
    n_routers = n_agents  # simplified: one router per agent
    n_nics = n_agents
    data_width = cr.physical.default_data_width
    process_nm = cr.physical.process_node_nm
    freq_ghz = cr.physical.default_clock_freq_mhz / 1000.0

    # Determine topology from NocConfig
    topo_name = "mesh"
    if cr.noc_config.topology_family:
        topo_name = cr.noc_config.topology_family.value

    # Link count — use actual if provided, otherwise estimate
    if n_edges is not None:
        n_links = n_edges
    elif topo_name in ("mesh", "torus"):
        k = n_routers ** 0.5
        n_links = int(2 * k * (k - 1)) if k == int(k) else 2 * n_routers
    else:
        n_links = 2 * n_routers  # rough default

    # Area
    has_rcu = cr.noc_config.rcu_enabled or False
    area = estimate_fabric_area(
        n_routers=n_routers, n_links=n_links, n_nics=n_nics,
        data_width=data_width, process_nm=process_nm,
        has_rcu=has_rcu, n_rcu=n_agents if has_rcu else 0,
    )

    # Power
    avg_hops = sim_result.get("hops", 4.0)
    power = estimate_total_power(
        n_routers=n_routers, data_width=data_width,
        activity_rate=activity_rate, avg_hops=avg_hops,
        voltage=_DEFAULT_VOLTAGE, freq_ghz=freq_ghz, process_nm=process_nm,
    )

    # Timing — derated Fmax (realistic) and ideal Fmax (upper bound)
    fmax_derated = estimate_max_frequency(topo_name, process_nm, data_width, derated=True)
    fmax_ideal = estimate_max_frequency(topo_name, process_nm, data_width, derated=False)
    cp_ps = estimate_critical_path_ps(topo_name, process_nm, data_width)
    stages = router_pipeline_stages()

    # Energy
    e_per_bit = compute_energy_per_bit(data_width, avg_hops)

    report: dict[str, Any] = {
        "area": area,
        "power": power,
        "timing": {
            "max_freq_mhz": fmax_derated,
            "max_freq_ideal_mhz": fmax_ideal,
            "critical_path_ps": round(cp_ps, 1),
            "pipeline_stages": len(stages),
            "derating_factor": _FMAX_DERATING,
        },
        "energy": {
            "per_bit_pj": round(e_per_bit, 3),
        },
        "guardrail_hash": cr.guardrail_hash(),
        # Accuracy notes (PRD §7 — honest limitations)
        "accuracy_notes": {
            "area": "±30% relative accuracy. Good for A vs B comparison, not tape-out.",
            "power": "Includes link + router internal activity. No process corners or thermal.",
            "timing": f"Derated Fmax (×{_FMAX_DERATING}). Needs STA for guaranteed frequency.",
            "energy": "Order-of-magnitude. Based on 0.15 pJ/bit/hop reference.",
        },
    }

    # Include simulation results if provided
    if sim_result:
        report["simulation"] = sim_result

    # Collective sizing block (PRD §5.2 Level B — estimates, not sign-off).
    # Incast buffer note: worst-case concurrent arrivals at one port ≈
    # incast_degree × packet_size flits (canonical: BOOKSIM_DEFAULTS in
    # core.constants, currently 8). A fabric absorbing full-fan-in bursts
    # without backpressure needs vc_buf at or above that; below it, expect
    # the saturation seen in trace replay.
    # Hypercast estimate: alltoall/allgather among G ranks takes G*(G-1)
    # unicast messages vs G hardware-multicast messages, saving G*(G-2).
    from ..model.compile_model import collective_vc_floor, collective_vc_map
    colls = list(cr.workload.collectives)
    multi = [c for c in colls if c.group_size > 1]
    max_incast = max((c.group_size for c in multi), default=0)
    hypercast_saved = {
        f"{c.kind.value}/{c.group_size}": c.group_size * (c.group_size - 2)
        for c in multi
        if c.kind.value in ("alltoall", "allgather") and c.group_size > 2
    }
    # Ring-algorithm phase estimates for reduce collectives: a ring
    # allreduce/reducescatter over G ranks takes 2*(G-1) phases. Assumes the
    # ring algorithm (bandwidth-optimal, latency-suboptimal); a tree or
    # in-network-compute collapse is NOT modeled — see note below.
    ring_phases = {
        f"{c.kind.value}/{c.group_size}": 2 * (c.group_size - 1)
        for c in multi
        if c.kind.value in ("allreduce", "reducescatter") and c.group_size > 1
    }
    # Multicast group fit vs the GUIDED hardware knobs (None = ideal).
    mcast_kinds = ("alltoall", "allgather", "broadcast")
    mcast_need = [c for c in multi if c.kind.value in mcast_kinds]
    mcast_groups = cr.noc_config.mcast_groups
    mcast_setup = cr.noc_config.mcast_setup_cycles
    mcast_fallback = (
        max(0, len(mcast_need) - mcast_groups) if mcast_groups is not None
        else 0
    )
    setup_cost = (
        len(mcast_need) * mcast_setup
        if mcast_setup is not None else None
    )
    report["collectives"] = {
        "contexts": [
            {"kind": c.kind.value, "group_size": c.group_size,
             "bytes_per_element": c.bytes_per_element}
            for c in colls
        ],
        "vc_floor": collective_vc_floor(tuple(colls)),
        "collective_vc_map": collective_vc_map(tuple(colls)),
        "max_incast_degree": max_incast,
        "recommended_vc_buf_note": (
            f"Full-fan-in absorption needs vc_buf >= {max_incast * BOOKSIM_DEFAULTS['packet_size']} flits "
            f"({max_incast} ranks x {BOOKSIM_DEFAULTS['packet_size']}-flit packets); below this, size for "
            f"backpressure tolerance, not losslessness. Estimate only."
            if max_incast else "No multi-rank collectives — no incast sizing."
        ),
        "hypercast_messages_saved_estimate": hypercast_saved,
        "hypercast_note": (
            "Message counts only (G*(G-1) unicast vs G multicast). Excludes "
            "group-setup latency and the N-1→1 phase collapse from "
            "in-network compute — both unmodeled. Do not quote as speedup."
            if hypercast_saved else "No alltoall/allgather with G>2."
        ),
        "ring_phases_estimate": ring_phases,
        "ring_note": (
            "Phase counts assume the ring algorithm, 2*(G-1) phases per "
            "collective. Bandwidth-optimal but latency-suboptimal; tree and "
            "in-network-compute collapses unmodeled. Phase counts, not time."
            if ring_phases else "No allreduce/reducescatter with G>1."
        ),
        "multicast_groups_required": len(mcast_need),
        "multicast_groups_available": mcast_groups,
        "multicast_fallback_to_unicast": mcast_fallback,
        "multicast_setup_cost_cycles_estimate": setup_cost,
        "multicast_note": (
            "One group per multicast collective context; excess contexts "
            "fall back to unicast (slower, still correct). Setup cost = "
            "contexts × mcast_setup_cycles; dynamic reconfiguration during "
            "expert routing unmodeled. None-valued knobs mean ideal "
            "multicast was assumed."
        ),
    }

    # Validation / VC assignment info (PRD §13 — all stages in report)
    from ..model.compile_model import derive_vc_assignment, verify_design, generate_artifacts
    va = derive_vc_assignment(cr)
    report["vc_assignment"] = {
        "vc_count": va.vc_count,
        "routing_function": va.routing_function,
        "per_class_vc": va.per_class_vc,
        "turn_restrictions": list(va.turn_restrictions),
    }
    report["validation"] = {
        "ok": True,
        "vc_count": va.vc_count,
        "total_nodes": n_agents,
    }

    # Verification stage (PRD §13.5 — F1-F8 checks)
    vr = verify_design(cr, topology_name=topo_name)
    report["verification"] = {
        "ok": vr.ok,
        "checks": vr.checks,
        "errors": vr.errors,
    }

    # Generate stage (PRD §13.6 — artifact tracking)
    artifacts = generate_artifacts(cr)
    report["artifacts"] = [a.to_dict() for a in artifacts]

    return report

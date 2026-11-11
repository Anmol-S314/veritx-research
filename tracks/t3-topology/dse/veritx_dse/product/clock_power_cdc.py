from __future__ import annotations
from dataclasses import dataclass
GEC_HYBRID_NUM_VCS = 6
GEC_HYBRID_FLITS_PER_VC = 8
GEC_HYBRID_BUFFER_FLITS = 48
GEC_HYBRID_CREDIT_RETURN_LATENCY_CYCLES = 1
GEC_HYBRID_VC_ALLOC_DELAY = 1
GEC_HYBRID_SWITCH_ALLOC_DELAY = 1
GEC_HYBRID_SWITCH_TRAVERSAL_CYCLES = 1
GEC_HYBRID_ROUTING_DELAY = 1
GEC_HYBRID_OUTPUT_STAGE_DEPTH = 1
GEC_HYBRID_BUFFER_ORGANIZATION = "per_input_port_per_vc"
GEC_HYBRID_FLOW_CONTROL = "credit"
@dataclass(frozen=True)
class GecHybridCreditPin:
    num_vcs: int = GEC_HYBRID_NUM_VCS
    flits_per_vc: int = GEC_HYBRID_FLITS_PER_VC
    buffer_flits: int = GEC_HYBRID_BUFFER_FLITS
    credit_return_latency_cycles: int = GEC_HYBRID_CREDIT_RETURN_LATENCY_CYCLES
    vc_alloc_delay: int = GEC_HYBRID_VC_ALLOC_DELAY
    switch_alloc_delay: int = GEC_HYBRID_SWITCH_ALLOC_DELAY
    switch_traversal_cycles: int = GEC_HYBRID_SWITCH_TRAVERSAL_CYCLES
    routing_delay: int = GEC_HYBRID_ROUTING_DELAY
    def to_dict(self):
        return {"num_vcs": self.num_vcs, "flits_per_vc": self.flits_per_vc, "buffer_flits": self.buffer_flits, "credit_return_latency_cycles": self.credit_return_latency_cycles, "vc_alloc_delay": self.vc_alloc_delay, "switch_alloc_delay": self.switch_alloc_delay, "switch_traversal_cycles": self.switch_traversal_cycles, "routing_delay": self.routing_delay, "output_stage_depth_flits_per_vc": GEC_HYBRID_OUTPUT_STAGE_DEPTH, "buffer_organization": GEC_HYBRID_BUFFER_ORGANIZATION, "flow_control": GEC_HYBRID_FLOW_CONTROL}
def gec_hybrid_credit_pin():
    return GecHybridCreditPin()
def gec_hybrid_credit_pin_from_behavior(num_vcs, flits_per_vc, credit_return_latency_cycles):
    if type(num_vcs) is not int or num_vcs != GEC_HYBRID_NUM_VCS:
        raise ValueError("GEC_HYBRID_CREDIT_OBSERVABILITY_CONTRACT_UNVERIFIED: num_vcs must be 6")
    if type(flits_per_vc) is not int or flits_per_vc != GEC_HYBRID_FLITS_PER_VC:
        raise ValueError("GEC_HYBRID_CREDIT_OBSERVABILITY_CONTRACT_UNVERIFIED: flits_per_vc must be 8")
    if type(credit_return_latency_cycles) is not int or credit_return_latency_cycles != GEC_HYBRID_CREDIT_RETURN_LATENCY_CYCLES:
        raise ValueError("GEC_HYBRID_CREDIT_OBSERVABILITY_CONTRACT_UNVERIFIED: credit_return_latency_cycles must be 1")
    return GecHybridCreditPin()
def hybrid_used_credit(occupancy_per_vc):
    total = 0
    for value in tuple(occupancy_per_vc):
        if type(value) is not int or value < 0:
            raise ValueError("occupancy per vc must be exact int >= 0")
        total = total + value
    if total < 0 or total > GEC_HYBRID_BUFFER_FLITS:
        raise ValueError("occupancy total outside pinned buffer")
    return total
def hybrid_used_credit_mesh(occupancy_per_vc):
    return hybrid_used_credit(occupancy_per_vc)
def hybrid_used_credit_tap(occupancy_per_vc):
    return hybrid_used_credit(occupancy_per_vc)
def hybrid_credit_visible_cycle(pop_cycle):
    if type(pop_cycle) is not int or pop_cycle < 0:
        raise ValueError("pop_cycle must be exact int >= 0")
    return pop_cycle + GEC_HYBRID_CREDIT_RETURN_LATENCY_CYCLES
def hybrid_select(mesh_credit, mecs_credit, mesh_hops):
    if type(mesh_credit) is not int or mesh_credit < 0 or mesh_credit > GEC_HYBRID_BUFFER_FLITS:
        raise ValueError("mesh_credit outside pinned buffer")
    if type(mecs_credit) is not int or mecs_credit < 0 or mecs_credit > GEC_HYBRID_BUFFER_FLITS:
        raise ValueError("mecs_credit outside pinned buffer")
    if type(mesh_hops) is not int or mesh_hops < 1 or mesh_hops > 3:
        raise ValueError("mesh_hops must be 1..3")
    if mesh_credit * mesh_hops < mecs_credit:
        return "mesh"
    return "mecs"
def hybrid_native_choice(mesh_credit, mecs_credit, mesh_hops):
    mesh_cost = mesh_credit * mesh_hops
    mecs_cost = mecs_credit
    if mesh_cost < mecs_cost:
        return "mesh"
    return "mecs"
def hybrid_peer_index(coord, dest_coord):
    if dest_coord < coord:
        return dest_coord
    return dest_coord - 1
def hybrid_mesh_hops(coord, dest_coord):
    if dest_coord >= coord:
        return dest_coord - coord
    return coord - dest_coord
def hybrid_credit_bindings(k=4, c=1, o=1, d=3, num_vcs=6):
    if type(k) is not int or k != 4:
        raise ValueError("hybrid credit bindings need k=4")
    if type(c) is not int or c != 1:
        raise ValueError("hybrid credit bindings need c=1")
    if type(o) is not int or o != 1:
        raise ValueError("hybrid credit bindings need o=1")
    if type(d) is not int or d != 3:
        raise ValueError("hybrid credit bindings need d=3")
    if type(num_vcs) is not int or num_vcs != GEC_HYBRID_NUM_VCS:
        raise ValueError("hybrid credit bindings need num_vcs=6")
    half = int(num_vcs / 2)
    rows = []
    for router in range(k * k):
        rows.append((router, "mesh_west", -1, 0, half - 1))
        rows.append((router, "mesh_east", -1, 0, half - 1))
        rows.append((router, "mesh_north", -1, half, num_vcs - 1))
        rows.append((router, "mesh_south", -1, half, num_vcs - 1))
        for tap in range(d):
            rows.append((router, "row_mecs", tap, tap, tap))
            rows.append((router, "col_mecs", tap, half + tap, half + tap))
    return tuple(rows)
def gec_hybrid_differential_cases():
    cases = []
    for mesh_credit in range(0, 9):
        for mecs_credit in range(0, 9):
            for mesh_hops in (1, 2, 3):
                cases.append((mesh_credit, mecs_credit, mesh_hops))
    for mesh_credit in (0, 1, 7, 8, 16, 24, 48):
        for mecs_credit in (0, 1, 7, 8, 16, 24, 48):
            for mesh_hops in (1, 2, 3):
                cases.append((mesh_credit, mecs_credit, mesh_hops))
    return tuple(sorted(set(cases)))
def gec_hybrid_check_differential():
    for mesh_credit, mecs_credit, mesh_hops in gec_hybrid_differential_cases():
        pinned = hybrid_select(mesh_credit, mecs_credit, mesh_hops)
        native = hybrid_native_choice(mesh_credit, mecs_credit, mesh_hops)
        if pinned != native:
            raise ValueError("hybrid selector differential mismatch")
    return True

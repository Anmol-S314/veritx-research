#!/usr/bin/env python3
"""noc_requirements.py — P1: Typed requirement spec + translation layer.

Defines the structured requirement schema that a customer (or LLM intake)
fills in. The translation layer converts these high-level requirements into
the internal bandwidth/traffic model our DSE engine consumes.

Customer never uploads a matrix — it's DERIVED from their requirements via
progressive disclosure:

  Requirements → (translation) → Traffic Model → (DSE) → Topology + Config

The schema covers:
  * Flows: {src, dst, protocol, R/W_BW, latency_budget, QoS_class, order}
  * Budgets: {area, power, VC, radix, link}
  * Physical: {CDC, floorplan, tiling}
  * Reliability: {ECC, safety}
  * Verification intent

Usage:
  # Create a requirement programmatically
  from noc_requirements import NoCRequirement, RequirementSet
  req = NoCRequirement(
      name="Qwen3-30B MoE dispatch",
      n_nodes=64,
      flows=[FlowSpec(src=0, dst="all", protocol="AXI4", bw_bytes=64)],
      budgets=BudgetSpec(area_um2=1e6, power_mw=500, max_vcs=8, max_radix=6),
  )
  traffic_model = req.translate()

  # Or from JSON
  reqset = RequirementSet.from_json("customer_reqs.json")
  for req in reqset.requirements:
      tm = req.translate()
"""
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ── Flow specification ────────────────────────────────────────────────────────

@dataclass
class FlowSpec:
    """One communication flow in the system."""
    src: int | str             # node id or "all" for broadcast-like
    dst: int | str             # node id, "all", or "nearest_k:<k>"
    protocol: str = "AXI4"     # AXI4, TileLink, custom
    bw_bytes: int = 64         # bytes per transfer (flit size)
    bw_per_cycle: float = 1.0  # bytes/cycle this flow needs
    latency_budget: int = 1000 # max acceptable latency in cycles
    qos_class: str = "BE"      # GS (guaranteed service) or BE (best effort)
    order: str = "none"        # none, src_ordered, total
    pattern: str = "unicast"   # unicast, multicast, broadcast
    fanout: int = 1            # for multicast: number of destinations
    burstiness: float = 1.0    # peak/mean injection ratio
    temporal: Optional[Dict] = None  # e.g., {"phase": "dispatch", "start": 0, "end": 1000}

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items() if v is not None}


# ── Budget specification ──────────────────────────────────────────────────────

@dataclass
class BudgetSpec:
    """Physical and resource budgets."""
    area_um2: Optional[float] = None          # total area budget (µm²)
    power_mw: Optional[float] = None          # total power budget (mW)
    max_vcs: int = 8                          # maximum VCs per port
    max_radix: int = 6                        # maximum router radix
    max_link_width_bytes: int = 64            # link width in bytes
    max_hops: Optional[int] = None            # max path length
    max_diameter: Optional[int] = None        # network diameter
    link_length_um: Optional[float] = None    # max link length (µm)
    technology_node: int = 7                  # nm (for area/power estimates)


# ── Physical specification ────────────────────────────────────────────────────

@dataclass
class PhysicalSpec:
    """Physical implementation constraints."""
    clock_domains: int = 1
    cdc_scheme: str = "synchronous"           # synchronous, mesochronous, GALS
    floorplan: Optional[Dict] = None          # e.g., {"rows": 4, "cols": 4}
    tiling: str = "grid"                      # grid, interposer, chiplet
    packaging: str = "2.5D"                   # 2D, 2.5D (interposer), 3D


# ── Reliability specification ─────────────────────────────────────────────────

@dataclass
class ReliabilitySpec:
    """Reliability and safety requirements."""
    ecc: bool = False                         # error-correcting codes on links
    safety_level: Optional[str] = None        # ASIL-B, ASIL-D, none
    redundancy: str = "none"                  # none, TMR, spare links
    mtbf_hours: Optional[float] = None


# ── Verification intent ───────────────────────────────────────────────────────

@dataclass
class VerificationIntent:
    """What verification the customer expects."""
    deadlock_check: bool = True
    formal_proofs: bool = False
    cycle_accurate_sim: bool = True
    assertion_coverage: Optional[float] = None  # target %
    test_vectors: Optional[int] = None


# ── Main requirement ──────────────────────────────────────────────────────────

@dataclass
class NoCRequirement:
    """Complete NoC requirement specification."""
    name: str
    n_nodes: int
    flows: List[FlowSpec] = field(default_factory=list)
    budgets: BudgetSpec = field(default_factory=BudgetSpec)
    physical: PhysicalSpec = field(default_factory=PhysicalSpec)
    reliability: ReliabilitySpec = field(default_factory=ReliabilitySpec)
    verification: VerificationIntent = field(default_factory=VerificationIntent)
    description: str = ""

    def translate(self) -> Dict[str, Any]:
        """Translate requirements into the internal traffic model.
        
        Returns a dict compatible with our DSE engine's expectations:
        - traffic_matrix: N x N numpy-like list
        - injection_rate: estimated average
        - phase_list: temporal phases (if specified)
        - topology_constraints: from budgets
        """
        n = self.n_nodes
        
        # 1. Build traffic matrix from flows
        matrix = [[0.0] * n for _ in range(n)]
        total_bytes = 0
        for flow in self.flows:
            bw = flow.bw_per_cycle * flow.bw_bytes
            if flow.src == "all" or flow.dst == "all":
                # Broadcast/all-to-all: distribute across all pairs
                srcs = list(range(n)) if flow.src == "all" else [flow.src]
                dsts = list(range(n)) if flow.dst == "all" else [flow.dst]
                per_pair_bw = bw / max(len(srcs) * len(dsts), 1)
                for s in srcs:
                    for d in dsts:
                        if s != d and s < n and d < n:
                            matrix[s][d] += per_pair_bw
                            total_bytes += per_pair_bw
            elif isinstance(flow.dst, str) and flow.dst.startswith("nearest_k:"):
                k = int(flow.dst.split(":")[1])
                # Nearest k neighbors (placeholder — real impl needs topology)
                for d in range(min(k, n)):
                    if d != flow.src and flow.src < n:
                        matrix[flow.src][d] += bw / k
                        total_bytes += bw / k
            else:
                s, d = int(flow.src), int(flow.dst)
                if 0 <= s < n and 0 <= d < n and s != d:
                    matrix[s][d] += bw
                    total_bytes += bw
        
        # 2. Normalize to injection rate
        max_row_sum = max(sum(row) for row in matrix) if matrix else 1.0
        if max_row_sum > 0:
            injection_rate = min(max_row_sum / (n * self.budgets.max_link_width_bytes), 1.0)
        else:
            injection_rate = 0.08  # default
        
        # 3. Extract temporal phases
        phases = []
        for flow in self.flows:
            if flow.temporal:
                phases.append({
                    "name": flow.temporal.get("phase", "default"),
                    "start": flow.temporal.get("start", 0),
                    "end": flow.temporal.get("end", 1000),
                    "src": flow.src,
                    "dst": flow.dst,
                })
        
        # 4. Topology constraints
        topo_constraints = {
            "n_nodes": n,
            "max_radix": self.budgets.max_radix,
            "max_vcs": self.budgets.max_vcs,
            "max_hops": self.budgets.max_hops,
            "layout": self.physical.tiling,
        }
        
        return {
            "name": self.name,
            "traffic_matrix": matrix,
            "injection_rate": round(injection_rate, 4),
            "total_bytes": total_bytes,
            "n_phases": len(phases),
            "phases": phases,
            "topology_constraints": topo_constraints,
            "qos_classes": list(set(f.qos_class for f in self.flows)),
            "protocols": list(set(f.protocol for f in self.flows)),
        }
    
    def to_dict(self):
        return {
            "name": self.name,
            "n_nodes": self.n_nodes,
            "description": self.description,
            "flows": [f.to_dict() for f in self.flows],
            "budgets": self.budgets.__dict__,
            "physical": self.physical.__dict__,
            "reliability": self.reliability.__dict__,
            "verification": self.verification.__dict__,
        }
    
    @classmethod
    def from_dict(cls, d: Dict) -> "NoCRequirement":
        flows = [FlowSpec(**f) for f in d.get("flows", [])]
        budgets = BudgetSpec(**d.get("budgets", {}))
        physical = PhysicalSpec(**d.get("physical", {}))
        reliability = ReliabilitySpec(**d.get("reliability", {}))
        verification = VerificationIntent(**d.get("verification", {}))
        return cls(
            name=d["name"], n_nodes=d["n_nodes"], flows=flows,
            budgets=budgets, physical=physical, reliability=reliability,
            verification=verification, description=d.get("description", ""),
        )


# ── Requirement set (multiple requirements for ensemble) ──────────────────────

@dataclass
class RequirementSet:
    """Collection of requirements — for ensemble evaluation."""
    requirements: List[NoCRequirement] = field(default_factory=list)
    
    @classmethod
    def from_json(cls, path: str) -> "RequirementSet":
        data = json.loads(Path(path).read_text())
        reqs = [NoCRequirement.from_dict(r) for r in data.get("requirements", [data])]
        return cls(requirements=reqs)
    
    def translate_all(self) -> List[Dict]:
        return [r.translate() for r in self.requirements]


# ── LLM intake helper ────────────────────────────────────────────────────────

LLM_INTAKE_PROMPT = """You are a NoC design assistant. Given a user's description of their
communication needs, extract a structured NoCRequirement JSON.

Key fields to extract:
- n_nodes: total processing elements
- flows: list of {src, dst, bw_bytes, latency_budget, qos_class, protocol}
- budgets: {area_um2, power_mw, max_vcs, max_radix}
- physical: {tiling, clock_domains, cdc_scheme}

Output valid JSON matching the NoCRequirement schema.
Example input: "64 NPUs doing MoE dispatch with 64-byte flits, need <500 cycle latency"
"""


def demo_qwen_requirement():
    """Create a demo requirement matching the Qwen3-30B MoE workload."""
    return NoCRequirement(
        name="Qwen3-30B-A3B MoE dispatch",
        n_nodes=64,
        description="64-NPU MoE dispatch + allreduce for Qwen3-30B-A3B. "
                    "Expert parallelism=8, so dispatch sends 1/8 of tokens to each expert group. "
                    "Allreduce follows for gradient sync.",
        flows=[
            FlowSpec(src="all", dst="all", protocol="AXI4", bw_bytes=64,
                     bw_per_cycle=0.016, latency_budget=500, qos_class="BE",
                     pattern="multicast", fanout=8, burstiness=2.0,
                     temporal={"phase": "dispatch", "start": 0, "end": 5000}),
            FlowSpec(src="all", dst="all", protocol="AXI4", bw_bytes=64,
                     bw_per_cycle=0.016, latency_budget=1000, qos_class="BE",
                     pattern="unicast", burstiness=1.0,
                     temporal={"phase": "allreduce", "start": 5000, "end": 10000}),
        ],
        budgets=BudgetSpec(
            area_um2=5e6, power_mw=2000, max_vcs=8, max_radix=6,
            max_link_width_bytes=64, technology_node=7,
        ),
        physical=PhysicalSpec(
            clock_domains=1, tiling="grid", packaging="2.5D",
            floorplan={"rows": 8, "cols": 8},
        ),
        reliability=ReliabilitySpec(ecc=True, safety_level=None),
        verification=VerificationIntent(
            deadlock_check=True, cycle_accurate_sim=True,
        ),
    )


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="print demo Qwen3 requirement")
    ap.add_argument("--json", default=None, help="load requirement from JSON")
    ap.add_argument("--translate", action="store_true", help="translate and print traffic model")
    ap.add_argument("--out", default=None, help="save translated traffic model")
    args = ap.parse_args()

    if args.demo:
        req = demo_qwen_requirement()
        print(json.dumps(req.to_dict(), indent=2))
        if args.translate:
            tm = req.translate()
            print("\n--- Translated Traffic Model ---")
            print(json.dumps({k: v for k, v in tm.items() if k != "traffic_matrix"}, indent=2))
            # Save matrix
            if args.out:
                mat_path = Path(args.out)
                with open(mat_path, "w") as f:
                    f.write(f"# Generated from requirement: {req.name}\n")
                    for row in tm["traffic_matrix"]:
                        f.write(" ".join(f"{v:.6f}" for v in row) + "\n")
                print(f"matrix -> {mat_path}")
    elif args.json:
        reqset = RequirementSet.from_json(args.json)
        for req in reqset.requirements:
            print(f"\nRequirement: {req.name}")
            if args.translate:
                tm = req.translate()
                print(json.dumps({k: v for k, v in tm.items() if k != "traffic_matrix"}, indent=2))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()

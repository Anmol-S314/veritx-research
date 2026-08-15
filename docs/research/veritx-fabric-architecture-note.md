# VeritX Fabric Architecture — data plane / control plane / telemetry-compiler

Status: **NOTED, not designed** (Dave, 2026-08-15, user request). Product
vision for the VeritX Fabric. This is the "self-adapting NoC" thesis the
research supports; NOT a current paper claim.

## The idea (user's framing, 2026-08-15)

Three layers + a compiler/telemetry layer, so the NoC can **adapt and learn
from any and all traffic**:

| Layer | Function | What we already have |
|---|---|---|
| **Data plane** | Moves flits — routers, VCs, bridge | The 2-die RTL, verified 154/154 per-flit |
| **Control plane** | Physically separated from data; carries policy/config | Our plane-separation result IS this: burstiness starves control 6.68× at 1 VC → control must be physical, not virtual |
| **Telemetry/compiler** | Observes traffic, learns, configures the data plane | The trace pipeline (LLMServingSim → Chakra → matrices) IS telemetry: it derives policy — the placement law, D(G) law, VC/buffer configs |

## The honest cautions (recorded, not resolved)

1. **Not novel as a vision** — Intel (Sapphire Rapids NoC telemetry),
   NVIDIA (NVLink/InfiniBand adaptive routing + telemetry), AMD have shipped
   pieces. What's unclaimed: **a credibility-verified adaptive fabric** —
   every adaptation ships with proof (the VeritX mark). That's the
   differentiation and the moat.
2. **Adaptive routing + deadlock freedom is the classic trap.** Adapt
   PARAMETERS (VC allocation, fork placement, buffer config) under FIXED
   routing — config-level adaptation, not path-level, until the RTL gate
   proves otherwise. The placement law is the model: a compiler output that
   the gate verified.
3. **Scope.** Ten-year product, not the paper. The paper's method section
   can frame it as "the measured foundation of a self-adapting fabric":
   plane separation (control plane) + placement law (first compiler output)
   + trace pipeline (telemetry layer).

## Reference points

- FlooNoC (Fischer/Benini): already two logical networks (narrow control +
  wide data) on three physical planes — the industry's control/data split.
- MONET (DATE 2026): MoE NoC with segregated control/token routing.
- Preemptive VC (arXiv 2607.01430, 2026): the deadlock-freedom toolkit for
  adaptive-ish designs.
- Our paper_draft.md claim-scope section: network-level demand reduction
  claimable, end-to-end serving NOT (yet).

## Next (if pursued)

Write as an ADR in docs/adr/ + a section in docs/business/company-vision.md
("the platform underneath"). The paper should cite the three-plane framing
only as motivation, not as a contribution.

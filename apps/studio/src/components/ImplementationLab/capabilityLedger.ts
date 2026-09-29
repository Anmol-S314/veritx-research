// *
// Rationale: docs/decisions/studio.md

/** §44 feature status vocabulary. Nothing is ever simply hidden. */
export const MATURITIES = [
  'AVAILABLE',
  'EXPERIMENTAL',
  'RESEARCH',
  'HISTORICAL',
  'BLOCKED',
  'NOT APPLICABLE',
] as const;

export type Maturity = (typeof MATURITIES)[number];

/** The eight explorer columns (§32). Short cell vocabulary. */
export type StageCell = string;

export interface CapabilityRecord {
  id: string;
  name: string;
  maturity: Maturity;
  /** Why this maturity — one line, no invented authority. */
  maturityNote: string;
  stages: {
    intent: StageCell;
    artifact: StageCell;
    verifier: StageCell;
    projection: StageCell;
    executable: StageCell;
    qualified: StageCell;
    product: StageCell;
    evidence: StageCell;
  };
  whatItIs: string;
  implementation: string[];
  historicalEvidence: string[];
  missingBridge: string;
  actions: { label: string; detail: string }[];
}

export const MATURITY_BLURB: Record<Maturity, string> = {
  AVAILABLE: 'fully product-wired for this design',
  EXPERIMENTAL: 'canonical path exists but qualification is limited',
  RESEARCH: 'implementation exists but the canonical/product bridge is incomplete',
  HISTORICAL: 'recorded implementation/results exist outside the current path',
  BLOCKED: 'the design asks for a capability that cannot proceed at a specific stage',
  'NOT APPLICABLE': 'the question does not apply to this design',
};

/** Full 28-record archaeology mirror. Order follows the yaml. */
export const CAPABILITIES: CapabilityRecord[] = [
  {
    id: 'BOOKSIM-LATENCY-PARSER',
    name: 'BookSim stdout stats parser (honest latency + percentiles)',
    maturity: 'AVAILABLE',
    maturityNote: 'CURRENT_CANONICAL + CURRENT_QUALIFIED; consumed by the certified path',
    stages: { intent: 'YES', artifact: 'YES', verifier: 'YES (25 tests)', projection: 'N/A — IS the result reader', executable: 'YES', qualified: 'YES', product: 'YES', evidence: 'YES' },
    whatItIs: 'Honest BookSim output parser: honest latency (never a warmed-up-window average), percentiles, max packet latency, max node, fail-loud trace errors.',
    implementation: ['tracks/t3-topology/dse/veritx_dse/simulation/booksim.py::parse_output', 'called by backend/booksim.py::_execute_prepared'],
    historicalEvidence: ['BAKE-OFF-REPRODUCIBILITY.md verified latencies: mesh_8x8 23.38c, custom_anynet 23.20c, flatfly_8x8 20.38c — HISTORICAL MEASUREMENT'],
    missingBridge: 'none after this tranche',
    actions: [{ label: 'Inspect evidence', detail: 'Every BookSim run carries route_dump_sha256 + parsed metrics in backend-evidence.json.' }],
  },
  {
    id: 'GEC-MESH',
    name: 'GEC nearest-neighbour mesh mode',
    maturity: 'RESEARCH',
    maturityNote: 'CURRENT_BACKEND_ONLY + HISTORICAL_MEASURED; intent exists, materializer missing (PHASE D)',
    stages: { intent: 'INTENT ONLY', artifact: 'NO', verifier: 'NO', projection: 'backend-native only', executable: 'YES (outside canonical path)', qualified: 'NO', product: 'NO', evidence: 'NO' },
    whatItIs: 'GEC nearest-neighbour mesh mode (mesh=1): express partitioning does not apply. NOT assumed equivalent to ordinary mesh without proof.',
    implementation: ['third_party/booksim2/src/networks/gec.cpp (mesh mode)', 'model/topology_intent.py GecTopologyIntent(mode=MESH, …)'],
    historicalEvidence: ['gec_mesh_k8 replay row, PARETO-REPLAY-RESULTS-2026-08-29.md — HISTORICAL MEASUREMENT (see record for exact figure)'],
    missingBridge: 'PHASE D equivalence ruling for GEC mesh vs ordinary Mesh materialization, then a canonical materializer',
    actions: [
      { label: 'View historical evidence', detail: 'PARETO-REPLAY-RESULTS-2026-08-29.md, gec_mesh_k8 row.' },
      { label: 'Inspect backend source', detail: 'third_party/booksim2/src/networks/gec.cpp.' },
    ],
  },
  {
    id: 'GEC-EXPRESS',
    name: 'GEC point-to-point express channels',
    maturity: 'RESEARCH',
    maturityNote: 'CURRENT_BACKEND_ONLY + HISTORICAL_MEASURED; intent is no longer the blocker, physical derivation is',
    stages: { intent: 'INTENT ONLY', artifact: 'NO', verifier: 'NO', projection: 'PARTIAL', executable: 'YES (outside canonical path)', qualified: 'NO', product: 'NO', evidence: 'NO' },
    whatItIs: 'GEC point-to-point express channels (d=1): ordinary channels, canonical materialization + route/VC semantics still missing.',
    implementation: ['third_party/booksim2/src/networks/gec.cpp (express mode)', 'model/topology_intent.py GecTopologyIntent(mode=EXPRESS, …); groups × destinations == side − 1 enforced at construction', 'model/presets.py SWEEP_TOPOS gec_express_k8'],
    historicalEvidence: ['1857.69c qwen / 239.81c attention (best or near-best) — HISTORICAL MEASUREMENT'],
    missingBridge: 'canonical materializer + route/VC semantics',
    actions: [
      { label: 'View historical evidence', detail: 'PARETO-REPLAY-RESULTS-2026-08-29.md, gec_express row.' },
      { label: 'Open design experiment', detail: 'Authorable as GecTopologyIntent; compilation stops at TOPOLOGY with a typed refusal.' },
    ],
  },
  {
    id: 'GEC-MECS',
    name: 'GEC multi-drop express (MECS) topology',
    maturity: 'RESEARCH',
    maturityNote: 'CURRENT_BACKEND_ONLY + HISTORICAL_EXECUTABLE + HISTORICAL_MEASURED; shared tapped resource, never flattened to p2p',
    stages: { intent: 'INTENT ONLY (shared/tapped declared, not flattened)', artifact: 'NO — DirectedChannel cannot express it', verifier: 'NO', projection: 'backend-native only', executable: 'YES (outside canonical path)', qualified: 'NO', product: 'NO', evidence: 'NO' },
    whatItIs: 'Shared multidrop express channel (destinations_per_express_channel > 1): ONE channel tapped to many destinations. Flattening taps into independent p2p links changes contention and delivery semantics and is refused.',
    implementation: ['third_party/booksim2/src/networks/gec.cpp', 'third_party/booksim2/src/multidropchannel.{hpp,cpp}', 'third_party/booksim2/src/flit.hpp', 'model/topology_intent.py GecTopologyIntent(mode=MULTIDROP, …)'],
    historicalEvidence: ['1906.87c qwen / 64235.20c llama ring / 260.44c attention — HISTORICAL MEASUREMENT'],
    missingBridge: 'canonical multidrop physical resource + route/VC semantics (incl. tap/drop selection, per-tap credit/BufferState, VC subranges) + backend-equivalence qualification',
    actions: [
      { label: 'View historical evidence', detail: 'PARETO-REPLAY-RESULTS-2026-08-29.md, gec_mecs rows.' },
      { label: 'Inspect backend source', detail: 'multidropchannel.hpp/cpp — the single-slot contention model.' },
    ],
  },
  {
    id: 'GEC-HYBRID',
    name: 'GEC hybrid routing model',
    maturity: 'RESEARCH',
    maturityNote: 'CURRENT_BACKEND_ONLY; no durable run record located — inherits MECS semantics + two-domain VC/routing',
    stages: { intent: 'INTENT ONLY', artifact: 'NO', verifier: 'NO', projection: 'backend-native only', executable: 'YES (outside canonical path)', qualified: 'NO', product: 'NO', evidence: 'NO' },
    whatItIs: 'GEC hybrid routing model (routing/hybrid_gec.cpp): requires 2·d VCs; hybrid=1 with mesh=1 is refused at construction.',
    implementation: ['third_party/booksim2/src/networks/gec.cpp + gec.hpp', 'model/topology_intent.py GecTopologyIntent(mode=HYBRID, …)'],
    historicalEvidence: ['NO durable run record or measurement artifact located — NOT PROVEN'],
    missingBridge: 'canonical materializer + the 2·d VC sub-range semantics + backend-equivalence qualification',
    actions: [{ label: 'Inspect backend source', detail: 'third_party/booksim2/src/networks/gec.{hpp,cpp}.' }],
  },
  {
    id: 'TORUS',
    name: 'Torus (KNCube wrap) topology',
    maturity: 'EXPERIMENTAL',
    maturityNote: 'DOR_TORUS_XY route generator + TORUS profile exist; deadlock-proof method (dateline partition) + qualification pending',
    stages: { intent: 'YES', artifact: 'YES (wraparound links)', verifier: 'PARTIAL (ROUTE_COMPLETE/LEGAL pass; DEADLOCK_FREE FAILs named X-ring VC0 cycle)', projection: 'YES (CERTIFIED_BOOKSIM_TORUS_DOR_XY_V1)', executable: 'YES (k=5 uniform, no deadlock)', qualified: 'NO', product: 'PARTIAL — staged', evidence: 'PARTIAL' },
    whatItIs: 'Torus (KNCube wrap): DOR_TORUS_XY sealed class (wraparound-minimal X-then-Y, deterministic midpoint ties, dateline halves) + native profile with exact-2-VC qualifier. The static (channel,VC) CDG cannot express the dateline partition — that proof method is the bridge.',
    implementation: ['third_party/booksim2/src/networks/kncube.cpp', 'MaterializedFamily.TORUS materializer', 'core/route_artifact.py DOR_TORUS_XY', 'backend/booksim_projection.py qualify_native_torus_dor', 'SWEEP_TOPOS torus_8x8'],
    historicalEvidence: ['1872.47c / 62451.80c / 374.61c — HISTORICAL MEASUREMENT', 'k=5 uniform traffic EXECUTED (avg pkt 24.5c, no deadlock) — backend-level, not certified qualification'],
    missingBridge: 'dateline-partition deadlock-proof method + qualification envelope; fork dump harness passes in_channel=-1 (exact network.cpp patch recorded, not applied)',
    actions: [
      { label: 'Open design experiment', detail: 'Torus is authorable; Studio reports exactly where compilation stops (ROUTING/PROJECTION).' },
      { label: 'View historical evidence', detail: 'PARETO-REPLAY-RESULTS-2026-08-29.md, torus_8x8 row.' },
    ],
  },
  {
    id: 'FLATFLY',
    name: 'Flattened butterfly (on-chip)',
    maturity: 'EXPERIMENTAL',
    maturityNote: 'FLATFLY_MIN route class + native profile exist; k=4/n=2 dump vs canonical table 256/256 COMPARABLE; qualification pending',
    stages: { intent: 'YES (FlatFlyIntent)', artifact: 'YES (internal materializer)', verifier: 'PARTIAL (route verified; deadlock discharge per shape)', projection: 'YES (CERTIFIED_BOOKSIM_FLATFLY_MIN_V1)', executable: 'YES (byte-identical route realization)', qualified: 'NO', product: 'NO', evidence: 'PARTIAL' },
    whatItIs: 'Flattened butterfly (KNFly): pure point-to-point (no new channel primitive needed), chosen as the first non-mesh proof family. FLATFLY_MIN replicas min_flatfly lowest-dimension-first.',
    implementation: ['third_party/booksim2/src/networks/flatfly_onchip.cpp', 'model/topology_artifact.py materialize_flatfly', 'core/route_artifact.py FLATFLY_MIN', 'backend/booksim_projection.py qualify_native_flatfly_min'],
    historicalEvidence: ['flatfly_64 (ran_min): 1922.73c / 63937.80c / 259.81c — HISTORICAL MEASUREMENT', 'k=4/n=2 executed route dump 256/256 COMPARABLE, 0 mismatches — backend-level, not certified qualification'],
    missingBridge: 'qualification envelope; authoring/control-plane bridge for user-facing intent',
    actions: [{ label: 'View historical evidence', detail: 'PARETO-REPLAY-RESULTS-2026-08-29.md, flatfly_64 row.' }],
  },
  {
    id: 'FAT-TREE',
    name: 'Fat-tree (BookSim fattree / k-ary n-tree)',
    maturity: 'RESEARCH',
    maturityNote: 'CURRENT_BACKEND_ONLY + HISTORICAL_MEASURED (archived comparison); canonical materializer missing — NOT cfg-only',
    stages: { intent: 'INTENT ONLY (FatTreeIntent)', artifact: 'NO', verifier: 'NO', projection: 'PARTIAL', executable: 'YES (outside canonical path)', qualified: 'NO', product: 'NO', evidence: 'NO' },
    whatItIs: 'Fat-tree (nca/anca routing registered): a concentrated fat-tree is a DIFFERENT topology semantic and is NOT expressible in FatTreeIntent.',
    implementation: ['third_party/booksim2/src/networks/fattree.cpp', 'model/topology_intent.py FatTreeIntent(switch_radix, level_count)'],
    historicalEvidence: ['IN HISTORY commit 6a335004: booksim2/full_topology_comparison.xlsx, “Fat-tree (nca, 64 nodes)” rows — HISTORICAL MEASUREMENT, not present at HEAD'],
    missingBridge: 'canonical materializer + route/VC semantics + qualification',
    actions: [{ label: 'View historical evidence', detail: 'archive/topology-comparison-2026-08@6a335004, full_topology_comparison.xlsx.' }],
  },
  {
    id: 'DRAGONFLY',
    name: 'DragonflyNew',
    maturity: 'RESEARCH',
    maturityNote: 'CURRENT_BACKEND_ONLY + HISTORICAL_MEASURED (structural minimum 72 nodes); no canonical representation — NOT cfg-only',
    stages: { intent: 'NO', artifact: 'NO', verifier: 'NO', projection: 'PARTIAL', executable: 'YES (outside canonical path)', qualified: 'NO', product: 'NO', evidence: 'NO' },
    whatItIs: 'DragonflyNew (min/ugal routing registered). The 72-node structural minimum (a·p·(a·p+1) at p=2,n=1) constrains comparisons.',
    implementation: ['third_party/booksim2/src/networks/dragonfly.cpp'],
    historicalEvidence: ['IN HISTORY commit 6a335004: “Dragonfly (min, 72 nodes — structural minimum)” rows — HISTORICAL MEASUREMENT, not present at HEAD'],
    missingBridge: 'canonical representation + qualification',
    actions: [{ label: 'View historical evidence', detail: 'archive/topology-comparison-2026-08@6a335004, full_topology_comparison.xlsx.' }],
  },
  {
    id: 'QTREE',
    name: 'Quad tree (BookSim qtree)',
    maturity: 'RESEARCH',
    maturityNote: 'Backend implements it; NO committed run or measurement artifact — reclaim experimentally only after real runs',
    stages: { intent: 'NO', artifact: 'NO', verifier: 'NO', projection: 'PARTIAL', executable: 'EXECUTABLE POTENTIAL — NOT PROVEN', qualified: 'NO', product: 'NO', evidence: 'NO' },
    whatItIs: 'Quad tree (nca_qtree registered). The binary accepts the topology; execution is plausible but unproven from durable evidence.',
    implementation: ['third_party/booksim2/src/networks/qtree.cpp'],
    historicalEvidence: ['NOT PROVEN — no committed run or measurement artifact in HEAD or history. Never present as historically measured.'],
    missingBridge: 'canonical representation + qualification + fresh authenticated executions',
    actions: [{ label: 'Open design experiment', detail: 'Run qtree through the canonical pipeline to create the first authenticated evidence.' }],
  },
  {
    id: 'TREE4',
    name: '4-ary tree (BookSim tree4)',
    maturity: 'RESEARCH',
    maturityNote: 'Backend implements it; NO committed run or measurement artifact — reclaim experimentally only after real runs',
    stages: { intent: 'NO', artifact: 'NO', verifier: 'NO', projection: 'PARTIAL', executable: 'EXECUTABLE POTENTIAL — NOT PROVEN', qualified: 'NO', product: 'NO', evidence: 'NO' },
    whatItIs: '4-ary tree (nca_tree4/anca_tree4 registered). Same evidence discipline as qtree.',
    implementation: ['third_party/booksim2/src/networks/tree4.cpp'],
    historicalEvidence: ['NOT PROVEN — no committed run or measurement artifact in HEAD or history. Never present as historically measured.'],
    missingBridge: 'canonical representation + qualification + fresh authenticated executions',
    actions: [{ label: 'Open design experiment', detail: 'Run tree4 through the canonical pipeline to create the first authenticated evidence.' }],
  },
  {
    id: 'ADAPTIVE-ROUTING',
    name: 'Adaptive routing (MinAdapt/UGAL/Valiant/Chaos/planar/ROMM)',
    maturity: 'RESEARCH',
    maturityNote: 'Fork registers 9+ functions; canonical policy producer/projection/qualification missing; implementation potential, not execution evidence',
    stages: { intent: 'PARTIAL (RoutingPolicyDefinition)', artifact: 'PARTIAL', verifier: 'PARTIAL (adaptive_escape.py)', projection: 'NO', executable: 'YES (outside canonical path)', qualified: 'NO', product: 'NO', evidence: 'NO' },
    whatItIs: 'Adaptive routing research: PER_HOP/CANDIDATE_SET/ROUTER_ALLOCATOR/RNG/credit-observation vocabulary plus ADAPTIVE/ESCAPE/PHASE/TAP roles exist canonically; no adaptive policy producer is wired to a family.',
    implementation: ['third_party/booksim2/src/routefunc.cpp (min_adapt_mesh, planar_adapt_mesh, romm_mesh, valiant_mesh, chaos_mesh, ugal_*)', 'model/routing_policy.py', 'verification/adaptive_escape.py'],
    historicalEvidence: ['Study scripts exist (study_adaptive_*.sh) but NO committed adaptive-routing result artifact — NOT PROVEN measured. Create fresh product evidence before calling it executed.'],
    missingBridge: 'policy producer + BookSim projection + executed-route observation + qualification; deterministic DOR and adaptive stay distinct fidelity envelopes',
    actions: [{ label: 'Inspect backend source', detail: 'third_party/booksim2/src/routefunc.cpp registered functions.' }],
  },
  {
    id: 'MULTI-CLASS-COMMUNICATION',
    name: 'Multi-class traffic (class → VC subset)',
    maturity: 'EXPERIMENTAL',
    maturityNote: 'CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1 live (per-class conservation); ASTRA multi-class QUALIFIED under embedded class ABI 1 with live execution',
    stages: { intent: 'YES', artifact: 'YES', verifier: 'YES (_vc_exactness)', projection: 'YES (MC mesh profile + ASTRA V3 seam)', executable: 'YES (per-class conservation; ASTRA 7090-cycle live run)', qualified: 'CONDITIONAL (MC envelope / class ABI 1)', product: 'PARTIAL', evidence: 'YES (per-class conservation gates)' },
    whatItIs: 'Multi-class traffic with class → VC-subset semantics. V3 artifacts stamp per-message classes (COLLECTIVE + communicating EXPERT ops); the MC mesh profile replays per-class with conservation; ASTRA carries class identity through the versioned ABI (never inferred). A classes=2 run with a bad mapping once inflated latency 75× (fixed) — mapping soundness is the qualification.',
    implementation: ['traffic_class_to_vcs artifacts', 'LogicalMessageArtifactV3 / PhysicalTrafficArtifactV3', 'CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1', 'backend/astra_machine.py EMBEDDED_NETWORK_CLASS_ABI_VERSION=1', 'configs/plane_shared.cfg'],
    historicalEvidence: ['Per-phase slicing in PER-PHASE-PARETO-RESULTS-2026-08-29.md (class 0 vs class 1) — HISTORICAL MEASUREMENT', '2-class mesh (TP ALLREDUCE + EP ALLTOALL) EXECUTED via AstraSim_BookSim2, 7090 cycles, binding/ABI verified — current evidence'],
    missingBridge: 'class→VC-subset mapping qualification ongoing under the MC envelope; EXPERT dispatch/combine now named by the V3 sidecar',
    actions: [{ label: 'Open design experiment', detail: 'Multi-class designs compile; Studio shows the exact qualification state per envelope.' }],
  },
  {
    id: 'HARDWARE-MULTICAST',
    name: 'Hardware flit-fork multicast',
    maturity: 'HISTORICAL',
    maturityNote: 'HISTORICAL_EXECUTABLE + PROTOTYPE_ONLY; patch archived, unapplied at HEAD; logical replication is the canonical form',
    stages: { intent: 'PARTIAL (logical replication only)', artifact: 'PARTIAL', verifier: 'NO', projection: 'NO', executable: 'NO currently', qualified: 'NO', product: 'NO (example JSON has no consumer)', evidence: 'NO' },
    whatItIs: 'Hardware flit-fork multicast (Flit/IQRouter/TrafficManager fork). DISTINCT from logical source replication: logical multicast lowers to repeated unicasts unless hardware multicast is explicitly selected under a future qualified resource.',
    implementation: ['archive/booksim-ext/multicast.patch (300 lines, NOT applied)', 'product/examples/multicast.json (no consumer)'],
    historicalEvidence: ['IN HISTORY: “SMOKE TEST PASS: unicast 0→9 (4 flits) retired cycle 22; row multicast 0→{1,2,3,7} 4/4 via fork” (c41087b1); “ROW-MCAST 700/700; CROSS-DIE 800/800” (973ee7bd) — HISTORICAL MEASUREMENT, scope-limited to what the records state'],
    missingBridge: 'reclaim/modernize fork resource semantics (replication point, delivery/conservation laws, VC/deadlock effects, backend equivalence) + verification — never just reapply the patch',
    actions: [
      { label: 'View historical evidence', detail: 'archive/booksim-ext/multicast.patch + cited status records.' },
      { label: 'Inspect backend source', detail: 'The patch is a prototype, not a product path.' },
    ],
  },
  {
    id: 'MULTIPLANE',
    name: 'Simultaneous multi-plane fabric',
    maturity: 'RESEARCH',
    maturityNote: 'CURRENT_RESEARCH + HISTORICAL_EXECUTABLE of independent runs; no simultaneous-fabric contract — independent runs are NOT one fabric',
    stages: { intent: 'NO', artifact: 'NO', verifier: 'NO', projection: 'NO', executable: 'PARTIAL (each plane alone)', qualified: 'NO', product: 'NO', evidence: 'NO' },
    whatItIs: 'Simultaneous multi-plane fabric research. The old experiment executes planes as INDEPENDENT runs — that is explicitly not a simultaneous fabric.',
    implementation: ['configs/plane_*.cfg', 'scripts/research/plane_separation.py'],
    historicalEvidence: ['Per-plane latency/VC/express studies only — PARTIAL; no simultaneous-fabric measurement exists.'],
    missingBridge: 'first-class simultaneous multi-plane fabric contract (plane set, flow/class→plane assignment, shared endpoint/resource semantics, one execution/verification contract)',
    actions: [{ label: 'Inspect backend source', detail: 'scripts/research/plane_separation.py harness.' }],
  },
  {
    id: 'P2P-LOGICAL-MULTICAST',
    name: 'P2P and logical multicast operation contracts',
    maturity: 'EXPERIMENTAL',
    maturityNote: 'Typed ops + lowering tested; product workload intent cannot yet originate these ops',
    stages: { intent: 'YES', artifact: 'YES', verifier: 'YES', projection: 'YES (replication → unicast)', executable: 'YES (lowered form)', qualified: 'YES (lowered form)', product: 'NO', evidence: 'PARTIAL' },
    whatItIs: 'P2P and logical (source-replicated) multicast operation contracts. Semantic multicast is source replication to unicast — never equated with hardware fork multicast.',
    implementation: ['workload/operations.py', 'workload/graph.py', 'workload/messages.py'],
    historicalEvidence: ['Lowering covered by committed tests; no durable backend run artifact tied to an originating op — measurement axis not established.'],
    missingBridge: 'WorkloadV3 / product intent origination (representation already exists downstream)',
    actions: [{ label: 'Open design experiment', detail: 'Lowered forms execute; origination UI is the missing bridge.' }],
  },
  {
    id: 'STATIC-MOE',
    name: 'Static MoE expert dispatch/combine',
    maturity: 'EXPERIMENTAL',
    maturityNote: 'Expert operation semantics + lowering exist downstream; static dispatch/combine producer at intent level missing; serving MoE is a SEPARATE path',
    stages: { intent: 'YES', artifact: 'YES', verifier: 'PARTIAL', projection: 'YES (ASTRA lowering)', executable: 'YES', qualified: 'PARTIAL', product: 'NO', evidence: 'PARTIAL' },
    whatItIs: 'Static MoE expert dispatch/combine (EXPERT BEGIN/END + ALLTOALL dispatch/combine + logical messages). V3 sidecar names communicating EXPERT ops (dispatch/combine classes) — origination bridge landed. Serving-MoE trace results exercise a different path and are not evidence for this row.',
    implementation: ['workload/graph.py EXPERT BEGIN/END', 'backend/astra.py lowering', 'workload/messages.py V3 EXPERT sidecar'],
    historicalEvidence: ['Construction/validation/lowering covered by tests; dispatch/combine V3 origination proven; ASTRA EP dispatch/combine executes under class ABI 1.'],
    missingBridge: 'canonical static MoE dispatch/combine producer at intent level',
    actions: [{ label: 'Open design experiment', detail: 'Static model evaluation vs serving simulation stay distinct templates.' }],
  },
  {
    id: 'PIM',
    name: 'Processing-in-memory',
    maturity: 'RESEARCH',
    maturityNote: 'Real LLMServingSim latency/power models downstream; canonical intent→PIM bridge missing; zero-traffic marker is NOT PIM simulation',
    stages: { intent: 'PARTIAL (graph markers)', artifact: 'PARTIAL', verifier: 'NO', projection: 'NO (ASTRA: ZERO network traffic)', executable: 'YES (inside LLMServingSim only)', qualified: 'NO', product: 'NO', evidence: 'NO' },
    whatItIs: 'Processing-in-memory: LLMServingSim pim_model.py/power_model.py are real models a serving run invokes; the canonical side has PIM graph markers only.',
    implementation: ['third_party/llmservingsim/serving/core/pim_model.py', 'third_party/llmservingsim/serving/core/power_model.py'],
    historicalEvidence: ['EXECUTABLE POTENTIAL only — no committed PIM serving run or result artifact located. ASTRA treats PIM markers as ZERO network traffic.'],
    missingBridge: 'canonical intent → PIM execution bridge',
    actions: [{ label: 'Inspect backend source', detail: 'LLMServingSim PIM models (downstream authority).' }],
  },
  {
    id: 'RAMULATOR',
    name: 'Ramulator memory simulation',
    maturity: 'EXPERIMENTAL',
    maturityNote: 'Backend runs with qualification envelope + typed evidence; no NoC/memory coupling; no product memory API yet',
    stages: { intent: 'YES', artifact: 'YES', verifier: 'YES', projection: 'YES', executable: 'YES', qualified: 'YES', product: 'PARTIAL', evidence: 'YES' },
    whatItIs: 'Ramulator memory simulation (standalone HBM3 timing). Summing BookSim cycles + Ramulator cycles is FORBIDDEN — NoC/memory causal composition is a separate feature.',
    implementation: ['veritx_dse/simulation/ramulator.py', 'qualification/ramulator.py'],
    historicalEvidence: ['HANDOFF-2026-09-18-phase15-ramulator.md records the measured Ramulator leg (commit fd2b6694) — HISTORICAL MEASUREMENT'],
    missingBridge: 'NoC/memory coupling + product surface (memory-bearing workloads, controller placement, DRAM objectives)',
    actions: [{ label: 'View historical evidence', detail: 'tracks/t3-topology/docs/HANDOFF-2026-09-18-phase15-ramulator.md.' }],
  },
  {
    id: 'CANDIDATE-PROMOTION',
    name: 'Topology candidate promotion',
    maturity: 'EXPERIMENTAL',
    maturityNote: 'Canonical primitive tested; product/API/Studio promotion action is the missing bridge',
    stages: { intent: 'YES', artifact: 'YES', verifier: 'YES', projection: 'N/A', executable: 'N/A', qualified: 'N/A', product: 'NO', evidence: 'YES (linkage)' },
    whatItIs: 'Topology candidate promotion: promote_to_explicit_topology + apply_promotion_to_request_doc freeze a candidate graph into canonical TopologyIR (kind=custom); provenance is linkage, excluded from design identity.',
    implementation: ['synthesis/candidate.py promote_to_explicit_topology + apply_promotion_to_request_doc'],
    historicalEvidence: ['Exercised in-process by committed tests (test_candidate_promotion.py); no durable external run artifact — N/A measurement.'],
    missingBridge: 'product/API/Studio promotion action (“Use candidate” → explicit-topology draft → explicit Compile)',
    actions: [{ label: 'Open design experiment', detail: 'Promotion is library-level today; the Studio action is the bridge.' }],
  },
  {
    id: 'EVIDENCE-REUSE',
    name: 'Evidence reuse / cache',
    maturity: 'EXPERIMENTAL',
    maturityNote: 'Safe reuse-verification API exists; cache lookup/orchestration is the missing bridge (an API is not a cache)',
    stages: { intent: 'YES', artifact: 'YES', verifier: 'YES', projection: 'N/A', executable: 'N/A', qualified: 'N/A', evidence: 'YES', product: 'NO' },
    whatItIs: 'Evidence reuse: verify_reusable_record + read_reusable_record (digest/schema/binary/profile safe). Never reuse across producer, profile, backend-config, traffic, clock (when clock-dependent), or semantic-version changes.',
    implementation: ['backend/evidence.py verify_reusable_record + read_reusable_record'],
    historicalEvidence: ['Exercised in-process by committed tests; no durable external run artifact — N/A measurement.'],
    missingBridge: 'cache lookup/orchestration keyed only by actual scientific parents; hits explicit in run/evidence UI with reused evidence id, never a synthetic measurement',
    actions: [{ label: 'Inspect backend source', detail: 'backend/evidence.py reuse gate.' }],
  },
  {
    id: 'SEARCH-COMPLETENESS',
    name: 'Structural search completeness accounting',
    maturity: 'EXPERIMENTAL',
    maturityNote: 'Primitive + accounting exist and are tested; registry/docs reconciliation is the remaining bridge',
    stages: { intent: 'YES', artifact: 'YES', verifier: 'YES', projection: 'N/A', executable: 'N/A', qualified: 'N/A', evidence: 'YES', product: 'PARTIAL' },
    whatItIs: 'Structural search completeness: EXHAUSTIVE (complete over the declared finite design space) vs BUDGETED vs UNBOUNDED/heuristic (“best observed among evaluated candidates”). Global topology optimality is never implied.',
    implementation: ['optimization/completeness.py SearchCompleteness (EXHAUSTIVE/BUDGETED/UNBOUNDED + result binding)'],
    historicalEvidence: ['Exercised in-process by committed tests (test_search_completeness.py); N/A measurement.'],
    missingBridge: 'registry/docs reconciliation only — product copy must use the completeness wording everywhere',
    actions: [{ label: 'Inspect backend source', detail: 'optimization/completeness.py — the existing SearchCompleteness authority.' }],
  },
  {
    id: 'WAVE-E-METRICS',
    name: 'Wave-E metric registry',
    maturity: 'EXPERIMENTAL',
    maturityNote: 'Registry computes + projects with honesty metadata; committed measurement result artifact not located',
    stages: { intent: 'YES', artifact: 'YES', verifier: 'YES', projection: 'N/A', executable: 'N/A', qualified: 'PARTIAL (ANALYTICAL_MODEL, measured=False)', product: 'PARTIAL', evidence: 'YES' },
    whatItIs: 'Wave-E metric registry: makespan, critical path, request-latency mean, resource-utilization max — MODELLED, UNCALIBRATED, never merged with ASTRA native outputs under one metric name.',
    implementation: ['optimization/metric_registry.py'],
    historicalEvidence: ['Covered by test_wave_e_metric_projection.py; no committed measurement result artifact located.'],
    missingBridge: 'registry/docs describe an older missing state — reconcile after source/tests establish the new state',
    actions: [{ label: 'Open Performance view', detail: 'Schedule/dependency explanation behind makespan and critical path.' }],
  },
  {
    id: 'NOC-ENERGY',
    name: 'NoC energy estimation',
    maturity: 'RESEARCH',
    maturityNote: 'Six fidelity classes coexist; no canonical metric authority — the estimators must never be merged into one “energy”',
    stages: { intent: 'NO', artifact: 'NO', verifier: 'NO', projection: 'N/A', executable: 'N/A (runnable research script)', qualified: 'NO', product: 'PARTIAL', evidence: 'NO' },
    whatItIs: 'NoC energy estimation research: hops×packet proxy, Timeloop/Accelergy, noc_energy_bridge pJ/hop, analytical estimators, BookSim native, LLMServingSim — six separate fidelities.',
    implementation: ['scripts/noc_energy_bridge.py', 'dse/veritx_dse/reports/reports.py'],
    historicalEvidence: ['Bridge calibrated against Accelergy/FlooNoC (claim); no committed energy result table for a canonical fabric located.'],
    missingBridge: 'canonical fidelity/metric ownership; energy objectives enter optimization only after a canonical metric authority + comparable-fidelity law exist',
    actions: [{ label: 'Open Implementation Lab → Energy', detail: 'Per-authority fidelity, units, calibration state.' }],
  },
  {
    id: 'BOOKSIM-NATIVE-POWER',
    name: 'BookSim native Power_Module',
    maturity: 'RESEARCH',
    maturityNote: 'Backend-only; INVALID/INCOMPLETE for MECS until multidrop activity is included in power accounting',
    stages: { intent: 'NO', artifact: 'NO', verifier: 'NO', projection: 'NO', executable: 'YES', qualified: 'NO', product: 'NO', evidence: 'NO' },
    whatItIs: 'BookSim native Power_Module (power/). Walks Network::GetChannels()/_chan — GEC MECS shared links live in _md_chan and are silently uncounted.',
    implementation: ['third_party/booksim2/src/power/power_module.cpp', 'third_party/booksim2/src/networks/network.cpp'],
    historicalEvidence: ['Runs when sim_power=1; topology comparison scripts do not enable it; no committed power run artifact — NOT PROVEN measured.'],
    missingBridge: 'MECS-aware power accounting (include _md_chan activity) before any MECS power result is allowed',
    actions: [{ label: 'Open Implementation Lab → Energy', detail: 'BACKEND_ACTIVITY_MODEL fidelity, MECS exclusion stated.' }],
  },
  {
    id: 'RTL-VALIDATION',
    name: 'RTL build/run validation',
    maturity: 'RESEARCH',
    maturityNote: 'Validation harness is current and executable; RTL is not a canonical VERITX artifact; simulation, not proof',
    stages: { intent: 'N/A (not canonical)', artifact: 'N/A', verifier: 'YES (oracle comparison)', projection: 'N/A', executable: 'YES', qualified: 'PARTIAL', product: 'NO', evidence: 'PARTIAL' },
    whatItIs: 'RTL build/run validation (Verilator build+run + oracle comparison). RTL simulation results are RTL_SIMULATION, never proof.',
    implementation: ['validation/harness/rtl.py + compare.py', 'tracks/t3-topology/rtl/*'],
    historicalEvidence: ['Committed RTL document (research/rtl-audit-2026-08-13.md) is a read-through audit, not a run record; no committed run log located.'],
    missingBridge: 'product integration; exact generated-RTL inputs bound to parent design artifacts; tool/version/testbench/design/result binding',
    actions: [{ label: 'Open Implementation Lab → RTL', detail: 'Build/run status, oracle comparison, source design identity.' }],
  },
  {
    id: 'UVM-SVA',
    name: 'UVM / SVA generation',
    maturity: 'RESEARCH',
    maturityNote: 'Generator runs; generated collateral is not verification — execution/formal authority missing',
    stages: { intent: 'N/A (collateral)', artifact: 'N/A', verifier: 'NO', projection: 'N/A', executable: 'NO', qualified: 'NO', product: 'NO', evidence: 'NO' },
    whatItIs: 'UVM/SVA generation (uvm_gen.py + generated tests). Generated SVA is collateral until executed by a simulator/formal engine.',
    implementation: ['tracks/t3-topology/dse/veritx_dse/verification/uvm_gen.py'],
    historicalEvidence: ['Generator runs; no committed simulator execution authority — NO measurement.'],
    missingBridge: 'execution/formal authority (simulator/formal engine runs with committed pass artifacts)',
    actions: [{ label: 'Open Implementation Lab → UVM/SVA', detail: 'Generated vs Executed vs Passed, kept separate.' }],
  },
  {
    id: 'CDC',
    name: 'Clock-domain crossing',
    maturity: 'RESEARCH',
    maturityNote: 'Working CDC FIFO component + testbench; a FIFO is not multi-clock NoC execution; system qualification NOT ESTABLISHED',
    stages: { intent: 'NO (no multi-clock contract)', artifact: 'NO', verifier: 'PARTIAL (component testbench)', projection: 'NO', executable: 'NO', qualified: 'NO', product: 'NO', evidence: 'NO' },
    whatItIs: 'Clock-domain crossing: CDC FIFO component (gray pointers + sync) with Verilator testbench. Component tests are not evidence for full multi-clock NoC execution.',
    implementation: ['tracks/t3-topology/rtl/cdc/cdc_fifo.sv', 'tracks/t3-topology/rtl/cdc/tb_cdc.cpp'],
    historicalEvidence: ['Component builds/runs via the cdc Makefile; no committed run log located; measurement PARTIAL (component only).'],
    missingBridge: 'canonical multi-clock NoC execution contract; until then research/validation under Implementation Lab, never implied multi-clock qualification',
    actions: [{ label: 'Open Implementation Lab → CDC', detail: 'Component status vs system qualification, kept separate.' }],
  },
];

export interface CoreSystem {
  id: string;
  name: string;
  maturity: Maturity;
  note: string;
  authority: string;
}

/**
 * Core product systems not represented as archaeology rows
 * (Studio-curated product-surface state — not registry authority).
 */
export const CORE_SYSTEMS: CoreSystem[] = [
  { id: 'BOOKSIM', name: 'BookSim standalone', maturity: 'AVAILABLE', note: 'certified mesh/cmesh/anynet + multi-class mesh profiles with conservation gates', authority: 'backend five-operation model (capabilities/assess/prepare/execute/normalize)' },
  { id: 'ASTRA', name: 'ASTRA-Sim', maturity: 'EXPERIMENTAL', note: 'system simulation runs; multi-class QUALIFIED under embedded class ABI 1 (live 7090-cycle run, per-class conservation); numerical validation not established for cross-model comparison', authority: 'vendored ASTRA↔BookSim ABI (EMBEDDED_NETWORK_CLASS_ABI_VERSION=1, mismatch aborts)' },
  { id: 'SERVING', name: 'Serving / LLMServingSim', maturity: 'EXPERIMENTAL', note: 'request semantics owned by LLMServingSim; declared compute durations stay visibly declared', authority: 'CanonicalServingEvidence' },
  { id: 'FEDERATION', name: 'Federation', maturity: 'AVAILABLE', note: 'question-first planning with per-question qualified producers; AUTO default, expert pinning', authority: 'EvaluationPlanner + federated metric catalog' },
  { id: 'COMPARISON', name: 'Comparison', maturity: 'AVAILABLE', note: 'backend verdicts with MODEL DIFFERENCE on incompatible families — never fake deltas', authority: 'server product-compare verdicts' },
  { id: 'REPRODUCTION', name: 'Reproduction', maturity: 'EXPERIMENTAL', note: 'per-backend archived-input reproduction with match/divergence comparison', authority: 'reproduce_* backend contracts' },
  { id: 'OPTIMIZATION', name: 'Optimization', maturity: 'AVAILABLE', note: 'certified single-backend Pareto + budgeted/random search with completeness wording', authority: 'OptimizationStudyView v2 contract' },
  { id: 'SYNTHESIS', name: 'Topology synthesis', maturity: 'EXPERIMENTAL', note: 'MILP/SA/BO/RHO/GRPO via canonical adapters (synthesis/rho_grpo_adapter.py, synthesis/bo_adapter.py → to_topology_candidate, FEASIBLE/BUDGETED/UNBOUNDED honesty)', authority: 'TopologyCandidate + promotion primitives' },
];

/** §43 History view: durable historical comparisons as HISTORICAL with re-run action. */
export const HISTORY_ROWS: { scope: string; artifact: string; note: string }[] = [
  { scope: 'Mesh / Torus / FlatFly / GEC / Fat-tree / Dragonfly', artifact: 'archive/topology-comparison-2026-08@6a335004 — full_topology_comparison.xlsx (Report + All Runs)', note: 'HISTORICAL MEASUREMENT with exact source commit; regression use only after workload/profile semantics are understood' },
  { scope: 'GEC mesh / express / MECS rows', artifact: 'PARETO-REPLAY-RESULTS-2026-08-29.md replay table', note: 'HISTORICAL MEASUREMENT; directionally consistent reclamation tests, exact equality only on proven-equivalent versions' },
  { scope: 'Fat-tree (nca, 64 nodes) / Dragonfly (min, 72 nodes)', artifact: 'same xlsx, structural-minimum noted', note: 'HISTORICAL MEASUREMENT, not present at HEAD' },
  { scope: 'Hardware multicast fork runs', artifact: 'status records c41087b1 / 973ee7bd + archived patch', note: 'HISTORICAL EXECUTION, scope-limited to what the records state' },
  { scope: 'Ramulator leg', artifact: 'HANDOFF-2026-09-18-phase15-ramulator.md @ fd2b6694', note: 'HISTORICAL MEASUREMENT with campaign source' },
];

export function maturityCounts(): Record<Maturity, number> {
  const counts = Object.fromEntries(MATURITIES.map((m) => [m, 0])) as Record<Maturity, number>;
  for (const c of CAPABILITIES) counts[c.maturity] += 1;
  return counts;
}

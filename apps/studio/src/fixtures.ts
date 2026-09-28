// Fixture loading. Studio boots from these contract-validated fixtures only.
// Every file here must pass scripts/validate_fixtures.py against the frozen
// contracts (study view v2, the other four views v1). No engine
// connectivity, no fetched data.
import type { FixtureBundle } from './types';

import compiledMesh from '../fixtures/compiled-mesh.json';
import invalidDesign from '../fixtures/invalid-design.json';
import backendUnavailable from '../fixtures/backend-unavailable.json';
import evaluatedDesign from '../fixtures/evaluated-design.json';
import optimizationStudy from '../fixtures/optimization-study.json';

function asBundle(doc: unknown): FixtureBundle {
  return doc as unknown as FixtureBundle;
}

export const FIXTURE_ORDER = [
  'compiled-mesh',
  'invalid-design',
  'backend-unavailable',
  'evaluated-design',
  'optimization-study',
] as const;

export type FixtureId = (typeof FIXTURE_ORDER)[number];

export const FIXTURES: Record<FixtureId, FixtureBundle> = {
  'compiled-mesh': asBundle(compiledMesh),
  'invalid-design': asBundle(invalidDesign),
  'backend-unavailable': asBundle(backendUnavailable),
  'evaluated-design': asBundle(evaluatedDesign),
  'optimization-study': asBundle(optimizationStudy),
};

// ── Studio vNext inline fixtures (offline demonstration only) ──────────
// These NEVER substitute for a live project (§45). They exist so new
// pages render their contract shape with zero engine connectivity, and
// so contract tests can pin the never-rules against fixed inputs.
import type {
  CandidateDetailView,
  CandidateLibraryView,
  CapabilityExplorerView,
  CompletenessView,
  EnergyAuthoritiesView,
  ImplementationStatusView,
  PerformanceMetricsView,
  SynthesisResultView,
} from './api/types';

export const VNEXT_SYNTHESIS_FIXTURE: SynthesisResultView = {
  contract_version: 1,
  synthesis_id: 'synth-demo-1',
  method: 'rho',
  base_topology: 'mesh 4x4',
  generated_count: 50,
  evaluated_count: 50,
  completeness: {
    kind: 'UNBOUNDED',
    evaluated: 50,
    declared: null,
    wording:
      '50 generated graphs explored — heuristic search, no claim of global optimality.',
    may_claim_optimality: false,
  } as CompletenessView,
  candidates: [
    {
      candidate_id: 'rho-demo-17',
      method: 'rho',
      solver_status: 'FEASIBLE',
      generator_objective_name: 'traffic_weighted_hops',
      generator_objective_value: 842,
      compile_status: 'COMPILED',
      verification_status: 'PASS',
      measured_cycles: 11720,
      measured_backend: 'BOOKSIM_STANDALONE',
      evidence_id: 'ev-demo-1',
      requirements_state: 'SATISFIED',
    },
  ],
};

export const VNEXT_CANDIDATES_FIXTURE: CandidateLibraryView = {
  contract_version: 1,
  entries: [
    {
      candidate_id: 'rho-demo-17',
      origin: 'synth-demo-1',
      method: 'rho',
      design_delta: '+3 express links, radix 4→5 on 2 routers',
      network_cycles: 11720,
      system_cycles: null,
      memory_cycles: null,
      verification: 'PASS',
      status: 'EVALUATED',
      pareto_member: null,
      adopted: false,
    },
  ],
};

export const VNEXT_CANDIDATE_DETAIL_FIXTURE: CandidateDetailView = {
  contract_version: 1,
  candidate: VNEXT_CANDIDATES_FIXTURE.entries[0],
  topology_hash: 'sha256:topo-demo',
  compile: 'COMPILED',
  verification: 'PASS',
  evidence_ids: ['ev-demo-1'],
  generator_provenance: { method: 'rho', seed: 7, steps: 20 },
  promotion: { promoted: false, message: null },
};

export const VNEXT_CAPABILITIES_FIXTURE: CapabilityExplorerView = {
  contract_version: 1,
  rows: [
    {
      capability_id: 'mesh-dor',
      title: 'Mesh + DOR',
      ladder: {
        intent: true, materialized: true, verified: true, projected: true,
        executable: true, qualified: true, product: true,
      },
      maturity: 'AVAILABLE',
      evidence: 'CERTIFIED_BOOKSIM_MESH_DOR_XY_V1',
    },
    {
      capability_id: 'torus',
      title: 'Torus',
      ladder: {
        intent: true, materialized: true, verified: 'partial',
        projected: false, executable: 'partial', qualified: false,
        product: false,
      },
      maturity: 'EXPERIMENTAL',
      evidence: 'historical measurement, commit 6a335004',
    },
    {
      capability_id: 'gec-mecs',
      title: 'GEC-MECS',
      ladder: {
        intent: true, materialized: false, verified: false,
        projected: 'partial', executable: 'partial', qualified: false,
        product: false,
      },
      maturity: 'RESEARCH',
      evidence: 'backend-only + historical measurement',
    },
  ],
};

export const VNEXT_PERFORMANCE_FIXTURE: PerformanceMetricsView = {
  contract_version: 1,
  makespan_s: 0.00001172,
  critical_path_s: 0.0000091,
  critical_path_note:
    'dependency chain only — resource serialization excluded',
  request_latency: {
    mean_s: 0.0000021, median_s: null, p95_s: null, max_s: null,
    sample_count: 64,
  },
  utilization: { fabric: 0.62 },
  sensitivity: { link_width_x2: { makespan_s: 0.0000098 } },
  epistemic: 'MODELLED',
  predictive_validation: 'NOT_ESTABLISHED',
};

export const VNEXT_ENERGY_FIXTURE: EnergyAuthoritiesView = {
  contract_version: 1,
  authorities: [
    {
      id: 'hops-packet-proxy', fidelity: 'PROXY', unit: 'hop-bits',
      inputs: ['hops_avg', 'packet_size_bits'], source: 'BookSim sweep',
      scope: 'research Pareto input only', calibration: null,
    },
    {
      id: 'booksim-native-power', fidelity: 'BACKEND_ACTIVITY', unit: 'W',
      inputs: ['sim_power=1 activity'], source: 'BookSim Power_Module',
      scope: 'point-to-point only', calibration: null,
    },
  ],
  mecs_native_power: {
    available: false,
    reason: 'multidrop _md_chan activity is not currently included',
  },
};

export const VNEXT_IMPLEMENTATION_FIXTURE: ImplementationStatusView = {
  contract_version: 1,
  rtl: {
    build: 'PASS', simulation: 'PASS', oracle: 'MATCH',
    design_identity: 'sha256:design', epistemic: 'RTL_SIMULATION',
  },
  uvm_sva: {
    generated: true, executed: false, passed: null, assertions: 8,
    testbench: 'tb_top',
  },
  cdc: {
    component: 'cdc_fifo', component_tests: 'PASS',
    system_qualification: 'NOT_ESTABLISHED',
  },
};

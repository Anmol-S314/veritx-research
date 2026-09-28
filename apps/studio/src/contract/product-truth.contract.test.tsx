/** Product-truth contract tests (fixtures only — no engine, no network).
 *
 *  Every test renders a component against a server-shaped fixture and
 *  asserts Studio surfaces the server's verdict verbatim: backend-specific
 *  rows for all three backends, no BookSim tables for non-BookSim evidence,
 *  exact refusal reasons, no winner language, and server-provided
 *  verdict/delta/support/readiness fields shown when present.
 */
import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { EvaluationPlanTable, AnalysisCard } from '../components/FederatedEvaluationView';
import { AnalysisIntegrity } from '../pages/index';
import StudyVerdict from '../StudyVerdict';
import type {
  EvaluationPlanView,
  FederatedAnalysisView,
} from '../api/types';
import type { Candidate, OptimizationStudyView } from '../types';

const PLAN: EvaluationPlanView = {
  contract_version: 1,
  revision_id: 'r-1',
  design_hash: 'sha256:design',
  resolved_fabric_hash: 'sha256:fabric',
  workload_id: 'w-1',
  analyses: [
    {
      question: 'NETWORK_COMPLETION',
      backend: 'BOOKSIM_STANDALONE',
      support: 'SUPPORTED',
      readiness: 'READY',
      model_fidelity: 'NETWORK_PACKET_SIMULATION',
      qualification_profile: 'CERTIFIED_BOOKSIM_MESH_DOR_XY_V1',
      reason: null,
      limitations: [],
    },
    {
      question: 'SYSTEM_MAKESPAN',
      backend: 'ASTRA2_EMBEDDED_BOOKSIM',
      support: 'SUPPORTED',
      readiness: 'READY',
      model_fidelity: 'SYSTEM_SIMULATION',
      qualification_profile: 'ASTRA2_COLLECTIVE_V1',
      reason: null,
      limitations: ['collective-mode only'],
    },
    {
      question: 'DRAM_TIMING',
      backend: 'RAMULATOR2_HBM3_V1',
      support: 'SUPPORTED',
      readiness: 'BLOCKED',
      model_fidelity: null,
      qualification_profile: null,
      reason: 'extension not built',
      limitations: [],
    },
  ],
};

describe('EvaluationPlanTable', () => {
  it('renders all 7 columns including ASTRA and Ramulator rows', () => {
    render(<EvaluationPlanTable plan={PLAN} />);
    const table = screen.getByRole('table');
    const headers = within(table)
      .getAllByRole('columnheader')
      .map((h) => h.textContent?.toLowerCase() ?? '');
    for (const col of [
      'question',
      'backend',
      'readiness',
      'fidelity',
      'qualification',
      'reason',
      'limitations',
    ]) {
      expect(headers.join('|')).toContain(col);
    }
    expect(screen.getByText('BOOKSIM_STANDALONE')).toBeDefined();
    expect(screen.getByText('ASTRA2_EMBEDDED_BOOKSIM')).toBeDefined();
    expect(screen.getByText('RAMULATOR2_HBM3_V1')).toBeDefined();
    // The blocked Ramulator row names its exact reason.
    expect(screen.getByText('extension not built')).toBeDefined();
  });
});

const ASTRA_INTEGRITY: Record<string, unknown> = {
  backend: 'ASTRA2_EMBEDDED_BOOKSIM',
  status: 'EVALUATED',
  kind: 'astra_system_integrity',
  native_evidence_id: 'astra-ev-1',
  evidence_tier: 'ASTRA_OWNED_COLLECTIVE_EXECUTION',
  reason: null,
};

describe('AnalysisIntegrity', () => {
  it('never renders BookSim packet tables for ASTRA evidence', () => {
    const { container } = render(
      <AnalysisIntegrity name="system_makespan" record={ASTRA_INTEGRITY} />,
    );
    const text = container.textContent ?? '';
    expect(text).not.toContain('Packet conservation');
    expect(text).not.toContain('Flit conservation');
    expect(text).not.toContain('Route realization');
    expect(text).toContain('ASTRA_OWNED_COLLECTIVE_EXECUTION');
  });
});

const FAILED_ANALYSIS: FederatedAnalysisView = {
  question: 'SYSTEM_MAKESPAN',
  backend_id: 'ASTRA2_EMBEDDED_BOOKSIM',
  status: 'FAILED',
  model_fidelity: 'SYSTEM_SIMULATION',
  qualification: null,
  native_evidence_id: null,
  reason: 'astra binary exited rc=1: collective ledger missing COMM_COLL lines',
  native_summary: null,
  normalized_metrics: null,
  limitations: null,
};

describe('AnalysisCard', () => {
  it('shows the exact server reason for a FAILED analysis', () => {
    render(
      <AnalysisCard analysis={FAILED_ANALYSIS} evaluation={null} requirements={null} />,
    );
    expect(
      screen.getByText(
        'astra binary exited rc=1: collective ledger missing COMM_COLL lines',
      ),
    ).toBeDefined();
    // No invented metrics section for a failed analysis.
    expect(screen.queryByText('Normalized metrics')).toBeNull();
  });
});

function candidate(over: Partial<Candidate>): Candidate {
  return {
    candidate_id: 'c-1',
    guided_patch: {},
    evaluation_ids: {
      design_hash: 'sha256:design',
      performance_result_id: null,
      requirement_report_id: null,
    },
    product_requirements: { satisfied: null, verdicts: [] },
    objective_values: { completion_cycles: 1000 },
    objective_availability: { completion_cycles: 'MEASURED' },
    constraint_verdicts: {},
    evaluation_authority: 'certified-backend',
    compilation_status: 'COMPILED',
    evaluation_status: 'EVALUATED',
    evaluation_reason: null,
    eligibility_reason: null,
    pareto_eligible: true,
    pareto_member: true,
    ...over,
  };
}

const STUDY: OptimizationStudyView = {
  contract_version: 2,
  result_class: 'CERTIFIED_PRODUCT',
  metric_registry_id: null,
  metric_registry_version: null,
  optimization_result_id: 'opt-1',
  base_design_hash: 'sha256:design',
  definition: {
    definition_id: 'd-1',
    objectives: [{ metric: 'completion_cycles', direction: 'MIN' }],
    constraints: [],
    method: 'grid',
    selection: 'min_first_objective',
    budget: {},
  },
  candidates: [
    candidate({
      candidate_id: 'c-best',
      guided_patch: { link_width: 128 },
      objective_values: { completion_cycles: 900 },
      verdict: 'COMPARABLE',
      differs: null,
      delta_b_minus_a: -100,
      evaluation_support: 'SUPPORTED',
      evaluation_readiness: 'READY',
    }),
  ],
  pareto_ids: ['c-best'],
};

describe('StudyVerdict', () => {
  it('uses no winner language and shows the server delta when provided', () => {
    const { container } = render(<StudyVerdict study={STUDY} baseGuided={null} />);
    const text = container.textContent ?? '';
    expect(text).not.toMatch(/best measured design/i);
    // The word "winner" may appear only inside the explicit
    // not-a-winner disclaimer, never as a claim.
    expect(text).not.toMatch(/\bwinner\b(?!\))/i);
    expect(text).toContain('Highest measured value (not a winner)');
    // Server verdict block with delta.
    expect(text).toContain('COMPARABLE');
    expect(text).toContain('-100');
    // Server capability truth.
    expect(text).toContain('SUPPORTED · READY');
  });
});

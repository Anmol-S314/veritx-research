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
    const withoutDisclaimers = text.replace(/not a winner/gi, '');
    expect(withoutDisclaimers).not.toMatch(/\bwinner\b/i);
    expect(text).toContain('Highest measured value (not a winner)');
    // Server verdict block with delta.
    expect(text).toContain('COMPARABLE');
    expect(text).toContain('-100');
    // Server capability truth.
    expect(text).toContain('SUPPORTED · READY');
  });
});

// ── Studio vNext contract: scientific value, maturity, never-rules ─────
import {
  MATURITY_LEVELS,
  completenessWording,
  formatEngineeringTime,
  isMaturityLevel,
  recommendationLabel,
  tieVerdict,
} from '../api/types';
import {
  VNEXT_CANDIDATES_FIXTURE,
  VNEXT_CAPABILITIES_FIXTURE,
  VNEXT_ENERGY_FIXTURE,
  VNEXT_IMPLEMENTATION_FIXTURE,
  VNEXT_PERFORMANCE_FIXTURE,
  VNEXT_SYNTHESIS_FIXTURE,
} from '../fixtures';
import { ScientificValue } from '../components/ScientificValue';

describe('ScientificValue', () => {
  it('carries an epistemic chip, unit and source on every number', () => {
    const { container } = render(
      <ScientificValue
        value={11720}
        unit="cycles"
        epistemic="SIMULATED"
        source="BookSim"
        fidelity="NETWORK_PACKET_SIMULATION"
        qualification="QUALIFIED"
      />,
    );
    const text = container.textContent ?? '';
    expect(text).toContain('11,720');
    expect(text).toContain('cycles');
    expect(text).toContain('SIMULATED');
    expect(text).toContain('BookSim');
    expect(text).toContain('QUALIFIED');
  });

  it('renders an explicit PROVENANCE GAP, never a bare number', () => {
    const { container } = render(
      <ScientificValue value={42} unit="cycles" epistemic={null} />,
    );
    expect(container.textContent ?? '').toContain('PROVENANCE GAP');
  });

  it('marks derived summaries with their sample count', () => {
    const { container } = render(
      <ScientificValue
        value={2.1}
        unit="µs"
        epistemic="MODELLED"
        source="Wave-E model"
        sampleCount={64}
      />,
    );
    expect(container.textContent ?? '').toContain('n=64');
  });
});

describe('maturity vocabulary', () => {
  it('is the closed six-level §44 language', () => {
    expect([...MATURITY_LEVELS]).toEqual([
      'AVAILABLE',
      'EXPERIMENTAL',
      'RESEARCH',
      'HISTORICAL',
      'BLOCKED',
      'NOT_APPLICABLE',
    ]);
    expect(isMaturityLevel('RESEARCH')).toBe(true);
    expect(isMaturityLevel('unsupported')).toBe(false);
    expect(isMaturityLevel(null)).toBe(false);
  });

  it('labels every explorer row with a valid maturity — none hidden', () => {
    for (const row of VNEXT_CAPABILITIES_FIXTURE.rows) {
      expect(isMaturityLevel(row.maturity)).toBe(true);
    }
    const ids = VNEXT_CAPABILITIES_FIXTURE.rows.map((r) => r.capability_id);
    expect(ids).toContain('torus');
    expect(ids).toContain('gec-mecs');
  });
});

describe('completeness wording', () => {
  it('reserves completeness claims for EXHAUSTIVE', () => {
    expect(completenessWording('EXHAUSTIVE', 27, 27)).toContain('all 27');
    const budgeted = completenessWording('BUDGETED', 100, 12480);
    expect(budgeted).toContain('best observed among evaluated candidates');
    expect(budgeted).not.toMatch(/complete over/i);
    const unbounded = completenessWording('UNBOUNDED', 250, null);
    expect(unbounded).toContain('no claim of global optimality');
    expect(VNEXT_SYNTHESIS_FIXTURE.completeness?.may_claim_optimality).toBe(
      false,
    );
  });
});

describe('tie and recommendation language', () => {
  it('reports NO DISTINCTION on ties, never a tie-break winner', () => {
    expect(tieVerdict([11720, 11720])).toBe('NO_DISTINCTION');
    expect(tieVerdict([11720, 13050])).toBeNull();
    expect(tieVerdict([null, null])).toBeNull();
  });

  it('recommends investigation without winner language', () => {
    const label = recommendationLabel();
    expect(label).toContain('further investigation');
    expect(label).not.toMatch(/best measured design/i);
  });
});

describe('engineering units', () => {
  it('uses µs for 11.72µs and never rounds nonzero to zero', () => {
    const v = formatEngineeringTime(0.00001172);
    expect(v.unit).toBe('µs');
    expect(v.text).toContain('11.72');
    const tiny = formatEngineeringTime(1e-12);
    expect(tiny.text).not.toBe('0');
    expect(formatEngineeringTime(null).text).toBe('—');
  });
});

describe('vNext fixtures carry their authority honestly', () => {
  it('keeps generator and measured objectives on separate fields', () => {
    const c = VNEXT_SYNTHESIS_FIXTURE.candidates[0];
    expect(c.generator_objective_name).toBe('traffic_weighted_hops');
    expect(c.measured_cycles).toBe(11720);
    expect(c.measured_backend).toBe('BOOKSIM_STANDALONE');
    // Heuristic provenance: FEASIBLE, never OPTIMAL.
    expect(c.solver_status).toBe('FEASIBLE');
  });

  it('marks Wave-E MODELLED, never MEASURED', () => {
    expect(VNEXT_PERFORMANCE_FIXTURE.epistemic).toBe('MODELLED');
    expect(VNEXT_PERFORMANCE_FIXTURE.predictive_validation).toBe(
      'NOT_ESTABLISHED',
    );
    expect(
      (VNEXT_PERFORMANCE_FIXTURE as unknown as Record<string, unknown>)
        .measured,
    ).toBeUndefined();
  });

  it('keeps energy authorities separate with MECS unavailable', () => {
    const fids = VNEXT_ENERGY_FIXTURE.authorities.map((a) => a.fidelity);
    expect(new Set(fids).size).toBe(fids.length);
    expect(VNEXT_ENERGY_FIXTURE.mecs_native_power.available).toBe(false);
    expect(VNEXT_ENERGY_FIXTURE.mecs_native_power.reason).toContain(
      '_md_chan',
    );
  });

  it('keeps generated/executed/passed distinct in the lab', () => {
    expect(VNEXT_IMPLEMENTATION_FIXTURE.uvm_sva.generated).toBe(true);
    expect(VNEXT_IMPLEMENTATION_FIXTURE.uvm_sva.executed).toBe(false);
    expect(VNEXT_IMPLEMENTATION_FIXTURE.uvm_sva.passed).toBeNull();
    expect(VNEXT_IMPLEMENTATION_FIXTURE.rtl.epistemic).toBe(
      'RTL_SIMULATION',
    );
    expect(
      VNEXT_IMPLEMENTATION_FIXTURE.cdc.system_qualification,
    ).toBe('NOT_ESTABLISHED');
  });

  it('labels demonstration fixtures as demos — never live truth', () => {
    expect(VNEXT_SYNTHESIS_FIXTURE.synthesis_id).toContain('demo');
    expect(VNEXT_CANDIDATES_FIXTURE.entries[0].candidate_id).toContain(
      'demo',
    );
  });
});

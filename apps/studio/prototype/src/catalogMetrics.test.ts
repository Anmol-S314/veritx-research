import { describe, expect, it } from 'vitest';
import { researchRtlVerdict } from './catalogMetrics';
import type { M5RtlPrototype } from './gateway';

const prototype = (overrides: Partial<M5RtlPrototype>): M5RtlPrototype => ({
  topology_id: 'mesh8x8',
  label: 'Mesh 8x8',
  catalog_family: 'mesh',
  scope: 'RESEARCH_VERILOG',
  final_implementation: false,
  required: true,
  verilog_status: 'PRESENT',
  verilog_file: 'CandidateNoCTop.v',
  file_presence: 'PRESENT',
  generation_completeness: 'UNKNOWN',
  proof_status: 'UNVERIFIED',
  lint_status: 'NOT_RUN',
  simulation_status: 'NOT_RUN',
  source_reproduction_status: 'UNKNOWN',
  qualification_status: 'NOT_QUALIFIED',
  historical_snapshot: {
    reported_proof: 'PASS (historical report; not verified against current source)',
    reported_verilog: 'Previously reported emitted; current filesystem presence is checked independently',
  },
  lineage: 'UNKNOWN',
  artifacts: [],
  detail: 'Current file presence is not evidence of complete generation, proof, lint, simulation, reproduction, or qualification.',
  ...overrides,
});

describe('researchRtlVerdict', () => {
  it('reports a present research Verilog file as present, never ready or qualified', () => {
    const verdict = researchRtlVerdict(prototype({ verilog_status: 'PRESENT', file_presence: 'PRESENT', verilog_file: 'CandidateNoCTop.v' }));
    expect(verdict.tone).toBe('green');
    expect(verdict.text).toContain('Research Verilog present');
    expect(verdict.detail).toContain('UNVERIFIED');
    expect(verdict.detail).toContain('Research Verilog only, not product-final RTL');
    expect(verdict.detail).toContain('Previously reported emitted; current filesystem presence is checked independently');
    expect(verdict.detail).toContain('PASS (historical report; not verified against current source)');
    expect(verdict.text).not.toContain('READY');
    expect(verdict.text).not.toContain('qualified');
  });

  it('reports a missing required Verilog file as red', () => {
    const verdict = researchRtlVerdict(prototype({ verilog_status: 'MISSING', file_presence: 'UNKNOWN', verilog_file: null, required: true }));
    expect(verdict.tone).toBe('red');
    expect(verdict.text).toContain('No Verilog file');
    expect(verdict.detail).toContain('UNVERIFIED');
    expect(verdict.detail).toContain('Research Verilog only, not product-final RTL');
    expect(verdict.detail).toContain('Previously reported emitted');
    expect(verdict.detail).toContain('PASS (historical report; not verified against current source)');
  });

  it('reports a missing optional Verilog file as amber', () => {
    const verdict = researchRtlVerdict(prototype({ topology_id: 'dragonflynew', verilog_status: 'MISSING', file_presence: 'UNKNOWN', verilog_file: null, required: false }));
    expect(verdict.tone).toBe('amber');
    expect(verdict.text).toContain('No Verilog file');
    expect(verdict.detail).toContain('Research Verilog only, not product-final RTL');
  });

  it('reports a missing M5 entry as neutral for old catalog jobs', () => {
    for (const verdict of [researchRtlVerdict(null), researchRtlVerdict(undefined)]) {
      expect(verdict.tone).toBe('neutral');
      expect(verdict.text).toContain('No M5 entry');
      expect(verdict.detail).toContain('Research Verilog only, not product-final RTL');
    }
  });
});

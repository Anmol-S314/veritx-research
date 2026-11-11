import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { CandidateEvidence } from './CandidateEvidence';

describe('candidate evidence', () => {
  it('does not turn missing evidence into a zero or recommendation', () => {
    const html = renderToStaticMarkup(createElement(CandidateEvidence, { study: { study: { candidates: [
      { candidate_id: 'missing', evaluation_status: 'FAILED' },
      { candidate_id: 'measured', objective_values: { completion_cycles: 42 } },
    ] } } }));
    expect(html).toContain('Unavailable');
    expect(html).toContain('FAILED');
    expect(html).not.toContain('Recommended in this evaluated set');
  });
  it('renders reported values with authority', () => {
    const html = renderToStaticMarkup(createElement(CandidateEvidence, { study: { study: { candidates: [
      { candidate_id: 'c1', objective_values: { completion_cycles: 42 }, evaluation_authority: 'MEASURED' },
    ] } } }));
    expect(html).toContain('42');
    expect(html).toContain('MEASURED');
  });
  it('names the recommended candidate by its declared name, not its array position', () => {
    const candidate = (id: string, width: number, cycles: number) => ({
      candidate_id: id, guided_patch: { link_width: width }, evaluation_status: 'EVALUATED',
      evaluation_authority: 'certified-backend', pareto_eligible: true,
      objective_values: { completion_cycles: cycles }, objective_availability: { completion_cycles: 'MEASURED' },
      constraint_verdicts: { completion_cycles: 'SATISFIED' },
    });
    const html = renderToStaticMarkup(createElement(CandidateEvidence, { study: {
      definition: { objectives: [{ metric: 'completion_cycles', direction: 'MIN' }], domain: [{ name: 'link_width', values: [64, 128] }] },
      study: { candidates: [candidate('fast', 128, 1459), candidate('slow', 64, 3211)] },
    } }));
    expect(html).toContain('Recommended in this evaluated set: C2');
    expect(html).toContain('Runner-up: C1');
    expect(html).not.toContain('Recommended in this evaluated set: C1');
  });
});

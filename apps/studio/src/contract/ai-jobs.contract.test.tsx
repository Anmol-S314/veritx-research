import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { AITopologyResults } from '../components/AITopologySearch';
import { JobProgress } from '../studio';
import type { AISearchView, JobView } from '../api';

const job: JobView = { contract_version: 1, job_id: 'job-test', project_id: 'p-test',
  kind: 'AI_SEARCH', revision_id: null, state: 'COMPLETED', submitted_at: '', updated_at: '',
  cancellable: true, error_code: null, error_message: null, result: null };
const view: AISearchView = { contract_version: 1, job, model: 'fixture-model',
  base_design_hash: 'sha256:pinned', stale: false, attempts: [{ attempt: 1,
    candidate_id: 'candidate-test', topology: { kind: 'torus', side_length: 7, concentration: 1 },
    rationale: 'A proposal, not an authoritative score.', status: 'EVALUATED', reason: null,
    compilation_status: 'COMPILED', objective_values: { completion_cycles: 2998 },
    adoptable: true, backend_profile: 'CERTIFIED_BOOKSIM_TORUS_DOR_XY_V1',
    execution_fidelity: 'QUALIFIED', requirements_pass: true }] };
const render = (data = view, saved = true) => renderToStaticMarkup(
  <AITopologyResults view={data} saved={saved} busy={false} onAdopt={() => {}} />);

describe('bounded AI and compile controls', () => {
  it('shows verified network units, profile and explicit adoption', () => {
    const html = render();
    expect(html).toContain('2,998 cycles');
    expect(html).toContain('QUALIFIED');
    expect(html).toContain('CERTIFIED_BOOKSIM_TORUS_DOR_XY_V1');
    expect(html).toContain('Use proposal 1 topology in draft');
    expect(html).not.toContain('disabled');
    expect(html).not.toContain('optimal');
  });
  it('cannot adopt over local unsaved or server-stale intent', () => {
    expect(render(view, false)).toContain('disabled');
    const stale = render({ ...view, stale: true });
    expect(stale).toContain('disabled');
    expect(stale).toContain('earlier snapshot');
  });
  it('does not invent zero measurements or adoption for refused evidence', () => {
    const html = render({ ...view, attempts: [{ ...view.attempts[0], status: 'EVIDENCE_INVALID',
      reason: 'Evidence digest mismatch', objective_values: {}, adoptable: false }] });
    expect(html).toContain('No verified measurement');
    expect(html).toContain('Evidence digest mismatch');
    expect(html).not.toContain('0 cycles');
    expect(html).not.toContain('Use topology in draft');
  });
  it('only offers cancellation for active owned process jobs', () => {
    expect(renderToStaticMarkup(<JobProgress job={{ ...job, state: 'RUNNING' }} />)).toContain('Cancel job');
    expect(renderToStaticMarkup(<JobProgress job={{ ...job, state: 'CANCELLING' }} />)).toContain('disabled');
    expect(renderToStaticMarkup(<JobProgress job={job} />)).not.toContain('Cancel job');
    expect(renderToStaticMarkup(<JobProgress job={{ ...job, state: 'RUNNING', cancellable: false }} />)).not.toContain('Cancel job');
  });
  it('routes every Studio compile through the bounded job seam', () => {
    const sources = import.meta.glob(
      ['../pages/design.tsx', '../pages/loom/authoring.tsx', '../hooks/useCompileJob.ts'],
      { query: '?raw', import: 'default', eager: true },
    ) as Record<string, string>;
    expect(Object.keys(sources)).toHaveLength(3);
    for (const [path, text] of Object.entries(sources)) {
      if (path.endsWith('useCompileJob.ts')) {
        expect(text, path).toContain('api.compileJob');
      } else {
        expect(text, path).not.toMatch(/api\.compile\(/);
      }
    }
  });
});

/**
 * RunsView — §28 run library.
 *
 * WIRING NOTE (minimal export): `pages/index.tsx` currently owns the
 * `Runs` page. To adopt this view, replace that page body with
 * `<RunsView />` (same route, no new page needed) — or keep both while
 * migrating. This file is intentionally self-contained apart from shared
 * `studio`/`badges`/`ScientificValue` primitives.
 *
 * Each line carries question-relevant identity: revision, workload,
 * backend, status, qualification, simulated value, fidelity-relevant
 * timestamps and reproduction-input availability. Two honest gaps are
 * marked in code, not papered over:
 * - `RunSummary` carries no per-run question tag, so there is no
 *   question filter (filtering by backend is not the same fact).
 * - `RunSummary` carries no reproduction outcome, so there is no
 *   reproduced/not-reproduced filter (bundle presence means archived
 *   inputs exist, not that reproduction succeeded).
 */
import { useState, type ReactElement } from 'react';
import { api, type RunSummary } from '../api';
import { AsyncView, Link, useAsync, useStudio } from '../studio';
import { Hash, StatusBadge } from './badges';
import { ScientificValue } from './ScientificValue';

function uniqueSorted(values: (string | null | undefined)[]): string[] {
  return Array.from(new Set(values.filter((v): v is string => !!v))).sort();
}

export default function RunsView(): ReactElement {
  const { activeProjectId } = useStudio();
  const [scope, setScope] = useState<'project' | 'all'>(
    activeProjectId ? 'project' : 'all',
  );
  const effectiveScope =
    scope === 'project' && !activeProjectId ? 'all' : scope;
  const [query, setQuery] = useState('');
  const [revision, setRevision] = useState('');
  const [backend, setBackend] = useState('');
  const [status, setStatus] = useState('');
  const [qualification, setQualification] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [archivedOnly, setArchivedOnly] = useState(false);

  const runs = useAsync(
    () => (effectiveScope === 'project' && activeProjectId
      ? api.runs({ projectId: activeProjectId })
      : api.runs()),
    [effectiveScope, activeProjectId],
  );
  const project = useAsync(
    () => (effectiveScope === 'project' && activeProjectId
      ? api.project(activeProjectId)
      : Promise.reject(new Error('no project scope'))),
    [effectiveScope, activeProjectId],
  );
  const activeRev = project.result.state === 'ready'
    ? project.result.data.active_revision_id
    : null;

  return (
    <div className="page">
      <div className="page-head">
        <h2>Runs</h2>
        <div className="segmented small" role="tablist" aria-label="Run scope">
          <button
            role="tab"
            aria-selected={effectiveScope === 'project'}
            className={effectiveScope === 'project' ? 'selected' : ''}
            disabled={!activeProjectId}
            title={activeProjectId || 'no project open'}
            onClick={() => setScope('project')}
          >
            This project
          </button>
          <button
            role="tab"
            aria-selected={effectiveScope === 'all'}
            className={effectiveScope === 'all' ? 'selected' : ''}
            onClick={() => setScope('all')}
          >
            All projects
          </button>
        </div>
      </div>
      <AsyncView result={runs.result} reload={runs.reload}>
        {(data) => {
          const all = data.runs;
          const backends = uniqueSorted(all.map((r) => r.backend));
          const statuses = uniqueSorted(all.map((r) => r.status));
          const quals = uniqueSorted(all.map((r) => r.qualification));
          const revs = uniqueSorted(all.map((r) => r.revision_id));
          const filtered = all.filter((r) => {
            if (query && !(r.run_id.includes(query)
              || (r.display_name ?? '').includes(query))) return false;
            if (revision && r.revision_id !== revision) return false;
            if (backend && r.backend !== backend) return false;
            if (status && r.status !== status) return false;
            if (qualification && r.qualification !== qualification) return false;
            if (from && (r.started_at ?? '') < from) return false;
            if (to && (r.started_at ?? '') > `${to}T23:59:59`) return false;
            if (archivedOnly && !r.bundle_id) return false;
            return true;
          });
          return (
            <>
              <section className="card">
                <div className="form-row">
                  <label>Search
                    <input value={query} onChange={(e) => setQuery(e.target.value)}
                      placeholder="run id or name" />
                  </label>
                  <label>Revision
                    <select value={revision} onChange={(e) => setRevision(e.target.value)}>
                      <option value="">all</option>
                      {revs.map((v) => <option key={v} value={v}>{v}</option>)}
                    </select>
                  </label>
                  <label>Backend
                    <select value={backend} onChange={(e) => setBackend(e.target.value)}>
                      <option value="">all</option>
                      {backends.map((v) => <option key={v} value={v}>{v}</option>)}
                    </select>
                  </label>
                  <label>Status
                    <select value={status} onChange={(e) => setStatus(e.target.value)}>
                      <option value="">all</option>
                      {statuses.map((v) => <option key={v} value={v}>{v}</option>)}
                    </select>
                  </label>
                </div>
                <div className="form-row">
                  <label>Qualification
                    <select value={qualification} onChange={(e) => setQualification(e.target.value)}>
                      <option value="">all</option>
                      {quals.map((v) => <option key={v} value={v}>{v}</option>)}
                    </select>
                  </label>
                  <label>From
                    <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
                  </label>
                  <label>To
                    <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
                  </label>
                  <label className="check">Archived inputs only
                    <input type="checkbox" checked={archivedOnly}
                      onChange={(e) => setArchivedOnly(e.target.checked)} />
                  </label>
                </div>
                <p className="muted">
                  Showing {filtered.length} of {all.length} runs.
                  Question and reproduced/not-reproduced filters are
                  intentionally absent: the run summary contract carries no
                  per-run question tag and no reproduction outcome — a
                  backend filter is not a question filter, and bundle
                  presence means archived inputs exist, not that
                  reproduction succeeded.
                </p>
              </section>
              {filtered.length === 0 ? (
                <p className="muted">No runs match these filters.</p>
              ) : (
                <table className="live-table">
                  <thead>
                    <tr>
                      <th>run</th>
                      {effectiveScope === 'all' && <th>project</th>}
                      <th>revision</th><th>workload</th><th>backend</th>
                      <th>status</th><th>value</th><th>qualification</th>
                      <th>started</th><th>inputs</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((r: RunSummary) => (
                      <tr key={r.run_id}>
                        <td>
                          <Link className="link" to={`/runs/${r.run_id}`}>
                            {r.display_name ?? r.run_id}
                          </Link>
                        </td>
                        {effectiveScope === 'all' && (
                          <td className="muted">{r.project_id}</td>
                        )}
                        <td className="muted">
                          {r.revision_id}
                          {effectiveScope === 'project' && activeRev
                            && r.revision_id !== activeRev && (
                            <span className="stale"> · historical</span>
                          )}
                        </td>
                        <td className="muted">{r.workload_id ?? '—'}</td>
                        <td className="muted">{r.backend ?? '—'}</td>
                        <td><StatusBadge status={r.status ?? 'UNKNOWN'} /></td>
                        <td>
                          {r.completion_cycles == null ? '—' : (
                            <ScientificValue value={r.completion_cycles}
                              unit="cycles" epistemic="SIMULATED"
                              source={r.backend}
                              qualification={r.qualification} />
                          )}
                        </td>
                        <td className="muted">{r.qualification ?? '—'}</td>
                        <td className="muted">{r.started_at ?? '—'}</td>
                        <td className="muted">
                          {r.bundle_id ? <Hash value={r.bundle_id} /> : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          );
        }}
      </AsyncView>
    </div>
  );
}

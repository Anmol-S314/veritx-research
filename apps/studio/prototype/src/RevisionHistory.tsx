import { useEffect, useMemo, useRef, useState } from 'react';
import { gateway, gatewayReason, type RevisionDiff, type RevisionSummary, type RunSummary } from './gateway';
import { Badge, Button, Notice, PageLink, Section } from './ui';
import { stamp } from './format';
import { runVersionLabels } from './runLabel';
import {
  buildRevisionGroups,
  diffRows,
  diffValue,
  previousCompiledRevision,
  revisionTone,
  runScopeLabel,
  type RevisionGroup,
} from './revisionHistory';

type DiffState =
  | { phase: 'loading' }
  | { phase: 'ready'; diff: RevisionDiff }
  | { phase: 'error'; reason: string };

const runTone = (status: string): 'green' | 'red' | 'amber' =>
  status === 'EVALUATED' ? 'green' : status === 'FAILED' ? 'red' : 'amber';

export function RevisionHistory({
  revisions,
  runs,
  activeRevisionId,
  selectedRunId,
  onOpenRun,
}: {
  revisions: RevisionSummary[];
  runs: RunSummary[];
  activeRevisionId?: string | null;
  selectedRunId?: string | null;
  onOpenRun: (runId: string) => void;
}) {
  const groups = useMemo(
    () => buildRevisionGroups(revisions, runs, activeRevisionId),
    [revisions, runs, activeRevisionId],
  );
  const labels = useMemo(() => runVersionLabels(runs), [runs]);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(activeRevisionId ? [activeRevisionId] : []));
  const [diffs, setDiffs] = useState<Record<string, DiffState>>({});
  const diffsRef = useRef<Record<string, DiffState>>({});

  const requestDiff = (group: RevisionGroup) => {
    if (diffsRef.current[group.revisionId]) return;
    if (group.compilationStatus !== 'COMPILED') return;
    const against = previousCompiledRevision(revisions, group.revisionId);
    const loading: DiffState = { phase: 'loading' };
    diffsRef.current = { ...diffsRef.current, [group.revisionId]: loading };
    setDiffs(diffsRef.current);
    gateway.revisionDiff(group.revisionId, against?.revision_id)
      .then(diff => {
        const ready: DiffState = { phase: 'ready', diff };
        diffsRef.current = { ...diffsRef.current, [group.revisionId]: ready };
        setDiffs(diffsRef.current);
      })
      .catch(error => {
        const failed: DiffState = { phase: 'error', reason: gatewayReason(error) };
        diffsRef.current = { ...diffsRef.current, [group.revisionId]: failed };
        setDiffs(diffsRef.current);
      });
  };

  useEffect(() => {
    if (!activeRevisionId) return;
    setExpanded(current => current.has(activeRevisionId) ? current : new Set(current).add(activeRevisionId));
  }, [activeRevisionId]);

  useEffect(() => {
    const active = groups.find(group => group.isActive);
    if (active) requestDiff(active);
    // The active revision is the only group opened automatically. Expanding
    // any other revision loads its diff on demand.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRevisionId]);

  const toggle = (group: RevisionGroup) => {
    const open = expanded.has(group.revisionId);
    setExpanded(current => {
      const next = new Set(current);
      if (next.has(group.revisionId)) next.delete(group.revisionId);
      else next.add(group.revisionId);
      return next;
    });
    if (!open) requestDiff(group);
  };

  return <Section title="Revision history" actions={<Badge>{groups.length} revision{groups.length === 1 ? '' : 's'} · {runs.length} run{runs.length === 1 ? '' : 's'}</Badge>}>
    {groups.map(group => {
      const open = expanded.has(group.revisionId);
      const tone = revisionTone(group);
      return <div className={`revision-group${group.isActive ? ' active' : ''}`} key={group.revisionId}>
        <button type="button" className="revision-head" aria-expanded={open} onClick={() => toggle(group)}>
          <span className="revision-caret" aria-hidden="true">{open ? '▾' : '▸'}</span>
          <span className="mono revision-id">{group.label}</span>
          {group.isActive && <Badge tone="blue">active</Badge>}
          <Badge tone={tone}>{group.compilationStatus ?? 'UNKNOWN'}</Badge>
          <span className="revision-meta">{stamp(group.createdAt)}</span>
          <span className="revision-spacer" />
          <span className="revision-count">{group.runs.length ? `${group.runs.length} run${group.runs.length === 1 ? '' : 's'}` : 'No runs'}</span>
        </button>
        {open && <div className="revision-body">
          {group.error && <Notice tone={tone === 'amber' ? 'amber' : 'red'}><strong>{group.label} did not compile.</strong> {group.error}</Notice>}
          {group.compilationStatus === 'COMPILED' && <RevisionDiffSummary state={diffs[group.revisionId]} />}
          {group.runs.length ? <div className="table-scroll"><table>
            <thead><tr><th>Run</th><th>Evaluated</th><th>Scope</th><th>Status</th><th>Requirements</th><th>Bundle</th><th /></tr></thead>
            <tbody>
              {group.runs.map(run => {
                const label = labels.get(run.run_id) ?? `${group.label} · run ?`;
                const selected = run.run_id === selectedRunId;
                return <tr key={run.run_id} className={selected ? 'selected' : ''}>
                  <th><span className="mono run-version">{label}</span><small className="block muted" title={run.run_id}>{run.run_id.slice(0, 13)}…</small></th>
                  <td className="mono">{stamp(run.completed_at)}</td>
                  <td>{runScopeLabel(run)}</td>
                  <td><Badge tone={runTone(run.status)}>{run.status}</Badge></td>
                  <td>{run.requirements_pass === undefined || run.requirements_pass === null ? 'Not recorded' : run.requirements_pass ? 'Pass' : 'Fail'}</td>
                  <td>{run.bundle_id ? 'Recorded' : 'No bundle'}</td>
                  <td><Button onClick={() => onOpenRun(run.run_id)}>{selected ? 'Open' : 'Open analysis'}</Button></td>
                </tr>;
              })}
            </tbody>
          </table></div> : <div className="revision-empty">
            <span>No evaluation yet.</span>
            {group.isActive && <PageLink page="analysis/summary">Evaluate {group.label}</PageLink>}
          </div>}
        </div>}
      </div>;
    })}
  </Section>;
}

function RevisionDiffSummary({ state }: { state?: DiffState }) {
  if (!state) return null;
  if (state.phase === 'loading') return <p className="meta-line">Reading changes from the previous compiled revision…</p>;
  if (state.phase === 'error') return <p className="meta-line">Change summary unavailable: {state.reason}</p>;
  const diff = state.diff;
  if (!diff.has_basis) return <p className="meta-line">First compiled revision; there is no predecessor to compare.</p>;
  const rows = diffRows(diff);
  const meaningful = rows.filter(row => row.field !== 'design_hash' && row.field !== 'fabric_identity');
  const shown = meaningful.length ? meaningful : rows;
  if (!shown.length) return <p className="meta-line">No declared design change from {diff.against_display_name ?? 'the previous revision'}.</p>;
  if (!meaningful.length) return <p className="meta-line">No declared design change from {diff.against_display_name ?? 'the previous revision'}; the design hash changed.</p>;
  return <div className="revision-diff">
    <strong>What changed from {diff.against_display_name ?? 'the previous revision'}</strong>
    <ul>
      {shown.slice(0, 6).map((row, index) => <li key={`${row.field}-${index}`}>
        <span className="mono">{row.field}</span>: {diffValue(row.before)} → {diffValue(row.after)}
      </li>)}
    </ul>
    {shown.length > 6 && <small>{shown.length - 6} more change{shown.length - 6 === 1 ? '' : 's'}</small>}
  </div>;
}

/** A grouped run picker. Revisions with no runs are omitted from the picker
 *  but remain visible in the history. */
export function RunSelect({
  revisions,
  runs,
  value,
  onChange,
  ariaLabel,
  activeRevisionId,
}: {
  revisions: RevisionSummary[];
  runs: RunSummary[];
  value: string;
  onChange: (runId: string) => void;
  ariaLabel: string;
  activeRevisionId?: string | null;
}) {
  const groups = useMemo(
    () => buildRevisionGroups(revisions, runs, activeRevisionId).filter(group => group.runs.length > 0),
    [revisions, runs, activeRevisionId],
  );
  const labels = useMemo(() => runVersionLabels(runs), [runs]);
  return <select aria-label={ariaLabel} value={value} onChange={event => onChange(event.target.value)}>
    <option value="">Select a run…</option>
    {groups.map(group => <optgroup key={group.revisionId} label={`${group.label}${group.isActive ? ' (active)' : ''}`}>
      {group.runs.map(run => <option key={run.run_id} value={run.run_id}>
        {labels.get(run.run_id) ?? run.run_id} · {run.status}
      </option>)}
    </optgroup>)}
  </select>;
}

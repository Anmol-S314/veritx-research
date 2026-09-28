import type { ReactElement } from 'react';
import { api, type RevisionDiffView } from '../../api';
import { AsyncView, useAsync } from '../../studio';
import { EmptyState } from './EmptyState';

/** P4 — change / impact analysis. Consumes the backend's stable
 * revision-diff projection; React infers nothing. */
export default function RevisionDiff({ revisionId }: {
  revisionId: string;
}): ReactElement {
  const { result, reload } = useAsync(
    () => api.revisionDiff(revisionId), [revisionId]);
  return (
    <AsyncView result={result} reload={reload}>
      {(diff) => <RevisionDiffBody diff={diff} />}
    </AsyncView>
  );
}

export function RevisionDiffBody({ diff }: {
  diff: RevisionDiffView;
}): ReactElement {
  if (!diff.has_basis) {
    return (
      <section className="card" aria-label="Revision changes">
        <h4>Changes since previous revision</h4>
        <EmptyState title="No predecessor to compare against.">
          <p>{diff.reason}</p>
        </EmptyState>
      </section>
    );
  }
  const total = diff.design_changes.length
    + diff.derived_changes.length + diff.capability_changes.length;
  return (
    <section className="card" aria-label="Revision changes">
      <h4>
        Changes since {diff.against_display_name ?? diff.against_revision_id}
      </h4>
      {total === 0 ? (
        <p className="muted">
          No declared, derived or capability differences — this revision
          is identical to its predecessor in every projected field.
        </p>
      ) : (
        <>
          <ChangeTable title="Design changes"
                       rows={diff.design_changes} />
          <ChangeTable title="Derived changes"
                       rows={diff.derived_changes} />
          <ChangeTable title="Capability changes"
                       rows={diff.capability_changes} />
        </>
      )}
    </section>
  );
}

function ChangeTable({ title, rows }: {
  title: string;
  rows: { field: string; before: unknown; after: unknown; kind: string;
          detail?: string | null }[];
}): ReactElement | null {
  if (rows.length === 0) return null;
  return (
    <>
      <h5 className="inspector-label">{title}</h5>
      <table className="tbl">
        <thead>
          <tr><th>field</th><th>before</th><th>after</th><th>kind</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.field}>
              <td><code>{r.field}</code></td>
              <td className="num">{fmtValue(r.before)}</td>
              <td className="num">{fmtValue(r.after)}</td>
              <td className="muted">{r.kind}{r.detail ? ` · ${r.detail}` : ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function fmtValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'string' && value.length > 24) {
    return `${value.slice(0, 24)}…`;
  }
  return String(value);
}

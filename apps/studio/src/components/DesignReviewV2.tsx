import { type ReactElement } from 'react';
import type { DesignViewV2 } from '../api';
import DesignViewV2Editor, {
  FINDING_GLYPH, FINDING_LABEL, READINESS_LABEL,
} from './DesignViewV2Editor';
import { fmtNum } from './badges';

/**
 * Review is `DesignViewV2 { presentation: "review" }` — the same projection
 * as authoring, not a second model (Gate 7 §2).
 *
 * Review may not hide active science (Gate 7 §6): the Guided/Expert
 * disclosure depth is not an input to its content, so every section is
 * expanded and read-only. It also may not claim a later stage (Gate 7
 * §39/§40) — the certificate, qualification, measurements and requirement
 * verdicts do not exist yet and are never rendered as current facts.
 */
export default function DesignReviewV2({
  view, doc, onCompile, compiling, onBack, onRefresh, onGoToSection,
  sectionId, onSectionChange,
}: {
  view: DesignViewV2;
  doc: Record<string, unknown>;
  onCompile: () => void;
  compiling: boolean;
  onBack: () => void;
  onRefresh: () => void;
  onGoToSection: (owner: string) => void;
  sectionId: string;
  onSectionChange: (id: string) => void;
}): ReactElement {
  const stale = view.review_freshness === 'STALE';
  const blocked = view.validation_findings.some((f) => f.blocking);
  const snapshot = view.draft_identity.draft_design_hash;

  return (
    <div className="review-v2">
      <header className="review-head">
        <div>
          <h2>Review — draft</h2>
          <p className="muted">
            {view.parent_revision_ref
              ? `based on ${view.parent_revision_ref.label}`
              : 'no parent revision'}
            {' · '}
            <code>{snapshot ? `${snapshot.slice(0, 18)}…` : '—'}</code>
            {' · '}
            {view.review_freshness}
          </p>
        </div>
        <span className={`readiness readiness-${view.readiness.toLowerCase()}`}>
          {READINESS_LABEL[view.readiness]}
        </span>
      </header>

      {stale && (
        <div className="finding finding-blocking_error" role="alert">
          <div className="finding-head">
            <span className="finding-glyph" aria-hidden="true">!</span>
            <strong>This review is stale.</strong>
          </div>
          <p className="finding-body">
            The draft changed after this review was generated. Reviewed{' '}
            <code>
              {view.review_snapshot?.reviewed_draft_design_hash?.slice(0, 18) ?? '—'}…
            </code>{' '}
            · current <code>{snapshot?.slice(0, 18) ?? '—'}…</code>
          </p>
          <p className="finding-remedies">
            <button className="btn" onClick={onRefresh}>Refresh review</button>
          </p>
        </div>
      )}

      <DesignViewV2Editor
        view={view}
        doc={doc}
        onDocChange={() => undefined}
        onGoToSection={onGoToSection}
        readOnly
        sectionId={sectionId}
        onSectionChange={onSectionChange}
      />

      <section className="card">
        <h3>Pre-compile derived summary</h3>
        {view.derived_summaries.length === 0 ? (
          <p className="muted">
            Not derived — the design does not reach the derivation stage.
          </p>
        ) : (
          <div className="kv-grid">
            {view.derived_summaries.map((summary) => (
              <div className="kv" key={summary.id}>
                <span>{summary.label}</span>
                <span className="num">{fmtNum(summary.value)}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="card">
        <h3>Capability consequences</h3>
        {view.capability_consequences.length === 0 ? (
          <p className="muted">
            No downstream limitation is caused by the current choices.
          </p>
        ) : (
          <ul className="consequence-list">
            {view.capability_consequences.map((consequence) => (
              <li key={consequence.capability_id}>
                <code>{consequence.capability_id}</code>{' '}
                <strong>{consequence.choice}</strong> — {consequence.wiring}
                {consequence.reason ? ` · ${consequence.reason}` : ''}
                {consequence.claim_scope && (
                  <p className="muted">{consequence.claim_scope}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card">
        <h3>Changes from {view.parent_revision_ref?.label ?? 'parent'}</h3>
        {!view.scientific_diff || view.scientific_diff.length === 0 ? (
          <p className="muted">
            No scientific change from the parent revision.
          </p>
        ) : (
          <table className="tbl">
            <thead>
              <tr><th>field</th><th>before</th><th>after</th><th>change</th></tr>
            </thead>
            <tbody>
              {view.scientific_diff.map((entry) => (
                <tr key={entry.field}>
                  <td><code>{entry.field}</code></td>
                  <td>{fmtNum(entry.before)}</td>
                  <td>{fmtNum(entry.after)}</td>
                  <td className="muted">{entry.kind}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <h3>Completeness</h3>
        <p className="muted">{view.completeness.law}</p>
        <div className="kv">
          <span>active scientific fields</span>
          <span className="num">
            {view.completeness.active_scientific_fields.length}
          </span>
        </div>
        <div className="kv">
          <span>represented</span>
          <span className="num">{view.completeness.represented_fields.length}</span>
        </div>
        {view.completeness.invariant_holds ? (
          <p className="good">✓ every active scientific field is represented</p>
        ) : (
          <p className="bad">
            unrepresented: {view.completeness.unrepresented_active_fields.join(', ')}
          </p>
        )}
        {view.completeness.non_active_fields.length > 0 && (
          <details>
            <summary>
              Non-active in this draft ({view.completeness.non_active_fields.length})
            </summary>
            <ul className="muted">
              {view.completeness.non_active_fields.map((row) => (
                <li key={row.field}>
                  <code>{row.field}</code> — {row.reason}
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>

      <footer className="review-actions">
        <button className="btn" onClick={onBack}>← Back to edit</button>
        <span className="muted">
          capability semantics {view.capability_semantics_version}
        </span>
        <button
          className="btn btn-primary"
          disabled={compiling || stale || blocked}
          title={stale ? 'Refresh the review before compiling'
            : blocked ? 'Blocking findings must be resolved'
              : undefined}
          onClick={onCompile}
        >
          {compiling ? 'Compiling…' : 'Compile Design'}
        </button>
      </footer>
    </div>
  );
}

export { FINDING_GLYPH, FINDING_LABEL };

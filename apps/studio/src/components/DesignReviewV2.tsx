import { type ReactElement } from 'react';
import { baseDocument } from '../canonicalDraft';
import type { DesignViewV2 } from '../api';
import DesignViewV2Editor, {
  FINDING_GLYPH, FINDING_LABEL, READINESS_LABEL,
} from './DesignViewV2Editor';
import { fmtNum, humanize } from './badges';
import { topologyName } from './TopologyIntentEditor';

function fmtCount(value: unknown): string {
  return typeof value === 'number' ? value.toLocaleString('en-US') : '—';
}

function ScenarioSummary({ doc: root }: { doc: Record<string, unknown> }): ReactElement {
  const doc = baseDocument(root);
  const workload = (doc['workload'] ?? {}) as Record<string, unknown>;
  const dims = (['tp', 'pp', 'ep', 'dp'] as const).map((d) => {
    const raw = workload[d];
    return typeof raw === 'number' ? raw : null;
  });
  const ranks = dims.every((d) => d !== null)
    ? (dims as number[]).reduce((a, b) => a * b, 1) : null;
  const agents = Array.isArray(doc['agents'])
    ? (doc['agents'] as Record<string, unknown>[]) : [];
  const agentLine = agents
    .filter((a) => a['kind'] != null && typeof a['count'] === 'number')
    .map((a) => `${fmtCount(a['count'])} × ${String(a['kind']).replace(/_/g, ' ')}`)
    .join(' · ') || '—';
  const noc = (doc['noc_controls'] ?? doc['noc_config'] ?? {}) as Record<string, unknown>;
  const physical = (doc['physical'] ?? {}) as Record<string, unknown>;
  const requirements = Array.isArray(doc['requirements'])
    ? (doc['requirements'] as Record<string, unknown>[]) : [];
  const collectives = Array.isArray(workload['collectives'])
    ? (workload['collectives'] as Record<string, unknown>[]) : [];
  return (
    <section className="card" aria-label="Scenario summary">
      <h3>{root.schema_version === 5 ? 'Base scenario · BASE_ONLY' : 'Scenario'}</h3>
      <div className="kv">
        <span>Workload</span>
        <span>
          {String(workload['model_name'] ?? workload['model_family'] ?? '—')}
          {workload['serving_mode'] != null ? ` · ${String(workload['serving_mode'])}` : ''}
          {dims[0] != null || dims[1] != null || dims[2] != null || dims[3] != null
            ? ` · TP${dims[0] ?? '·'} / PP${dims[1] ?? '·'} / EP${dims[2] ?? '·'} / DP${dims[3] ?? '·'}`
            : ''}
          {ranks != null ? ` → ${ranks} ranks` : ''}
          {collectives.length > 0 ? ` · ${collectives.length} communication phase${collectives.length === 1 ? '' : 's'}` : ''}
        </span>
      </div>
      <div className="kv"><span>System</span><span>{agentLine}</span></div>
      <div className="kv">
        <span>Fabric</span>
        <span>
          {topologyName(doc)}
          {noc['link_width'] != null ? ` · ${String(noc['link_width'])}-bit links` : ''}
          {physical['clock_freq_mhz'] != null ? ` · ${String(physical['clock_freq_mhz'])} MHz` : ''}
        </span>
      </div>
      <div className="kv">
        <span>Goals</span>
        <span>
          {requirements.length === 0 ? '—' : requirements.map((r, i) => (
            <span key={i}>
              {i > 0 ? ' · ' : ''}
              {String(r['qos_class'] ?? 'requirement').replace(/_/g, ' ')}
              {r['latency_ceiling_cycles'] != null
                ? ` < ${fmtCount(r['latency_ceiling_cycles'])} cycles` : ''}
            </span>
          ))}
        </span>
      </div>
      <p className="muted">
        Evaluation is decided on the Evaluate page from the compiled
        revision — this review declares intent only.
      </p>
    </section>
  );
}

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

  const intentGroups: { title: string; rows: typeof view.derived_summaries }[] = [
    { title: 'System', rows: [] },
    { title: 'Workload', rows: [] },
    { title: 'Fabric', rows: [] },
    { title: 'Routing / resources', rows: [] },
    { title: 'Requirements', rows: [] },
  ];
  for (const summary of view.derived_summaries) {
    const hay = `${summary.id} ${summary.label}`.toLowerCase();
    const index = /agent|router|channel|endpoint|seat|inventor|placement|memory|address|clock|physical/.test(hay) ? 0
      : /rank|workload|collective|class|operation|dispatch|combine|dependenc|parallel/.test(hay) ? 1
      : /topolog|link|width|mesh|torus|express|radix|concentration/.test(hay) ? 2
      : /rout|vc|arbitrat|escape|deadlock/.test(hay) ? 3
      : /requirement|bound|ceiling|qos/.test(hay) ? 4 : 1;
    intentGroups[index].rows.push(summary);
  }

  return (
    <div className="review-v2">
      <header className="review-head">
        <div>
          <h2>You are about to compile</h2>
          <p className="muted">
            Scientific intent only — no certificate, qualification or
            measurement exists yet.{' '}
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

      <ScenarioSummary doc={doc} />

      <section className="card" aria-label="Intent summary">
        <h3>{doc.schema_version === 5 ? 'Base intent summary · BASE_ONLY' : 'Intent summary'}</h3>
        {view.derived_summaries.length === 0 ? (
          <p className="muted">
            Not derived — the design does not reach the derivation stage.
          </p>
        ) : (
          intentGroups.filter((g) => g.rows.length > 0).map((group) => (
            <div key={group.title}>
              <h4>{group.title}</h4>
              <div className="kv-grid">
                {group.rows.map((summary) => (
                  <div className="kv" key={summary.id}>
                    <span>{summary.label}</span>
                    <span className="num">{fmtNum(summary.value)}</span>
                  </div>
                ))}
              </div>
            </div>
          ))
        )}
      </section>

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
        <h3>Capability impact</h3>
        <p className="muted">
          What each choice means downstream — fully qualified, staged, or
          research — before anything is built.
        </p>
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
          <>
          <table className="tbl">
            <thead>
              <tr><th>field</th><th>before</th><th>after</th><th>change</th></tr>
            </thead>
            <tbody>
              {view.scientific_diff.map((entry) => (
                <tr key={entry.field}>
                  <td title={`canonical path: ${entry.field}`}>{humanize(entry.field.split('.').pop() ?? entry.field)}</td>
                  <td>{fmtNum(entry.before)}</td>
                  <td>{fmtNum(entry.after)}</td>
                  <td className="muted">{entry.kind}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <details className="expert-provenance">
            <summary>Expert provenance — canonical field paths</summary>
            <p className="muted">
              {view.scientific_diff.map((entry) => entry.field).join(', ')}
            </p>
          </details>
          </>
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

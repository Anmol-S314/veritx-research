/** What was MEASURED for the knobs this draft authors.
 *
 * Reads the executed-configuration corpus the sweep cohorts produced and
 * reports, per case, whether its authored knobs agree with the draft's. Like
 * the knob editor, this file knows NO knob names: agreement is computed by
 * comparing whatever keys the draft and the case both set, so a knob added
 * tomorrow is compared the day both sides carry it.
 *
 * A corpus entry is evidence that its own configuration reached an outcome.
 * Its absence says nothing about whether that configuration would work.
 */
import { useMemo, useState, type ReactElement } from 'react';
import { useAsync } from '../studio';
import { api } from '../api';
import type { ExecutionEvidenceView } from '../api/types';

type KnobMap = Record<string, Record<string, unknown>>;

interface Agreement { compared: number; agreed: KnobMap; conflicts: KnobMap }

/** Structural comparison. No knob is named. */
function agree(draft: KnobMap, cases: KnobMap): Agreement {
  const agreed: KnobMap = {};
  const conflicts: KnobMap = {};
  let compared = 0;
  for (const [block, values] of Object.entries(draft)) {
    const other = cases[block];
    if (!other) continue;
    for (const [name, value] of Object.entries(values)) {
      if (!(name in other)) continue;
      compared += 1;
      const bucket = other[name] === value ? agreed : conflicts;
      (bucket[block] ??= {})[name] = { draft: value, case: other[name] };
    }
  }
  return { compared, agreed, conflicts };
}

/** The knobs this draft actually sets (non-null), per request block. */
function authored(doc: Record<string, unknown>): KnobMap {
  const out: KnobMap = {};
  for (const block of ['noc_controls', 'noc_config', 'topology']) {
    const raw = doc[block];
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) continue;
    const values = Object.fromEntries(
      Object.entries(raw as Record<string, unknown>).filter(([, v]) => v != null),
    );
    if (Object.keys(values).length) out[block] = values;
  }
  return out;
}

/** "n agree · m differ", or an em dash when the case carried no knobs. */
function agreementCell(match: Agreement | null, hasKnobs: boolean): string {
  if (!hasKnobs || !match || match.compared === 0) return '—';
  const same = match.compared - Object.keys(match.conflicts).length;
  const differ = Object.keys(match.conflicts).length;
  return differ ? `${same} · ${differ} differ` : `${same} agree`;
}

function metricRows(analyses: Record<string, {
  status?: string | null;
  backend?: string | null;
  profile?: string | null;
  qualification?: string | null;
  fidelity?: string | null;
  metrics?: Record<string, number>;
}>): string {
  return Object.entries(analyses).map(([question, row]) => {
    const bits = [row.status];
    if (row.profile) bits.push(row.profile);
    else if (row.qualification) bits.push(row.qualification);
    const m = Object.entries(row.metrics ?? {})
      .filter(([k]) => /cycles|completion|throughput|latency/i.test(k))
      .slice(0, 2)
      .map(([k, v]) => `${k} ${v}`);
    if (m.length) bits.push(m.join(' · '));
    return `${question}: ${bits.filter(Boolean).join(' · ')}`;
  }).join('\n');
}

export default function ExecutionEvidence({ doc }: {
  doc: Record<string, unknown>;
}): ReactElement {
  const index = useAsync<ExecutionEvidenceView>(() => api.executionEvidence(), []);
  const [onlyMatching, setOnlyMatching] = useState(false);
  const mine = useMemo(() => authored(doc), [doc]);

  if (index.result.state === 'loading') {
    return <p className="muted" role="status">Reading the executed-configuration corpus…</p>;
  }
  if (index.result.state === 'error') {
    return (
      <div role="alert">
        <p className="t-bad">✗ evidence corpus unreadable: {index.result.error.message}</p>
        <button className="btn btn-small" onClick={() => index.reload()}>Retry</button>
      </div>
    );
  }
  const data = index.result.data;

  return (
    <section className="topology-intent" aria-label="Executed configurations">
      <div>
        <h3 className="section-title">Executed configurations</h3>
        <p className="muted">{data.notes}</p>
        <p className="muted">
          {data.case_count} recorded case(s) across{' '}
          {data.cohorts.length} cohort(s).{' '}
          <label>
            <input type="checkbox" checked={onlyMatching}
              onChange={(e) => setOnlyMatching(e.target.checked)} />
            {' '}only cases agreeing with this draft
          </label>
        </p>
      </div>
      {data.cohorts.map((cohort) => {
        const cases = cohort.cases.map((entry) => ({
          entry,
          match: Object.keys(entry.knobs).length ? agree(mine, entry.knobs as KnobMap) : null,
        }));
        // "Matching" means the case carries knobs and at least one of them is
        // also authored by this draft. Cases that recorded no knobs (preset
        // and configuration sweeps) can never match, and are hidden by the
        // filter rather than counted as agreeing.
        const shown = onlyMatching
          ? cases.filter((c) => (c.match?.compared ?? 0) > 0)
          : cases;
        return (
          <details className="subtle" key={cohort.cohort} open={cohort.cohort === data.cohorts[0]?.cohort}>
            <summary>
              {cohort.cohort} — {cohort.evaluated} evaluated / {cohort.cases.length} cases
            </summary>
            <div style={{ maxHeight: 360, overflow: 'auto' }}>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>case</th><th>outcome</th><th className="num">agrees</th><th>detail</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map(({ entry, match }) => (
                    <tr key={entry.case_id}>
                      <td><code>{entry.case_id}</code></td>
                      <td>
                        <span className={entry.status === 'EVALUATED' ? 't-ok' : 't-warn'}>
                          {entry.status ?? '—'}
                        </span>
                        {entry.certificate && (
                          <span className={entry.certificate === 'PASS' ? 't-ok' : 't-bad'}>
                            {' '}cert {entry.certificate}
                          </span>
                        )}
                        {entry.reason && <div className="muted">{entry.reason}</div>}
                      </td>
                      <td className="num">
                        {agreementCell(match, Object.keys(entry.knobs).length > 0)}
                      </td>
                      <td className="muted" style={{ whiteSpace: 'pre-line', fontSize: 11 }}>
                        {metricRows(entry.analyses as never)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {shown.length === 0 && <p className="muted">No case in this cohort carries the knobs this draft authors.</p>}
            </div>
          </details>
        );
      })}
    </section>
  );
}
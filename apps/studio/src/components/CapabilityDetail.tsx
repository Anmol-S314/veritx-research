import type { ReactElement } from 'react';
import {
  MATURITY_BLURB,
  type CapabilityRecord,
} from './ImplementationLab/capabilityLedger';

const STAGE_COLUMNS = [
  'intent',
  'artifact',
  'verifier',
  'projection',
  'executable',
  'qualified',
  'product',
  'evidence',
] as const;

function cellTone(cell: string): string {
  const upper = cell.toUpperCase();
  if (/^(YES|AVAILABLE|QUALIFIED)\b/.test(upper)) return 'stage-yes';
  if (/^(NO|—)\b/.test(upper) || upper.startsWith('NO ')) return 'stage-no';
  return 'stage-partial';
}

/** §33 Capability detail: status matrix, what-it-is, implementation,
 * historical evidence (with source), missing bridge, actions. */
export function CapabilityDetail({ cap }: { cap: CapabilityRecord }): ReactElement {
  return (
    <div className="card capability-detail">
      <h3>
        {cap.name}{' '}
        <span className={`maturity maturity-${cap.maturity.toLowerCase().replace(/ /g, '-')}`}>
          {cap.maturity}
        </span>
      </h3>
      <p className="muted">
        {cap.id} · {MATURITY_BLURB[cap.maturity]} — {cap.maturityNote}.
      </p>
      <h4>Status</h4>
      <table className="live-table capability-matrix">
        <thead>
          <tr>
            {STAGE_COLUMNS.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            {STAGE_COLUMNS.map((c) => (
              <td key={c} className={cellTone(cap.stages[c])} title={cap.stages[c]}>
                {cap.stages[c]}
              </td>
            ))}
          </tr>
        </tbody>
      </table>
      <h4>What it is</h4>
      <p>{cap.whatItIs}</p>
      <h4>Existing implementation</h4>
      <ul>
        {cap.implementation.map((path) => (
          <li key={path}>
            <code title={`source path: ${path}`}>{path}</code>
          </li>
        ))}
      </ul>
      <h4>Historical evidence</h4>
      <ul>
        {cap.historicalEvidence.map((row) => (
          <li key={row}>{row}</li>
        ))}
      </ul>
      <h4>Missing bridge</h4>
      <p>{cap.missingBridge}</p>
      <h4>Actions</h4>
      <ul>
        {cap.actions.map((a) => (
          <li key={a.label}>
            <strong>{a.label}</strong> <span className="muted">— {a.detail}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

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

export const LADDER_STAGES = [
  'INTENT',
  'ARTIFACT',
  'VERIFY',
  'PROJECT',
  'EXECUTE',
  'QUALIFY',
  'PRODUCT',
] as const;

export type LadderLevel = 0 | 0.5 | 1;

export interface LadderCell {
  stage: (typeof LADDER_STAGES)[number];
  level: LadderLevel;
  detail: string;
}

export function ladderLevel(cell: string | undefined | null): LadderLevel {
  const upper = (cell ?? '').trim().toUpperCase();
  if (!upper) return 0;
  if (/^YES\b/.test(upper)) return 1;
  if (/^(NO\b|NO\s|N\/A\b|NOT\s|NONE\b|ABSENT\b|NEVER\b|—)/.test(upper)) return 0;
  return 0.5;
}

export function ladderCells(stages: CapabilityRecord['stages']): LadderCell[] {
  const picked = [
    stages.intent,
    stages.artifact,
    stages.verifier,
    stages.projection,
    stages.executable,
    stages.qualified,
    stages.product,
  ];
  return LADDER_STAGES.map((stage, i) => ({
    stage,
    level: ladderLevel(picked[i]),
    detail: picked[i] ?? '—',
  }));
}

export function StageLadder({
  cells,
  label,
}: {
  cells: LadderCell[];
  label: string;
}): ReactElement {
  return (
    <span
      role="img"
      aria-label={`${label} maturity ladder: ${cells
        .map((c) => `${c.stage}=${c.level === 1 ? 'on' : c.level === 0.5 ? 'partial' : 'off'}`)
        .join(', ')}`}
      title={cells.map((c) => `${c.stage}: ${c.detail}`).join('\n')}
      style={{ display: 'inline-flex', gap: 4, alignItems: 'center', verticalAlign: 'middle' }}
    >
      {cells.map((c) => (
        <span
          key={c.stage}
          title={`${c.stage}: ${c.detail}`}
          style={{
            width: 10,
            height: 10,
            borderRadius: '50%',
            display: 'inline-block',
            border: '1px solid currentColor',
            opacity: c.level === 0 ? 0.45 : 1,
            backgroundColor:
              c.level === 1 ? '#1f6c4f' : c.level === 0.5 ? '#9a6217' : 'transparent',
          }}
        />
      ))}
    </span>
  );
}

function cellTone(cell: string): string {
  const upper = cell.toUpperCase();
  if (/^(YES|AVAILABLE|QUALIFIED)\b/.test(upper)) return 'stage-yes';
  if (/^(NO|—)\b/.test(upper) || upper.startsWith('NO ')) return 'stage-no';
  return 'stage-partial';
}

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
      <p className="muted">
        Seven-stage ladder (INTENT → MATERIALIZED → VERIFIED → PROJECTED →
        EXECUTABLE → QUALIFIED → PRODUCT):{' '}
        <StageLadder cells={ladderCells(cap.stages)} label={cap.name} />
      </p>
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

import type { ReactElement, ReactNode } from 'react';
import { fmtNum, humanize } from './badges';

export const EPISTEMIC_CLASSES = [
  'DECLARED',
  'DERIVED',
  'VERIFIED',
  'SIMULATED',
  'MODELLED',
] as const;

export type EpistemicClass = (typeof EPISTEMIC_CLASSES)[number];

export function isEpistemic(value: unknown): value is EpistemicClass {
  return (
    typeof value === 'string' &&
    (EPISTEMIC_CLASSES as readonly string[]).includes(value)
  );
}

export const QUESTION_LABELS: Record<string, string> = {
  NETWORK_COMPLETION: 'Network completion',
  SYSTEM_MAKESPAN: 'Distributed schedule',
  COMMUNICATION_EXPOSURE: 'Communication exposure',
  PER_RANK_COMPLETION: 'Per-rank completion',
  DRAM_TIMING: 'DRAM timing',
  SERVING_TTFT: 'Serving TTFT',
  SERVING_COMPLETION: 'Serving completion',
};

export function questionLabel(question: string): string {
  return QUESTION_LABELS[question] ?? humanize(question);
}

export const BACKEND_LABELS: Record<string, string> = {
  BOOKSIM_STANDALONE: 'BookSim',
  BOOKSIM: 'BookSim',
  ASTRA2_EMBEDDED_BOOKSIM: 'ASTRA',
  ASTRA: 'ASTRA',
  RAMULATOR2_HBM3_V1: 'Ramulator',
  RAMULATOR: 'Ramulator',
  CANONICAL_SERVING: 'Serving',
  WAVE_E_MODEL: 'Wave-E model',
};

export function backendLabel(backendId: string | null | undefined): string {
  if (!backendId) return '—';
  if (BACKEND_LABELS[backendId]) return BACKEND_LABELS[backendId];
  const upper = backendId.toUpperCase();
  for (const [key, label] of Object.entries(BACKEND_LABELS)) {
    if (upper.includes(key)) return label;
  }
  return backendId;
}

export function EpistemicChip({ value }: { value: string | null | undefined }): ReactElement {
  const cls = isEpistemic(value) ? value.toLowerCase() : 'unknown';
  return (
    <span
      className={`epistemic epistemic-${cls}`}
      title={
        isEpistemic(value)
          ? `epistemic class: ${value} — how this number was produced`
          : `no epistemic class carried (got ${value ?? 'nothing'}) — provenance gap, not a bare fact`
      }
    >
      {value ?? 'PROVENANCE GAP'}
    </span>
  );
}

export function ScientificValue({
  value,
  unit,
  epistemic,
  source,
  fidelity,
  qualification,
  sampleCount,
}: {
  value: unknown;
  unit?: string | null;
  epistemic: string | null | undefined;
  source?: string | null;
  fidelity?: string | null;
  qualification?: string | null;
  sampleCount?: number | null;
}): ReactElement {
  const provenance = [
    source ? `source: ${source}` : null,
    fidelity ? `fidelity: ${fidelity}` : null,
    qualification ? `qualification: ${qualification}` : null,
    sampleCount != null
      ? `DERIVED SUMMARY over ${sampleCount} authenticated rows`
      : null,
  ].filter(Boolean).join(' · ');
  return (
    <span className="sci-value" title={provenance || 'no provenance carried'}>
      <span className="num">{fmtNum(value)}</span>
      {unit ? <span className="muted"> {unit}</span> : null}{' '}
      <EpistemicChip value={epistemic} />
      {source || fidelity || qualification ? (
        <span className="muted sci-source">
          {' '}
          · {[source, fidelity, qualification].filter(Boolean).join(' · ')}
        </span>
      ) : null}
      {sampleCount != null ? (
        <span className="muted"> · n={sampleCount}</span>
      ) : null}
    </span>
  );
}

export function SimulatedTimeNote(): ReactElement {
  return (
    <span className="muted">
      {' '}
      (simulated time = cycles × declared network clock — model time derived
      from simulation, not host wall-clock measurement)
    </span>
  );
}

export function ProvenanceLine({
  children,
}: {
  children: ReactNode;
}): ReactElement {
  return <p className="muted sci-provenance">{children}</p>;
}

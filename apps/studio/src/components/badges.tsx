import type { ReactNode } from 'react';

export function shortHash(h: string | null | undefined, chars = 12): string {
  if (!h) return '—';
  return h.length > chars + 9 ? `${h.slice(0, 7)}…${h.slice(-4)}` : h;
}

export function TierBadge({ tier }: { tier: 'LOCKED' | 'GUIDED' | 'FREE' }): ReactNode {
  return <span className={`tier tier-${tier.toLowerCase()}`}>{tier}</span>;
}

const STATUS_CLASS: Record<string, string> = {
  PASS: 'ok',
  SATISFIED: 'ok',
  COMPILED: 'ok',
  EVALUATED: 'ok',
  FAIL: 'bad',
  VIOLATED: 'bad',
  FAILED: 'bad',
  INVALID: 'bad',
  BACKEND_UNAVAILABLE: 'warn',
  UNMEASURABLE: 'warn',
  UNSUPPORTED: 'muted',
  NOT_APPLICABLE: 'muted',
  NOT_RUN: 'muted',
  RUNNING: 'info',
};

export function StatusBadge({ status }: { status: string }): ReactNode {
  const cls = STATUS_CLASS[status] ?? 'muted';
  return <span className={`status status-${cls}`}>{status}</span>;
}

export function Hash({ value, label }: { value: string | null | undefined; label?: string }): ReactNode {
  if (!value) return <span className="hash-empty">—</span>;
  return (
    <code className="hash" title={value}>
      {label ? `${label}: ` : ''}
      {shortHash(value)}
    </code>
  );
}

export function Empty({ title, body }: { title: string; body: string }): ReactNode {
  return (
    <div className="empty">
      <div className="empty-title">{title}</div>
      <div className="empty-body">{body}</div>
    </div>
  );
}

export function humanize(key: string): string {
  return key.replace(/_/g, ' ');
}

export function fmtNum(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return v.toLocaleString('en-US', { maximumFractionDigits: 2 });
  return String(v);
}

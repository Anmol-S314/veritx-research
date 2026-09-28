import type { ReactElement } from 'react';
import type { CompileCertificate, PreflightView } from '../../api';
import { Link } from '../../studio';

interface Action {
  label: string;
  to: string;
  enabled: boolean;
  blocker?: string;
}

/** NEXT ACTIONS — only genuinely legal actions. A blocked action stays
 * visible with its exact blocker; nothing button-like is inert. */
export default function CompileActions({ projectId, certificate,
  preflight, hasPredecessor }: {
  projectId: string;
  certificate: CompileCertificate | null;
  preflight: PreflightView | null;
  hasPredecessor: boolean;
}): ReactElement {
  const certPass = certificate?.overall === 'PASS';
  const actions: Action[] = [
    { label: 'Edit design', to: `/projects/${projectId}/design`,
      enabled: true },
    { label: 'Review intent', to: `/projects/${projectId}/review`,
      enabled: true },
    { label: 'Evaluate', to: `/projects/${projectId}/simulate`,
      enabled: certPass && (preflight?.ready ?? false),
      blocker: !certPass
        ? 'certificate is not PASS'
        : (preflight && !preflight.ready
          ? (preflight.reason ?? 'preflight is blocked') : undefined),
    },
    { label: 'Optimize', to: `/projects/${projectId}/optimize`,
      enabled: certPass,
      blocker: certPass ? undefined : 'certificate is not PASS' },
    { label: 'Inspect verification', to: `/projects/${projectId}/verify`,
      enabled: certificate !== null,
      blocker: certificate === null ? 'no certificate exists' : undefined },
    { label: 'Inspect evidence', to: `/projects/${projectId}/evidence`,
      enabled: true },
    { label: 'Compare with previous revision',
      to: `/projects/${projectId}/compile`,
      enabled: hasPredecessor,
      blocker: hasPredecessor
        ? undefined : 'this is the first compiled revision' },
  ];
  return (
    <section className="card" aria-label="Next actions">
      <h4>Next actions</h4>
      <ul className="action-list">
        {actions.map((a) => (
          <li key={a.label}>
            {a.enabled ? (
              <Link className="btn btn-small" to={a.to}>{a.label} →</Link>
            ) : (
              <span>
                <span className="btn btn-small btn-disabled"
                      aria-disabled="true">{a.label}</span>{' '}
                <span className="muted">blocked — {a.blocker}</span>
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

import type { ReactElement } from 'react';
import type { CompileCertificate, PreflightView } from '../../api';
import { Link } from '../../studio';

interface Action {
  label: string;
  to: string;
  enabled: boolean;
  blocker?: string;
}

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
  const blocked = actions.filter((a) => !a.enabled);
  return (
    <section className="card" aria-label="Next actions">
      <h4>Next actions</h4>
      <ul className="action-row">
        {actions.filter((a) => a.enabled).map((a) => (
          <li key={a.label}>
            <Link className="btn btn-small" to={a.to}>{a.label} →</Link>
          </li>
        ))}
      </ul>
      {blocked.length > 0 && (
        <p className="muted action-blockers">
          Unavailable:{' '}
          {blocked.map((a) => `${a.label} — ${a.blocker}`).join(' · ')}
        </p>
      )}
    </section>
  );
}

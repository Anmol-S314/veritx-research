import { useState } from 'react';
import { gateway, gatewayReason } from './gateway';
import type { LoadedProject, LoadedRun } from './project';
import { deriveTrustChecks, trustSummary, type TrustResult } from './trustChecks';
import { Badge, Button, Section } from './ui';

const tone = (result: TrustResult): 'green' | 'red' | 'amber' | 'neutral' =>
  result === 'PASS' ? 'green' : result === 'FAIL' ? 'red' : result === 'REVIEW' ? 'amber' : 'neutral';

/** One place to inspect whether a recorded run is internally consistent.
 *  The checks are derived from the run and its draft; they never promote a
 *  model result into hardware qualification. */
export function TrustChecks({ project, run }: { project: LoadedProject; run: LoadedRun }) {
  const checks = deriveTrustChecks(project, run);
  const counts = trustSummary(checks);
  const [verification, setVerification] = useState<{ phase: 'idle' | 'busy' | 'verified' | 'error'; message?: string }>({ phase: 'idle' });

  const recheck = async () => {
    setVerification({ phase: 'busy' });
    try {
      const result = await gateway.verifyRun(run.detail.run_id);
      setVerification({ phase: 'verified', message: `${result.status} · ${result.files_checked}/${result.file_count} files · ${result.bundle_id.slice(0, 18)}…` });
    } catch (error) {
      setVerification({ phase: 'error', message: gatewayReason(error) });
    }
  };

  const verificationResult: TrustResult = verification.phase === 'verified' ? 'PASS' : verification.phase === 'error' ? 'FAIL' : 'UNKNOWN';
  const verificationEvidence = verification.phase === 'verified'
    ? verification.message ?? 'Bundle hashes verified'
    : verification.phase === 'error'
      ? verification.message ?? 'The gateway refused verification'
      : verification.phase === 'busy' ? 'Verifying bundle hashes…' : 'Not run in this view.';

  const notApplicable = checks.filter(check => check.result === 'UNKNOWN' && /^No (compute stages|requirement verdicts)/i.test(check.evidence));
  const shown = checks.filter(check => !notApplicable.includes(check));

  return <Section title="Trust checks" actions={<div className="actions">
    <Badge tone={counts.fail ? 'red' : counts.review ? 'amber' : 'green'}>{counts.pass} pass · {counts.fail} fail · {counts.review} review</Badge>
    {notApplicable.length > 0 && <Badge tone="neutral" title={notApplicable.map(check => check.label).join(' · ')}>{notApplicable.length} not applicable</Badge>}
    <Button disabled={verification.phase === 'busy'} onClick={() => void recheck()}>{verification.phase === 'busy' ? 'Verifying…' : 'Re-verify bundle'}</Button>
  </div>}>
    <div className="table-scroll"><table className="trust-table"><thead><tr><th>Check</th><th>Result</th><th>Evidence</th></tr></thead><tbody>
      <tr>
        <th>Bundle re-verification</th>
        <td><Badge tone={tone(verificationResult)}>{verificationResult}</Badge></td>
        <td><small>{verificationEvidence}</small></td>
      </tr>
      {shown.map(check => <tr key={check.id}>
        <th>{check.label}{check.detail && <small className="block trust-detail">{check.detail}</small>}</th>
        <td><Badge tone={tone(check.result)}>{check.result}</Badge></td>
        <td><small>{check.evidence}</small></td>
      </tr>)}
    </tbody></table></div>
  </Section>;
}

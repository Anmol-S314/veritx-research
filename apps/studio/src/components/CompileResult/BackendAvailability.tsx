import type { ReactElement } from 'react';
import { api, type EvaluationPlanView } from '../../api';
import { AsyncView, useAsync } from '../../studio';
import { backendLabel, questionLabel } from '../ScientificValue';

/** Execution availability per analysis family (§8).

 * Derived from the federated evaluation plan — one row per engineering
 * question with its adjudicated backend, support, readiness, fidelity
 * and qualification. The plan is the server's verdict; Studio never
 * recomputes it. A question the plan does not represent is shown as
 * unrepresented, never as a BookSim verdict. */
export default function BackendAvailability({ revisionId }: {
  revisionId: string;
}): ReactElement {
  const plan = useAsync(
    () => api.evaluationPlan(revisionId), [revisionId]);
  return (
    <AsyncView result={plan.result} reload={plan.reload}>
      {(view: EvaluationPlanView) => (
        <section className="card" aria-label="Execution availability">
          <h4>Execution availability</h4>
          {(view.analyses ?? []).length === 0 && (
            <p className="muted">
              The plan represents no analysis question for this revision.
            </p>
          )}
          <table className="tbl">
            <thead>
              <tr><th>analysis</th><th>backend</th><th>support</th>
                <th>readiness</th><th>qualification</th><th>why</th></tr>
            </thead>
            <tbody>
              {(view.analyses ?? []).map((a) => (
                <tr key={a.question}>
                  <td>{questionLabel(a.question)}{' '}
                    <code className="muted">{a.question}</code></td>
                  <td>{a.backend
                    ? backendLabel(a.backend) : '—'}
                    {a.backend && (
                      <code className="muted"> {a.backend}</code>
                    )}</td>
                  <td>{a.support}</td>
                  <td className={a.readiness === 'READY' ? 'ok' : 'muted'}>
                    {a.readiness}</td>
                  <td className="muted">
                    {a.qualification_profile ?? '—'}</td>
                  <td className="muted">{a.reason ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">
            Default policy is AUTO: the planner selects the qualified
            backend per question. Manual backend pinning is expert
            execution policy on the Evaluate page.
          </p>
        </section>
      )}
    </AsyncView>
  );
}

import { useEffect, useState } from 'react';
import { JobEvents } from './JobEvents';
import { gateway, gatewayReason } from './gateway';
import { useGatewayDocument, useGatewayJob } from './LiveOperations';
import { useProject, type LoadedProject } from './project';
import { Button, Field, Notice, Properties, Section, downloadJson } from './ui';

export function LiveAgents({ project }: { project: LoadedProject }) {
  const { reload } = useProject();
  const id = project.detail.project.project_id, hash = project.draftMeta?.design_hash;
  const runtime = useGatewayDocument('general-agent-capabilities', gateway.agentCapabilities);
  const capability = useGatewayDocument(`agent-capabilities:${id}`, gateway.aiCapabilities);
  const key = `srota-ai-search:${id}`;
  const [jobId, setJobId] = useState(() => { try { return sessionStorage.getItem(key) ?? ''; } catch { return ''; } });
  const status = useGatewayJob(jobId);
  const result = useGatewayDocument(`ai-search:${id}:${jobId}:${status.job?.state ?? ''}`, () => jobId ? gateway.aiSearchResult(id, jobId) : Promise.resolve({}));
  const [consent, setConsent] = useState(false), [candidate, setCandidate] = useState(''), [reviewed, setReviewed] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  useEffect(() => { setConsent(false); setReviewed(false); setCandidate(''); }, [hash]);
  const start = async () => {
    if (!hash || !consent || !capability.data?.configured || busy) return;
    setBusy(true); setError('');
    try { const job = await gateway.aiSearch(id, hash); setJobId(job.job_id); try { sessionStorage.setItem(key, job.job_id); } catch { /* Optional recovery. */ } }
    catch (e) { setError(gatewayReason(e)); } finally { setBusy(false); }
  };
  const adopt = async () => {
    if (!hash || !reviewed || !candidate || !jobId || busy) return;
    setBusy(true); setError('');
    try { await gateway.adoptAI(id, jobId, candidate.trim(), hash); setReviewed(false); setCandidate(''); reload(); }
    catch (e) { setError(gatewayReason(e)); } finally { setBusy(false); }
  };
  const active = status.job && !['COMPLETED', 'FAILED', 'REFUSED', 'CANCELLED'].includes(status.job.state);
  return <div className="view-main"><Section title="General agent connection"><Properties rows={[[ 'Transport', runtime.data?.transport ?? 'Checking' ], ['Configured', runtime.data ? runtime.data.configured ? 'Yes' : 'No' : 'Checking' ], ['Connection', runtime.error ?? runtime.data?.reason ?? 'Server-managed' ], ['Client tools', 'None; file and terminal requests denied' ]]} /></Section><Notice>Topology search is a separate bounded model workflow. General chat and workload translation are available in their views.</Notice>
    <Section title="Topology search connection"><Properties rows={[[ 'Model configured', capability.data ? capability.data.configured ? 'Yes' : 'No' : 'Checking' ], ['Model', capability.data?.model ?? 'Not configured' ], ['Configuration', capability.data?.reason ?? capability.error ?? 'Server-managed' ], ['Draft snapshot', hash ?? 'Missing; reload project' ], ['Proposal limit', capability.data?.limits?.max_proposals ?? 'Not reported' ], ['Timeout', capability.data?.job_timeout_s ? `${capability.data.job_timeout_s} seconds` : 'Not reported' ]]} />
      <label className="check-row"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />Allow this draft snapshot to be sent to the server-configured model for bounded topology proposals and backend evaluation.</label>
      <Button primary disabled={busy || !consent || !hash || !capability.data?.configured || (!!jobId && (!status.job || !!active))} onClick={start}>{busy ? 'Working…' : 'Request topology proposals'}</Button>
    </Section>
    {status.job && <Section title="Proposal job"><Properties rows={[[ 'Job', jobId ], ['State', status.job.state ], ['Error', status.job.error_message ?? 'None reported' ]]} />{active && <Button disabled={!status.job.cancellable} onClick={status.cancel}>Cancel proposal job</Button>}</Section>}
    {jobId && <JobEvents key={jobId} jobId={jobId} />}
    {jobId && result.data && <Section title="Review proposal and evidence"><Button onClick={() => downloadJson('topology-proposals.json', result.data)}>Download proposal record</Button><pre className="code-preview">{JSON.stringify(result.data, null, 2)}</pre><Field label="Reviewed candidate identifier"><input value={candidate} onChange={e => { setCandidate(e.target.value); setReviewed(false); }} /></Field>
      <label className="check-row"><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)} />I reviewed this candidate's changes and evidence. Apply it to the pinned draft.</label>
      <Button primary disabled={busy || !reviewed || !candidate.trim() || !hash || status.job?.state !== 'COMPLETED'} onClick={adopt}>Adopt reviewed proposal</Button>
    </Section>}
    {(error || status.error || result.error) && <Notice tone="red">{error || status.error || result.error}</Notice>}{status.error && <Button onClick={status.retry}>Retry proposal job status</Button>}
  </div>;
}

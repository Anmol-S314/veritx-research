import { useEffect, useState } from 'react';
import { JobEvents } from './JobEvents';
import { gateway, gatewayReason } from './gateway';
import { useGatewayDocument, useGatewayJob } from './LiveOperations';
import { useProject, type LoadedProject } from './project';
import { Assumptions, Button, Field, Notice, Properties, Section, downloadJson } from './ui';

export function LiveAgents({ project, embedded = false, topologyOnly = false, parametersOnly = false, showAssumptions = true }: {
  project: LoadedProject;
  /** The guided flow owns the page shell; embedding drops the extra scroll/pad wrapper. */
  embedded?: boolean;
  /** Hide the general agent connection and show only the topology proposal workflow. */
  topologyOnly?: boolean;
  parametersOnly?: boolean;
  /** The embedding page owns the single scope block. */
  showAssumptions?: boolean;
}) {
  const { reload } = useProject();
  const id = project.detail.project.project_id, revisionToken = project.draftMeta?.revisionToken;
  const runtime = useGatewayDocument('general-agent-capabilities', gateway.agentCapabilities);
  const [configVersion, setConfigVersion] = useState(0);
  const [showSettings, setShowSettings] = useState(false);
  const [baseUrl, setBaseUrl] = useState(''), [model, setModel] = useState(''), [apiKey, setApiKey] = useState('');
  const capability = useGatewayDocument(`agent-capabilities:${id}:${configVersion}`, gateway.aiCapabilities);
  const key = `${parametersOnly ? 'srota-ai-parameters' : 'srota-ai-search'}:${id}`;
  const [jobId, setJobId] = useState(() => { try { return sessionStorage.getItem(key) ?? ''; } catch { return ''; } });
  const status = useGatewayJob(jobId);
  const result = useGatewayDocument(`ai-search:${id}:${jobId}:${status.job?.state ?? ''}`, () => jobId ? gateway.aiSearchResult(id, jobId) : Promise.resolve({}));
  const [consent, setConsent] = useState(false), [candidate, setCandidate] = useState(''), [reviewed, setReviewed] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  useEffect(() => { setConsent(false); setReviewed(false); setCandidate(''); }, [revisionToken]);
  const start = async () => {
    if (!revisionToken || !consent || !capability.data?.configured || busy) return;
    setBusy(true); setError('');
    try { const job = await (parametersOnly ? gateway.aiParameterSearch(id, revisionToken) : gateway.aiSearch(id, revisionToken)); setJobId(job.job_id); try { sessionStorage.setItem(key, job.job_id); } catch { /* Optional recovery. */ } }
    catch (e) { setError(gatewayReason(e)); } finally { setBusy(false); }
  };
  const adopt = async () => {
    if (!revisionToken || !reviewed || !candidate || !jobId || busy) return;
    setBusy(true); setError('');
    try { await gateway.adoptAI(id, jobId, candidate.trim(), revisionToken); setReviewed(false); setCandidate(''); reload(); }
    catch (e) { setError(gatewayReason(e)); } finally { setBusy(false); }
  };
  const configure = async () => {
    if (!baseUrl.trim() || !model.trim() || busy) return;
    setBusy(true); setError('');
    try {
      await gateway.setAgentConfig({ baseUrl: baseUrl.trim(), model: model.trim(), ...(apiKey ? { apiKey } : {}) });
      setApiKey(''); setShowSettings(false); setConsent(false); setConfigVersion(value => value + 1);
    } catch (caught) { setError(gatewayReason(caught)); }
    finally { setBusy(false); }
  };
  const active = status.job && !['COMPLETED', 'FAILED', 'REFUSED', 'CANCELLED'].includes(status.job.state);
  const body = <>{!topologyOnly && <Section title="General agent connection"><Properties rows={[[ 'Transport', runtime.data?.transport ?? 'Checking' ], ['Configured', runtime.data ? runtime.data.configured ? 'Yes' : 'No' : 'Checking' ], ['Connection', runtime.error ?? runtime.data?.reason ?? 'Server-managed' ], ['Client tools', 'None; file and terminal requests denied' ]]} /></Section>}
    <Section title={parametersOnly ? 'AI-assisted parameter refinement' : 'Topology search connection'}>
      {capability.error && <Notice tone="red">Model capability could not be read: {capability.error}</Notice>}
      {!capability.error && capability.data && !capability.data.configured && capability.data.reason && <Notice tone="amber">{capability.data.reason}</Notice>}
      {capability.data?.configured && <div className="toolbar"><span>Model · {capability.data.model}</span><Button onClick={() => setShowSettings(open => !open)}>Model settings</Button></div>}
      {(!capability.data?.configured || showSettings) && <form onSubmit={event => { event.preventDefault(); void configure(); }}>
        <p>Connect an OpenAI-compatible model to propose and evaluate parameter changes. Manual editing does not require a model.</p>
        <div className="form-grid">
          <Field label="Model endpoint"><input type="url" aria-label="Model endpoint" value={baseUrl} placeholder="https://provider.example/v1" onChange={event => setBaseUrl(event.target.value)} /></Field>
          <Field label="Model name"><input aria-label="Model name" value={model} onChange={event => setModel(event.target.value)} /></Field>
          <Field label="API key (if required)"><input type="password" autoComplete="off" aria-label="API key (if required)" value={apiKey} onChange={event => setApiKey(event.target.value)} /></Field>
        </div>
        <Button type="submit" disabled={busy || !baseUrl.trim() || !model.trim()}>Save model connection</Button>
      </form>}
      <label className="check-row"><input type="checkbox" checked={consent} disabled={!capability.data?.configured} onChange={e => setConsent(e.target.checked)} />{parametersOnly ? "Send this selected fabric's draft to the configured model for parameter proposals and real backend evaluation." : 'Allow this draft snapshot to be sent to the server-configured model for bounded topology proposals and backend evaluation.'}</label>
      <Button primary disabled={busy || !consent || !revisionToken || !capability.data?.configured || (!!jobId && (!status.job || !!active))} onClick={start}>{busy ? 'Working…' : parametersOnly ? 'Propose & evaluate parameter changes' : 'Request topology proposals'}</Button>
    </Section>
    {status.job && <Section title="Proposal job"><Properties rows={[[ 'Job', jobId ], ['State', status.job.state ], ['Error', status.job.error_message ?? 'None reported' ]]} />{active && <Button disabled={!status.job.cancellable} onClick={status.cancel}>Cancel proposal job</Button>}</Section>}
    {jobId && <JobEvents key={jobId} jobId={jobId} />}
    {jobId && result.data && <Section title="Review proposal and evidence"><Button onClick={() => downloadJson('topology-proposals.json', result.data)}>Download proposal record</Button><details><summary>Proposal changes & measured evidence</summary><pre className="code-preview">{JSON.stringify(result.data, null, 2)}</pre></details>{parametersOnly ? <Field label="Evaluated parameter proposal"><select value={candidate} onChange={e => { setCandidate(e.target.value); setReviewed(false); }}><option value="">Choose a measured proposal…</option>{(result.data.attempts ?? []).map((row: any) => <option key={row.attempt} value={row.candidate_id ?? ''} disabled={!row.adoptable}>Proposal {row.attempt} · {row.status}{row.objective_values?.completion_cycles != null ? ` · ${row.objective_values.completion_cycles} network cycles` : ''}{row.reason ? ` · ${row.reason}` : ''}</option>)}</select></Field> : <Field label="Reviewed candidate identifier"><input value={candidate} onChange={e => { setCandidate(e.target.value); setReviewed(false); }} /></Field>}
      <label className="check-row"><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)} />I reviewed this candidate's changes and evidence. Apply it to the pinned draft.</label>
      <Button primary disabled={busy || !reviewed || !candidate.trim() || !revisionToken || status.job?.state !== 'COMPLETED'} onClick={adopt}>Adopt reviewed proposal</Button>
    </Section>}
    {(error || status.error || result.error) && <Notice tone="red">{error || status.error || result.error}</Notice>}{status.error && <Button onClick={status.retry}>Retry proposal job status</Button>}
    {showAssumptions && <Assumptions rows={[
      ['Authority', 'The server manages the model and transport. Client tools are denied; no file or terminal request is granted to the agent.'],
      ['Data sent', 'Only the pinned draft snapshot, and only after the explicit consent checkbox.'],
      ['Proposals', parametersOnly ? 'Only declared parameters of the selected fabric may change. Workload, agents, requirements and fabric family stay fixed. Each proposal is evaluated before explicit adoption.' : 'Bounded topology proposals, then a real backend evaluation. Nothing is applied until a reviewed candidate identifier is confirmed.'],
      ['Not established', 'Proposal quality, model identity beyond what the server reports, and any production or hardware qualification.'],
    ]} />}
  </>;
  return embedded ? <div className="flow-embedded">{body}</div> : <div className="view-main">{body}</div>;
}

import { useEffect, useState } from 'react';
import { gateway, gatewayReason } from './gateway';
import { useGatewayDocument } from './LiveOperations';
import { useProject, type LoadedProject } from './project';
import { Assumptions, Button, Field, Notice, Properties, Section, downloadJson } from './ui';

type Message = { role: 'user' | 'assistant'; content: string };
export function AgentConsole({ project, translation = false }: { project: LoadedProject; translation?: boolean }) {
  const { reload } = useProject();
  const id = project.detail.project.project_id, revisionToken = project.draftMeta?.revisionToken;
  const config = useGatewayDocument('general-agent-capabilities', gateway.agentCapabilities);
  const [message, setMessage] = useState(''), [messages, setMessages] = useState<Message[]>([]), [consent, setConsent] = useState(false), [include, setInclude] = useState(translation), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [proposal, setProposal] = useState<Record<string, any> | null>(null), [reviewed, setReviewed] = useState(false);
  useEffect(() => { setConsent(false); setReviewed(false); }, [revisionToken]);
  const send = async () => {
    if (!consent || !config.data?.configured || !message.trim() || busy || ((include || translation) && !revisionToken)) return;
    const text = message.trim(); setBusy(true); setError(''); setReviewed(false);
    try {
      if (translation) setProposal(await gateway.translateWorkload(id, { message: text, allowModel: true, revisionToken: revisionToken! }));
      else {
        const response = await gateway.agentChat(id, { message: text, history: messages.slice(-20), allowModel: true, includeDraft: include, revisionToken: include ? revisionToken : undefined });
        setMessages(rows => [...rows, { role: 'user', content: text }, { role: 'assistant', content: response.text }]);
      }
      setMessage(''); setConsent(false);
    } catch (e) { setError(gatewayReason(e)); } finally { setBusy(false); }
  };
  const adopt = async () => {
    if (!proposal || !reviewed || !revisionToken || proposal.baseRevisionToken !== revisionToken || busy) return;
    setBusy(true); setError('');
    try { await gateway.adoptWorkload(id, proposal.proposal_id, revisionToken); setProposal(null); setReviewed(false); reload(); }
    catch (e) { setError(gatewayReason(e)); } finally { setBusy(false); }
  };
  return <div className="view-main"><Section title={translation ? 'Requirements to editable workload' : 'Contextual engineering chat'}>
    <Properties rows={[[ 'Transport', config.data?.transport ?? 'Checking' ], ['Configured', config.data ? config.data.configured ? 'Yes' : 'No' : 'Checking' ], ['Model', config.data?.model ?? 'Runtime-managed' ], ['Connection', config.error ?? config.data?.reason ?? 'Ready on request' ], ['Domain tools', 'None; text/proposals only' ]]} />
    {messages.map((row, index) => <Section key={index} title={row.role === 'user' ? 'You' : 'Assistant'}><pre className="code-preview">{row.content}</pre></Section>)}
    <Field label={translation ? 'Workload requirements' : 'Message'}><textarea rows={4} maxLength={16000} value={message} disabled={busy} onChange={e => setMessage(e.target.value)} /></Field>
    <label className="check-row"><input type="checkbox" checked={include} disabled={translation || busy} onChange={e => { setInclude(e.target.checked); setConsent(false); }} />Attach saved draft snapshot</label>
    <label className="check-row"><input type="checkbox" checked={consent} disabled={busy} onChange={e => setConsent(e.target.checked)} />Allow this message and attached context to be sent to the configured runtime.</label>
    <div className="toolbar"><Button primary disabled={!config.data?.configured || !message.trim() || !consent || busy || ((include || translation) && !revisionToken)} onClick={send}>{busy ? 'Waiting for runtime…' : translation ? 'Generate workload proposal' : 'Send message'}</Button>{!translation && <Button disabled={busy || !messages.length} onClick={() => setMessages([])}>Clear chat</Button>}</div>
    {error && <Notice tone="red">{error}</Notice>}
  </Section>
    {proposal && <Section title="Review workload proposal"><Properties rows={[[ 'Proposal', proposal.proposal_id ], ['Validation', 'Schema only; not executed' ], ['Rationale', proposal.sections?.rationale ]]} />
      {proposal.baseRevisionToken !== revisionToken && <Notice tone="amber">Draft changed. Request a new proposal; adoption is blocked.</Notice>}
      <Section title="Assumptions"><ul>{(proposal.sections?.assumptions ?? []).map((value: string, index: number) => <li key={index}>{value}</li>)}</ul></Section>
      <div className="table-scroll"><table><thead><tr><th>Section</th><th>Current draft</th><th>Proposed</th></tr></thead><tbody>{['workload', 'compute'].filter(field => field in proposal.sections).map(field => <tr key={field}><th>{field}</th><td><pre className="code-preview">{JSON.stringify((project.request as any)?.[field], null, 2)}</pre></td><td><pre className="code-preview">{JSON.stringify(proposal.candidate_request?.[field], null, 2)}</pre></td></tr>)}</tbody></table></div>
      <Button onClick={() => downloadJson('workload-proposal.json', proposal)}>Download proposal</Button><label className="check-row"><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)} />Apply these reviewed workload/compute changes. Requirements and hardware remain unchanged.</label><Button primary disabled={!reviewed || busy || proposal.baseRevisionToken !== revisionToken} onClick={adopt}>Adopt reviewed workload</Button>
    </Section>}
    <Assumptions rows={[
      ['Source', 'Configured gateway agent runtime; transcript and proposals are held in this page session.'],
      ['Interpretation', translation ? 'Model interpretation only. Schema validation is not simulation; review assumptions and changes before adoption.' : 'Model responses are suggestions, not evidence. Chat is memory-only; the last 20 messages are sent with each request.'],
      ['Runtime', 'The owner-configured ACP process is not OS-sandboxed; filesystem, terminal, and permission requests are denied.'],
      ['Authority', 'No domain tools. Draft changes apply only through the reviewed adoption control, and the base revision must still match.'],
    ]} />
  </div>;
}

import { useEffect, useState } from 'react';
import { gateway, gatewayReason } from './gateway';
import { useGatewayDocument } from './LiveOperations';
import { useProject, type LoadedProject } from './project';
import { Button, Field, Notice, Properties, Section, downloadJson } from './ui';

type Message = { role: 'user' | 'assistant'; content: string };
export function AgentConsole({ project, translation = false }: { project: LoadedProject; translation?: boolean }) {
  const { reload } = useProject();
  const id = project.detail.project.project_id, hash = project.draftMeta?.design_hash;
  const config = useGatewayDocument('general-agent-capabilities', gateway.agentCapabilities);
  const [message, setMessage] = useState(''), [messages, setMessages] = useState<Message[]>([]), [consent, setConsent] = useState(false), [include, setInclude] = useState(translation), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [proposal, setProposal] = useState<Record<string, any> | null>(null), [reviewed, setReviewed] = useState(false);
  useEffect(() => { setConsent(false); setReviewed(false); }, [hash]);
  const send = async () => {
    if (!consent || !config.data?.configured || !message.trim() || busy || ((include || translation) && !hash)) return;
    const text = message.trim(); setBusy(true); setError(''); setReviewed(false);
    try {
      if (translation) setProposal(await gateway.translateWorkload(id, { message: text, allow_model: true, expected_draft_design_hash: hash }));
      else {
        const response = await gateway.agentChat(id, { message: text, history: messages.slice(-20), allow_model: true, include_draft: include, expected_draft_design_hash: include ? hash : undefined });
        setMessages(rows => [...rows, { role: 'user', content: text }, { role: 'assistant', content: response.text }]);
      }
      setMessage(''); setConsent(false);
    } catch (e) { setError(gatewayReason(e)); } finally { setBusy(false); }
  };
  const adopt = async () => {
    if (!proposal || !reviewed || !hash || proposal.base_design_hash !== hash || busy) return;
    setBusy(true); setError('');
    try { await gateway.adoptWorkload(id, proposal.proposal_id, hash); setProposal(null); setReviewed(false); reload(); }
    catch (e) { setError(gatewayReason(e)); } finally { setBusy(false); }
  };
  return <div className="view-main"><Section title={translation ? 'Requirements to editable workload' : 'Contextual engineering chat'}>
    <Properties rows={[[ 'Transport', config.data?.transport ?? 'Checking' ], ['Configured', config.data ? config.data.configured ? 'Yes' : 'No' : 'Checking' ], ['Model', config.data?.model ?? 'Runtime-managed' ], ['Connection', config.error ?? config.data?.reason ?? 'Ready on request' ], ['Domain tools', 'None; text/proposals only' ]]} />
    {config.data?.transport === 'acp' && <Notice tone="amber">The owner-configured ACP process is not OS-sandboxed. Client filesystem, terminal, and permission requests are denied.</Notice>}
    <Notice>{translation ? 'Model interpretation only. Review assumptions and changes before adoption; schema validation is not simulation.' : 'Model responses are suggestions, not evidence. Chat is memory-only; the last 20 messages are sent with each request.'}</Notice>
    {messages.map((row, index) => <Section key={index} title={row.role === 'user' ? 'You' : 'Assistant'}><pre className="code-preview">{row.content}</pre></Section>)}
    <Field label={translation ? 'Workload requirements' : 'Message'}><textarea rows={4} maxLength={16000} value={message} disabled={busy} onChange={e => setMessage(e.target.value)} /></Field>
    <label className="check-row"><input type="checkbox" checked={include} disabled={translation || busy} onChange={e => { setInclude(e.target.checked); setConsent(false); }} />Attach saved draft snapshot {include ? hash ?? '(unavailable)' : ''}</label>
    <label className="check-row"><input type="checkbox" checked={consent} disabled={busy} onChange={e => setConsent(e.target.checked)} />Allow this message and attached context to be sent to the configured runtime.</label>
    <div className="toolbar"><Button primary disabled={!config.data?.configured || !message.trim() || !consent || busy || ((include || translation) && !hash)} onClick={send}>{busy ? 'Waiting for runtime…' : translation ? 'Generate workload proposal' : 'Send message'}</Button>{!translation && <Button disabled={busy || !messages.length} onClick={() => setMessages([])}>Clear chat</Button>}</div>
    {error && <Notice tone="red">{error}</Notice>}
  </Section>
    {proposal && <Section title="Review workload proposal"><Properties rows={[[ 'Proposal', proposal.proposal_id ], ['Captured draft', proposal.base_design_hash ], ['Validation', 'Schema only; not executed' ], ['Rationale', proposal.sections?.rationale ]]} />
      {proposal.base_design_hash !== hash && <Notice tone="amber">Draft changed. Request a new proposal; adoption is blocked.</Notice>}
      <Section title="Assumptions"><ul>{(proposal.sections?.assumptions ?? []).map((value: string, index: number) => <li key={index}>{value}</li>)}</ul></Section>
      <div className="table-scroll"><table><thead><tr><th>Section</th><th>Current draft</th><th>Proposed</th></tr></thead><tbody>{['workload', 'compute'].filter(field => field in proposal.sections).map(field => <tr key={field}><th>{field}</th><td><pre className="code-preview">{JSON.stringify((project.request as any)?.[field], null, 2)}</pre></td><td><pre className="code-preview">{JSON.stringify(proposal.candidate_request?.[field], null, 2)}</pre></td></tr>)}</tbody></table></div>
      <Button onClick={() => downloadJson('workload-proposal.json', proposal)}>Download proposal</Button><label className="check-row"><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)} />Apply these reviewed workload/compute changes. Requirements and hardware remain unchanged.</label><Button primary disabled={!reviewed || busy || proposal.base_design_hash !== hash} onClick={adopt}>Adopt reviewed workload</Button>
    </Section>}
  </div>;
}

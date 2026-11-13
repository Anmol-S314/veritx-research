
import { useEffect, useState, type ReactNode } from 'react';
import type { LoadedProject } from './project';
import { useProject } from './project';
import { gateway, gatewayReason } from './gateway';
import { Badge, Button, Notice, PageLink, Properties, Section } from './ui';
import { agentsFromRequest, formatBytes, formatHexBig, memoizedRangesJson, memoizedSavedRangesJson, parseAddressBigInt, parseSizeBigInt, validateWindows, windowsFromRequest, windowsToRequest, type AddressWindow } from './agentMap';

function ModuleShell({ id, title, badge, children }: {
  id: string;
  title: string;
  badge: ReactNode;
  children: ReactNode;
}) {
  return <Section id={id} title={title} actions={badge}>
    {children}
  </Section>;
}

function NoDraft() {
  return <Notice tone="amber">No project draft is loaded, so this module has nothing to edit. The read-only tables above stay authoritative; load a project draft to unlock controls.</Notice>;
}


function HexInput({ value, onCommit, label }: { value: bigint; onCommit: (v: bigint) => void; label: string }) {
  const [text, setText] = useState(() => formatHexBig(value));
  useEffect(() => { setText(formatHexBig(value)); }, [value]);
  return <input aria-label={label} className="mono" value={text} onChange={event => setText(event.target.value)}
    onKeyDown={event => { if (event.key === 'Enter') (event.target as HTMLInputElement).blur(); }}
    onBlur={() => {
      const parsed = parseAddressBigInt(text);
      if (parsed === null) setText(formatHexBig(value));
      else onCommit(parsed);
    }} />;
}

function SizeInput({ value, onCommit, label, disabled = false }: { value: bigint; onCommit: (v: bigint) => void; label: string; disabled?: boolean }) {
  const [text, setText] = useState(() => value.toString(10));
  const [error, setError] = useState('');
  useEffect(() => { setText(value.toString(10)); setError(''); }, [value]);
  return <span>
    <input aria-label={label} title={formatBytes(value)} value={text} disabled={disabled}
      onChange={event => { setText(event.target.value); setError(''); }}
      onKeyDown={event => { if (event.key === 'Enter') (event.target as HTMLInputElement).blur(); }}
      onBlur={() => {
        if (disabled) return;
        const parsed = parseSizeBigInt(text);
        if (parsed === null || parsed <= 0n) { setText(value.toString(10)); setError('Size must be a positive byte count.'); }
        else { setError(''); onCommit(parsed); }
      }} />
    {error && <small className="error-text">{error}</small>}
  </span>;
}

export function M1AddressEditor({ data }: { data: LoadedProject }) {
  const { reload } = useProject();
  const agents = agentsFromRequest(data.request);
  const [windows, setWindows] = useState<AddressWindow[]>(() => windowsFromRequest(data.request, agents));
  const [busy, setBusy] = useState<'save' | 'compile' | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  useEffect(() => {
    setWindows(windowsFromRequest(data.request, agentsFromRequest(data.request)));
    setError('');
    setNotice('');
  }, [data.detail.project.project_id, data.draftMeta?.revisionToken, data.detail.active_revision_id]);

  const issues = validateWindows(windows, agents);
  const blocking = issues.filter(issue => issue.severity === 'error');
  const savedRanges = memoizedSavedRangesJson(data.request ?? {}, agents);
  const dirty = memoizedRangesJson(windows) !== savedRanges;
  const v5Nested = !!(data.request as unknown as Record<string, unknown>)?.base_v4 || Number((data.request as unknown as Record<string, unknown>)?.schema_version ?? 4) >= 5;

  const update = (id: string, patch: Partial<AddressWindow>) => {
    setWindows(current => current.map(w => w.id === id ? { ...w, ...patch } : w));
    setNotice('');
  };
  const discard = () => {
    if (dirty && !window.confirm('Discard unsaved address-window edits? They have not been saved to the gateway.')) return;
    setWindows(windowsFromRequest(data.request, agentsFromRequest(data.request)));
    setError('');
    setNotice('');
  };
  const save = async () => {
    if (!data.request || busy || blocking.length) return;
    let savedDraft = false;
    setBusy('save'); setError(''); setNotice('');
    try {
      const next: Record<string, unknown> = {
        ...(data.request as unknown as Record<string, unknown>),
        address_map: { ranges: windowsToRequest(windows) },
      };
      const revToken = data.draftMeta?.revisionToken;
      const saved = await gateway.putDraft(data.detail.project.project_id, next, revToken);
      if (!saved.revisionToken) throw new Error('The gateway returned no saved draft version. Reopen this project before compiling.');
      savedDraft = true;
      setBusy('compile');
      const compiled = await gateway.compileProject(data.detail.project.project_id, saved.revisionToken);
      setNotice(`Address windows saved and compiled into revision ${compiled.revision_id ?? '—'}. The verdict below reflects the active revision.`);
      reload();
    } catch (caught) {
      setError(`${savedDraft ? 'Draft saved; compilation did not finish. ' : ''}${gatewayReason(caught)}`);
      if (savedDraft) reload();
    } finally {
      setBusy(null);
    }
  };

  return <ModuleShell id="m1-address-windows" title="Address windows — live draft edit"
    badge={<>{<Badge tone={dirty ? 'amber' : 'green'}>{dirty ? 'Unsaved changes' : 'Matches draft'}</Badge>}<Badge tone="blue" title="Deep module M1 · Address and permission">M1 · Address &amp; permission</Badge></>}>
    <p className="meta-line">Deep module M1 · Address &amp; permission. Saves declared address ranges to the draft; compile to materialize decode and verdicts.</p>
    {!data.request && <NoDraft />}
    {data.request && v5Nested && <Notice tone="amber"><strong>Schema-v5 draft.</strong> This editor writes the v4 <code>address_map</code> layout; a v5 design nests under <code>base_v4</code> and is not authored here (the same guard as Agent Fabric Map). Read-only decode above stays authoritative. <PageLink page="workloads/workflow">Open the Project workflow draft editor</PageLink></Notice>}
    {data.request && !v5Nested && <fieldset disabled={busy !== null}>
      {windows.length === 0 ? <Properties rows={[['Windows', 'Not declared — Add window to declare a range']]} />
        : <div className="table-scroll"><table className="address-table"><thead><tr><th>Name</th><th>Base</th><th>Size</th><th>Target agent</th><th>Selection</th><th>Actions</th></tr></thead><tbody>
          {windows.map(window => <tr key={window.id}>
            <td><input aria-label={`M1 window name ${window.id}`} value={window.name} placeholder="DRAM" onChange={event => update(window.id, { name: event.target.value })} /></td>
            <td><HexInput value={window.base} onCommit={value => update(window.id, { base: value })} label={`M1 window base ${window.id}`} /></td>
            <td><SizeInput value={window.size} onCommit={value => update(window.id, { size: value })} label={`M1 window size ${window.id}`} /><br /><small>{formatBytes(window.size)}</small></td>
            <td><select aria-label={`M1 window target ${window.id}`} value={window.targetAgentIdx}
              onChange={event => {
                const targetAgentIdx = Number(event.target.value);
                const group = agents[targetAgentIdx];
                const needsSelection = !!group && group.count > 1;
                update(window.id, {
                  targetAgentIdx,
                  selectionPolicy: needsSelection ? (window.selectionPolicy ?? 'FIXED_INSTANCE') : null,
                  targetInstanceIndex: needsSelection ? (window.targetInstanceIndex ?? 0) : null,
                });
              }}>{agents.map((agent, index) => <option key={`${agent.kind}-${index}`} value={index}>{agent.kind} ({agent.count})</option>)}
            </select></td>
            <td className="muted">{window.selectionPolicy ?? 'group'}{window.selectionPolicy === 'FIXED_INSTANCE' ? ` · ${window.targetInstanceIndex ?? 0}` : window.selectionPolicy === 'STRIPED' ? ` · ${formatBytes(window.interleaveBytes ?? 0n)}` : ''}</td>
            <td><Button onClick={() => setWindows(current => current.filter(w => w.id !== window.id))}>Remove</Button></td>
          </tr>)}
        </tbody></table></div>}
      <div className="toolbar toolbar-start">
        <Button onClick={() => {
          const target = Math.min(Math.max(0, windows.length ? windows[windows.length - 1].targetAgentIdx : 0), Math.max(0, agents.length - 1));
          const group = agents[target];
          setWindows(current => [...current, {
            id: `m1-${Date.now()}-${current.length}`,
            name: '',
            base: 0n,
            size: 0n,
            targetAgentIdx: target,
            selectionPolicy: group && group.count > 1 ? 'FIXED_INSTANCE' as const : null,
            targetInstanceIndex: group && group.count > 1 ? 0 : null,
            interleaveBytes: null,
          }]);
        }} disabled={!agents.length}>Add window</Button>
        {dirty && <>
          <Button primary disabled={busy !== null || blocking.length > 0} onClick={save}>{busy === 'save' ? 'Saving…' : busy === 'compile' ? 'Compiling…' : 'Save & compile'}</Button>
          <Button onClick={discard} disabled={busy !== null}>Discard edits</Button>
        </>}
      </div>
    </fieldset>}
    {error && <Notice tone="red">{error}</Notice>}
    {notice && <Notice tone="blue">{notice}</Notice>}
    {blocking.length > 0 && <div className="table-scroll"><table><thead><tr><th>Window</th><th>Code</th><th>Detail</th></tr></thead><tbody>
      {blocking.map((issue, index) => <tr key={`${issue.code}-${index}`}><th>{issue.window}</th><td className="mono">{issue.code}</td><td>{issue.detail}</td></tr>)}
    </tbody></table></div>}
  </ModuleShell>;
}

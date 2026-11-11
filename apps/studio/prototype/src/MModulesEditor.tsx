
import { useEffect, useState, type ReactNode } from 'react';
import type { LoadedProject } from './project';
import { useProject } from './project';
import { gateway, gatewayReason, type CompileResult } from './gateway';
import { Badge, Button, Notice, PageLink, Properties, Section } from './ui';
import { decodeGroup } from './fabricAnalysis';
import { INITIATOR_KINDS, agentsFromRequest, designDocument, formatBytes, formatHexBig, memoizedRangesJson, memoizedSavedRangesJson, parseAddressBigInt, parseSizeBigInt, validateWindows, windowsFromRequest, windowsToRequest, type AddressWindow } from './agentMap';
import { shortText } from './format';

type RecordShape = Record<string, any>;


const record = (value: unknown): RecordShape =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as RecordShape : {};

function stage1VerdictsOf(result: CompileResult | null): RecordShape[] | null {
  const raw = (result as unknown as Record<string, unknown> | null)?.stage1_verdicts;
  if (!Array.isArray(raw)) return null;
  return raw.map(row => record(row));
}

function stage1VerdictFor(result: CompileResult | null, module: string): RecordShape | null {
  const list = stage1VerdictsOf(result);
  if (!list) return null;
  return list.find(verdict => verdict.module === module) ?? null;
}

function stage1FindingsOf(result: CompileResult | null): string[] | null {
  const raw = (result as unknown as Record<string, unknown> | null)?.stage1_findings;
  if (!Array.isArray(raw)) return null;
  return raw.map(value => String(value));
}

function verdictReasonOf(verdict: RecordShape | null): string | null {
  const reason = verdict?.reason;
  return typeof reason === 'string' && reason ? reason : null;
}

function verdictFindingsOf(verdict: RecordShape | null): string[] {
  if (!verdict) return [];
  const raw = verdict.findings;
  if (!Array.isArray(raw)) return [];
  return raw.map(value => String(value));
}

function rtlSupportOf(result: CompileResult | null): RecordShape | null {
  const raw = (result as unknown as Record<string, unknown> | null) ?? null;
  const support = (raw?.rtl_support ?? raw?.preview_support ?? null) as Record<string, unknown> | null;
  return support && typeof support === 'object' ? record(support) : null;
}
function rtlSupportReasonOf(result: CompileResult | null): string | null {
  const reason = rtlSupportOf(result)?.reason;
  return typeof reason === 'string' && reason ? reason : null;
}
function rtlSupportCodeOf(result: CompileResult | null): string | null {
  const code = rtlSupportOf(result)?.code;
  return typeof code === 'string' && code ? code : null;
}
function stage1VerdictRows(verdict: RecordShape | null, module: string): [string, ReactNode][] {
  if (!verdict) {
    return [
      ['Verdict source', 'Not recorded — no stage1_verdicts entry for this module'],
      ['Verdict ok', 'Not recorded — verdict absent'],
      ['Owner stage', 'Not recorded — verdict absent'],
      ['Server reason (verbatim)', 'Not recorded — verdict absent'],
      ['Verdict findings', 'Not recorded — verdict absent'],
    ];
  }
  const reason = verdictReasonOf(verdict);
  const findings = verdictFindingsOf(verdict);
  return [
    ['Verdict source', `compile-result.stage1_verdicts · ${String(verdict.module ?? module)}`],
    ['Verdict ok', verdict.ok === true ? 'ok' : verdict.ok === false ? 'not ok' : 'Not recorded — ok flag absent'],
    ['Owner stage', typeof verdict.stopped_at_stage === 'string' && verdict.stopped_at_stage ? verdict.stopped_at_stage : 'Not recorded — owner stage absent'],
    ['Server reason (verbatim)', reason ?? 'Not recorded — no refusal reason served for this verdict'],
    ['Verdict findings', findings.length ? findings.join(' · ') : 'Not recorded — no findings in this verdict'],
  ];
}

function stage1GlobalFindingsRows(result: CompileResult | null): [string, ReactNode][] {
  const global = stage1FindingsOf(result);
  if (!global) return [];
  return [['Stage-1 findings (global)', global.length ? global.join(' · ') : 'Not recorded — no global findings in this compile-result']];
}

function provenanceOf(result: CompileResult | null): RecordShape {
  return record((record(result?.groups).provenance as RecordShape) ?? {});
}

function artifactHashesOf(result: CompileResult | null): [string, string][] {
  const hashes = provenanceOf(result).artifact_hashes;
  if (!hashes || typeof hashes !== 'object') return [];
  return (Object.entries(hashes) as [string, unknown][]).map(([name, hash]) => [name, String(hash)]);
}

function declaredIntents(data: LoadedProject): RecordShape[] {
  const rows = designDocument(data.request).agent_intents;
  return Array.isArray(rows) ? rows.map(row => record(row)) : [];
}

function intentOf(rows: RecordShape[], agentIdx: number): RecordShape | null {
  return rows.find(row => typeof row.agent_idx === 'number' && row.agent_idx === agentIdx) ?? null;
}

function verdictSummary(data: LoadedProject): string | null {
  const overall = data.compileResult?.certificate?.overall;
  const decode = decodeGroup(data.compileResult);
  const prov = provenanceOf(data.compileResult);
  const parts: string[] = [];
  if (data.detail.active_revision_id) parts.push(`revision ${data.detail.active_revision_id}`);
  if (data.detail.active_revision?.compilation_status) parts.push(`compilation ${data.detail.active_revision.compilation_status}`);
  if (overall) parts.push(`certificate ${overall}`);
  if (decode?.available !== undefined && decode?.available !== null) {
    parts.push(decode.available ? `${decode.rows?.length ?? 0} decode row(s)` : 'no decode artifact');
  }
  if (typeof prov.design_hash === 'string' && prov.design_hash) parts.push(`design ${shortText(prov.design_hash, 12)}`);
  return parts.length ? parts.join(' · ') : null;
}

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
  const decode = decodeGroup(data.compileResult);
  const prov = provenanceOf(data.compileResult);
  const hashes = artifactHashesOf(data.compileResult);
  const summary = verdictSummary(data);

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

  return <ModuleShell id="m1-address-windows" title="M1 · Address windows — edit (live draft)"
    badge={<>{<Badge tone={dirty ? 'amber' : 'green'}>{dirty ? 'Unsaved changes' : 'Matches draft'}</Badge>}<Badge tone="blue">M1</Badge></>}>
    {!data.request && <NoDraft />}
    {data.request && v5Nested && <Notice tone="amber"><strong>Schema-v5 draft.</strong> This editor writes the v4 <code>address_map</code> layout; a v5 design nests under <code>base_v4</code> and is not authored here (the same guard as Agent Fabric Map). Read-only decode above stays authoritative.</Notice>}
    {data.request && !v5Nested && <fieldset disabled={busy !== null}>
      <Properties rows={[
        ['Save writes', 'address_map.ranges then compile'],
        ['Untouched', 'agent_intents, traffic_policy'],
      ]} />
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
        <Button primary disabled={busy !== null || !dirty || blocking.length > 0} onClick={save}>{busy === 'save' ? 'Saving…' : busy === 'compile' ? 'Compiling…' : 'Save & compile'}</Button>
        <Button onClick={discard} disabled={busy !== null || !dirty}>Discard edits</Button>
      </div>
    </fieldset>}
    {error && <Notice tone="red">{error}</Notice>}
    {notice && <Notice tone="blue">{notice}</Notice>}
    {blocking.length > 0 && <div className="table-scroll"><table><thead><tr><th>Window</th><th>Code</th><th>Detail</th></tr></thead><tbody>
      {blocking.map((issue, index) => <tr key={`${issue.code}-${index}`}><th>{issue.window}</th><td className="mono">{issue.code}</td><td>{issue.detail}</td></tr>)}
    </tbody></table></div>}
    <Section title="Compiled verdict (active revision)" actions={<Badge tone={decode?.available ? 'blue' : 'neutral'}>{decode?.available ? `${decode.rows?.length ?? 0} row(s)` : 'not compiled'}</Badge>}>
      {summary ? <Properties rows={[
        ['Verdict', summary],
        ['Decode', decode?.available ? `transform ${decode.address_transform ?? '—'} · unmatched ${decode.unmatched_address_policy ?? '—'}` : 'No address_decode group in this compile result.'],
        ['Design hash', typeof prov.design_hash === 'string' && prov.design_hash ? <code className="mono">{shortText(prov.design_hash, 24)}</code> : '—'],
        ['Artifact hashes', hashes.length ? hashes.slice(0, 6).map(([name, hash]) => <span key={name} className="mono">{name}…{shortText(hash, 10)}</span>).join(' ') : 'Bundle produced no hashes (no bundle — see verdict above).'],
      ]} /> : <Properties rows={[['Compiled verdict', 'Not recorded — Save above to compile']]} />}
      <PageLink page="design/agent-map">Full editor (Agent Fabric Map)</PageLink>
    </Section>
  </ModuleShell>;
}


export function M1PermissionBlocked({ data }: { data: LoadedProject }) {
  const { reload } = useProject();
  const agents = agentsFromRequest(data.request);
  const windows = windowsFromRequest(data.request, agents);
  const rows = agents.map((agent, index) => ({ agent, index })).filter(({ agent }) => INITIATOR_KINDS.has(agent.kind));
  const intents = declaredIntents(data);
  const verdict = stage1VerdictFor(data.compileResult, 'address_permission');
  const hasVerdict = verdict !== null;
  const windowFor = (agentIdx: number, rangeName: string): RecordShape | null => {
    const intent = intentOf(intents, agentIdx);
    const list = Array.isArray(intent?.permission_windows) ? intent.permission_windows as RecordShape[] : [];
    return list.find(w => record(w).address_range === rangeName) ?? null;
  };
  type PermissionCell = { readable: boolean | undefined; writable: boolean | undefined };
  const cellKey = (agentIdx: number, rangeName: string) => `${agentIdx}:${rangeName}`;
  function declaredCell(agentIdx: number, rangeName: string): PermissionCell {
    const declared = windowFor(agentIdx, rangeName);
    if (!declared) return { readable: undefined, writable: undefined };
    return {
      readable: declared.readable === false ? false : true,
      writable: declared.writable === false ? false : true,
    };
  }
  const [edits, setEdits] = useState<Record<string, PermissionCell>>({});
  const [busy, setBusy] = useState<'save' | 'compile' | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  useEffect(() => {
    setEdits({});
    setError('');
    setNotice('');
  }, [data.detail.project.project_id, data.draftMeta?.revisionToken, data.detail.active_revision_id]);
  const v5Nested = !!(data.request as unknown as Record<string, unknown>)?.base_v4 || Number((data.request as unknown as Record<string, unknown>)?.schema_version ?? 4) >= 5;
  const effectiveCell = (agentIdx: number, rangeName: string): PermissionCell =>
    edits[cellKey(agentIdx, rangeName)] ?? declaredCell(agentIdx, rangeName);
  const dirty = rows.some(({ index }) =>
    windows.some(window => {
      const name = (window.name ?? '').trim();
      if (!name) return false;
      const effective = effectiveCell(index, name);
      const declared = declaredCell(index, name);
      return effective.readable !== declared.readable || effective.writable !== declared.writable;
    }));
  const enumerableWindows = windows.filter(window => (window.name ?? '').trim() !== '');
  let allowRead = 0; let denyRead = 0; let allowWrite = 0; let denyWrite = 0;
  for (const { index } of rows) {
    for (const window of enumerableWindows) {
      const cell = declaredCell(index, window.name.trim());
      if (cell.readable === true) allowRead += 1;
      else if (cell.readable === false) denyRead += 1;
      if (cell.writable === true) allowWrite += 1;
      else if (cell.writable === false) denyWrite += 1;
    }
  }
  const updateCell = (agentIdx: number, rangeName: string, field: 'readable' | 'writable', value: boolean | undefined) => {
    const key = cellKey(agentIdx, rangeName);
    setEdits(current => {
      const base = current[key] ?? declaredCell(agentIdx, rangeName);
      return { ...current, [key]: { ...base, [field]: value } };
    });
    setNotice('');
  };
  const discard = () => {
    if (dirty && !window.confirm('Discard unsaved permission edits? They have not been saved to the gateway.')) return;
    setEdits({});
    setError('');
    setNotice('');
  };
  const save = async () => {
    if (!data.request || busy || !dirty || v5Nested) return;
    let savedDraft = false;
    setBusy('save'); setError(''); setNotice('');
    try {
      const document = designDocument(data.request);
      const rawIntents = Array.isArray(document.agent_intents) ? (document.agent_intents as RecordShape[]) : [];
      const byIdx = new Map<number, RecordShape>();
      for (const row of rawIntents) {
        if (typeof row?.agent_idx === 'number') byIdx.set(row.agent_idx, row);
      }
      const rowIdxSet = new Set(rows.map(entry => entry.index));
      const nextIntents: RecordShape[] = [];
      for (const row of rawIntents) {
        const idx = row?.agent_idx;
        if (typeof idx === 'number' && rowIdxSet.has(idx)) continue;
        nextIntents.push(row);
      }
      for (const { index: agentIdx } of rows) {
        const previous = byIdx.get(agentIdx) ?? { agent_idx: agentIdx };
        const permissions: RecordShape[] = [];
        for (const window of enumerableWindows) {
          const name = window.name.trim();
          const cell = effectiveCell(agentIdx, name);
          if (cell.readable === undefined || cell.writable === undefined) continue;
          permissions.push({ address_range: name, readable: cell.readable, writable: cell.writable });
        }
        const nextRow: RecordShape = { ...previous, agent_idx: agentIdx };
        if (permissions.length) nextRow.permission_windows = permissions;
        else delete nextRow.permission_windows;
        const hasOtherKeys = Object.keys(nextRow).some(key => key !== 'agent_idx' && key !== 'permission_windows');
        if (permissions.length || hasOtherKeys) nextIntents.push(nextRow);
      }
      nextIntents.sort((a, b) => Number(a.agent_idx ?? 0) - Number(b.agent_idx ?? 0));
      const next: Record<string, unknown> = {
        ...(data.request as unknown as Record<string, unknown>),
        agent_intents: nextIntents,
      };
      const revToken = data.draftMeta?.revisionToken;
      const saved = await gateway.putDraft(data.detail.project.project_id, next, revToken);
      if (!saved.revisionToken) throw new Error('The gateway returned no saved draft version. Reopen this project before compiling.');
      savedDraft = true;
      setBusy('compile');
      const compiled = await gateway.compileProject(data.detail.project.project_id, saved.revisionToken);
      setNotice(`Permission matrix saved and compiled into revision ${compiled.revision_id ?? '—'}. The refreshed M1 verdict below reflects the active revision.`);
      reload();
    } catch (caught) {
      setError(`${savedDraft ? 'Draft saved; compilation did not finish. ' : ''}${gatewayReason(caught)}`);
      if (savedDraft) reload();
    } finally {
      setBusy(null);
    }
  };
  const editable = hasVerdict && !!data.request && !v5Nested;
  return <ModuleShell id="m1-permission" title="M1 · Permission (allow / deny)"
    badge={<><Badge>M1</Badge><Badge tone={dirty ? 'amber' : 'green'}>{dirty ? 'Unsaved changes' : 'Matches draft'}</Badge></>}>
    {!data.request && <NoDraft />}
    <Properties rows={[
      ...stage1VerdictRows(verdict, 'address_permission'),
      ['Allow / deny (declared draft)', rows.length && enumerableWindows.length ? `${allowRead} allow · ${denyRead} deny read · ${allowWrite} allow · ${denyWrite} deny write · ${rows.length} initiator(s) × ${enumerableWindows.length} range(s)` : 'Not recorded'],
      ...stage1GlobalFindingsRows(data.compileResult),
    ]} />
    {data.request && !hasVerdict && <Notice tone="amber"><strong>BLOCKED · no M1 verdict.</strong> This revision carries no <code>stage1_verdicts.address_permission</code>. Compile a fresh revision with the current gateway to expose the verdict and unlock editing.</Notice>}
    {data.request && hasVerdict && v5Nested && <Notice tone="amber"><strong>Schema-v5 draft.</strong> This editor writes the v4 <code>agent_intents</code> layout; a v5 design nests under <code>base_v4</code> and is not authored here. The read-only verdict table above stays authoritative.</Notice>}
    {data.request && (
      <fieldset disabled={!editable || busy !== null}>
        <Properties rows={[
          ['Save writes', 'agent_intents[].permission_windows'],
          ['One authority', 'Duplicate address_range across intents refused'],
        ]} />
        {rows.length === 0 || enumerableWindows.length === 0
          ? <Properties rows={[['Matrix', `Not recorded — ${agents.length} agent group(s), ${windows.length} window(s)`]]} />
          : <div className="table-scroll"><table className="mapping-table"><thead><tr><th scope="col">Initiator / range</th>{enumerableWindows.map(w => <th key={w.id} scope="col" className="mono">{w.name || 'unnamed'}</th>)}</tr></thead><tbody>
            {rows.map(({ agent, index }) => <tr key={index}><th scope="row" className="mono">{agent.kind}[{index}]</th>
              {enumerableWindows.map(w => {
                const name = w.name.trim();
                const cell = editable ? effectiveCell(index, name) : declaredCell(index, name);
                const r = cell.readable === undefined ? '' : cell.readable ? 'allow' : 'deny';
                const ww = cell.writable === undefined ? '' : cell.writable ? 'allow' : 'deny';
                return <td key={w.id}>
                  <label className="field"><span>R</span><select disabled={!editable || busy !== null} aria-label={`${agent.kind} read ${w.name}`} value={r} onChange={event => updateCell(index, name, 'readable', event.target.value === '' ? undefined : event.target.value === 'allow')}>
                    <option value="">Not recorded</option><option value="allow">allow</option><option value="deny">deny</option>
                  </select></label>
                  <label className="field"><span>W</span><select disabled={!editable || busy !== null} aria-label={`${agent.kind} write ${w.name}`} value={ww} onChange={event => updateCell(index, name, 'writable', event.target.value === '' ? undefined : event.target.value === 'allow')}>
                    <option value="">Not recorded</option><option value="allow">allow</option><option value="deny">deny</option>
                  </select></label>
                </td>;
              })}
            </tr>)}
          </tbody></table></div>}
        {editable && <div className="toolbar toolbar-start">
          <Button primary disabled={busy !== null || !dirty} onClick={save}>{busy === 'save' ? 'Saving…' : busy === 'compile' ? 'Compiling…' : 'Save & compile'}</Button>
          <Button onClick={discard} disabled={busy !== null || !dirty}>Discard edits</Button>
        </div>}
      </fieldset>
    )}
    {error && <Notice tone="red">{error}</Notice>}
    {notice && <Notice tone="blue">{notice}</Notice>}
  </ModuleShell>;
}

export const M1PermissionEditor = M1PermissionBlocked;


export function M2VcModule({ data }: { data: LoadedProject }) {
  const resources = data.compileResult?.groups?.resources;
  const classPairs = resources?.traffic_class_to_vcs ?? [];
  const vcIds = resources?.vc_ids ?? [];
  const escape = resources?.escape_vcs ?? [];
  const derivedVc = resources?.vc_count;
  const depth = resources?.arbitration?.input_buffer_depth_flits_per_vc;
  const agents = agentsFromRequest(data.request);
  const intents = declaredIntents(data);
  const deadlock = resources?.deadlock;
  const verdict = stage1VerdictFor(data.compileResult, 'ordering_vc');
  const rtlSupportReason = rtlSupportReasonOf(data.compileResult);
  const rtlSupportCode = rtlSupportCodeOf(data.compileResult);
  return <ModuleShell id="m2-vc" title="M2 · Ordering & VC (verdict)"
    badge={<><Badge tone={resources ? 'blue' : 'amber'}>{resources ? 'compile-result' : 'not exposed'}</Badge><Badge>M2</Badge></>}>
    {!data.request && <NoDraft />}
    {data.request && <fieldset disabled>
      <Properties rows={[
        ['Derived VCs', derivedVc !== undefined && derivedVc !== null ? `${derivedVc} per port · ids ${vcIds.length ? vcIds.join(', ') : '—'}` : 'Not derived'],
        ['Escape VCs', escape.length ? escape.join(', ') : 'none'],
        ['Buffer depth (flits / VC)', depth !== undefined && depth !== null ? String(depth) : 'Not declared'],
        ['Deadlock', deadlock ? `${deadlock.status ?? 'unknown'}${deadlock.method ? ` · ${deadlock.method}` : ''}` : 'Not exposed'],
        ...stage1VerdictRows(verdict, 'ordering_vc'),
        ...(rtlSupportReason ? [['RTL support (verbatim)', rtlSupportReason] as [string, ReactNode]] : []),
        ...(rtlSupportCode ? [['RTL support code', rtlSupportCode] as [string, ReactNode]] : []),
        ...stage1GlobalFindingsRows(data.compileResult),
      ]} />
      {classPairs.length ? <div className="table-scroll"><table><thead><tr><th>Traffic class</th><th>VC(s) — derived</th><th>VC → routing class</th></tr></thead><tbody>
        {classPairs.map(([cls, vcs]) => <tr key={cls}><th className="mono">{cls}</th><td className="mono">{vcs.join(', ')}</td>
          <td className="mono">{(resources?.vc_to_routing_class ?? []).filter(([vc]) => vcs.includes(vc)).map(([vc, rc]) => `VC ${vc}→${rc}`).join(' · ') || '—'}</td></tr>)}
      </tbody></table></div>
        : <Properties rows={[['Class → VC binding', 'Not recorded — no derived binding in resources']]} />}
      <div className="table-scroll"><table><thead><tr><th>Agent group</th><th>Ordering (disabled)</th><th>Max outstanding (disabled)</th></tr></thead><tbody>
        {agents.map((agent, index) => {
          const intent = intentOf(intents, index);
          return <tr key={`${agent.kind}-${index}`}><th className="mono">{agent.kind}[{index}]</th>
            <td><select disabled aria-label={`${agent.kind} ordering`} value={String(intent?.ordering ?? '')}>
              <option value="">Not recorded</option><option value="strong">strong</option><option value="relaxed">relaxed</option><option value="raw">raw</option>
            </select></td>
            <td><input disabled aria-label={`${agent.kind} max outstanding`} type="number" min={1} value={typeof intent?.max_outstanding === 'number' ? intent.max_outstanding : ''} placeholder="Not recorded" /></td></tr>;
        })}
        {agents.length === 0 && <tr><td colSpan={3} className="muted">The draft declares no agent groups.</td></tr>}
      </tbody></table></div>
    </fieldset>}
  </ModuleShell>;
}


export function M3DomainBlocked({ data }: { data: LoadedProject }) {
  const agents = agentsFromRequest(data.request);
  const intents = declaredIntents(data);
  const spanning = new Set(agents.map(a => a.clock_domain ?? '').filter(Boolean)).size;
  const domains = [...new Set(agents.flatMap(a => [a.clock_domain, a.power_domain]).filter((d): d is string => !!d))].sort();
  const verdict = stage1VerdictFor(data.compileResult, 'clock_power_cdc');
  const rtlSupportReason = rtlSupportReasonOf(data.compileResult);
  const rtlSupportCode = rtlSupportCodeOf(data.compileResult);
  return <ModuleShell id="m3-domains" title="M3 · Clock, power & CDC (blocked)"
    badge={<><Badge>M3</Badge></>}>
    {!data.request && <NoDraft />}
    <Properties rows={[
      ...stage1VerdictRows(verdict, 'clock_power_cdc'),
      ...(rtlSupportReason ? [['RTL support (verbatim)', rtlSupportReason] as [string, ReactNode]] : []),
      ...(rtlSupportCode ? [['RTL support code', rtlSupportCode] as [string, ReactNode]] : []),
      ...stage1GlobalFindingsRows(data.compileResult),
    ]} />
    {data.request && <fieldset disabled>
      {spanning > 1 && <Notice tone="red">This draft spans {spanning} clock domain(s) ({domains.join(', ')}). This is the UNSUPPORTED gate above, not a per-row edit: unify the domains before compile, or keep this panel as the explicit refusal.</Notice>}
      <div className="table-scroll"><table><thead><tr><th>Agent group</th><th>Clock domain (disabled)</th><th>Power domain (disabled)</th><th>Intent domain (declared)</th></tr></thead><tbody>
        {agents.map((agent, index) => {
          const intent = intentOf(intents, index);
          return <tr key={`${agent.kind}-${index}`}><th className="mono">{agent.kind}[{index}]</th>
            <td><select disabled aria-label={`${agent.kind} clock domain`} value={agent.clock_domain ?? ''}>
              <option value="">Not recorded</option>{domains.map(d => <option key={d} value={d}>{d}</option>)}
              {agent.clock_domain && !domains.includes(agent.clock_domain) && <option value={agent.clock_domain}>{agent.clock_domain}</option>}
            </select></td>
            <td><select disabled aria-label={`${agent.kind} power domain`} value={agent.power_domain ?? ''}>
              <option value="">Not recorded</option>{domains.map(d => <option key={d} value={d}>{d}</option>)}
              {agent.power_domain && !domains.includes(agent.power_domain) && <option value={agent.power_domain}>{agent.power_domain}</option>}
            </select></td>
            <td className="mono">{typeof intent?.clock_domain === 'string' ? intent.clock_domain : '—'}{typeof intent?.power_domain === 'string' ? ` / ${intent.power_domain}` : ''}</td></tr>;
        })}
        {agents.length === 0 && <tr><td colSpan={4} className="muted">The draft declares no agent groups.</td></tr>}
      </tbody></table></div>
    </fieldset>}
  </ModuleShell>;
}


export const PROTOCOLS = ['axi5', 'chi', 'tilelink', 'custom'];

export function M4ProtocolBlocked({ data }: { data: LoadedProject }) {
  const agents = agentsFromRequest(data.request);
  const intents = declaredIntents(data);
  const byKind = new Map<number, RecordShape>(intents.map(row => [row.agent_idx, row]));
  const verdict = stage1VerdictFor(data.compileResult, 'protocol_adapter');
  const rtlSupportReason = rtlSupportReasonOf(data.compileResult);
  const rtlSupportCode = rtlSupportCodeOf(data.compileResult);
  return <ModuleShell id="m4-protocol" title="M4 · Protocol adapter (blocked)"
    badge={<><Badge>M4</Badge></>}>
    {!data.request && <NoDraft />}
    <Properties rows={[
      ...stage1VerdictRows(verdict, 'protocol_adapter'),
      ...(rtlSupportReason ? [['RTL support (verbatim)', rtlSupportReason] as [string, ReactNode]] : []),
      ...(rtlSupportCode ? [['RTL support code', rtlSupportCode] as [string, ReactNode]] : []),
      ...stage1GlobalFindingsRows(data.compileResult),
    ]} />
    {data.request && <fieldset disabled>
      <Properties rows={[
        ['Vocabulary', PROTOCOLS.join(' / ')],
        ['Coexistence', 'Enum wins over legacy literal'],
      ]} />
      <div className="table-scroll"><table><thead><tr><th>Agent group</th><th>Declared protocol (legacy)</th><th>Protocol family (disabled)</th><th>Adapter module</th></tr></thead><tbody>
        {agents.map((agent, index) => {
          const intent = byKind.get(index);
          return <tr key={`${agent.kind}-${index}`}><th className="mono">{agent.kind}[{index}]</th>
            <td className="mono">{agent.protocol ?? 'Not recorded'}</td>
            <td><select disabled aria-label={`${agent.kind} protocol family`} value={typeof intent?.protocol === 'string' ? intent.protocol : ''}>
              <option value="">Not recorded</option>{PROTOCOLS.map(p => <option key={p} value={p}>{p}</option>)}
              {typeof intent?.protocol === 'string' && !PROTOCOLS.includes(intent.protocol) && <option value={intent.protocol}>{intent.protocol}</option>}
            </select></td>
            <td>Not emitted in Stage 1</td></tr>;
        })}
        {agents.length === 0 && <tr><td colSpan={4} className="muted">The draft declares no agent groups.</td></tr>}
      </tbody></table></div>
    </fieldset>}
  </ModuleShell>;
}

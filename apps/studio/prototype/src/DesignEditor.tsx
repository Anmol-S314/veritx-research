import { useCallback, useMemo, useState } from 'react';
import type { LoadedProject } from './project';
import type { Topology } from './gateway';
import { Button, Empty, PageLink, Properties } from './ui';
import { DraftEditor, type DraftSectionId } from './DraftEditor';
import type { IntentSaveState } from './intent';
import {
  SEVERITY_LABEL, SEVERITY_ORDER, collectProblems, derive, hex, rangeBounds, rangeName, same,
  type DecodeRow, type Derived, type Ep, type Problem, type Range, type Sel,
} from './designEditorModel';
import './designEditor.css';

type Overlay = 'kind' | 'clock' | 'ranges';
const OVERLAYS: { id: Overlay; label: string }[] = [{ id: 'kind', label: 'Agent kind' }, { id: 'clock', label: 'Clock domain' }, { id: 'ranges', label: 'Address ranges' }];
const TONES = ['#0f6c9e', '#246847', '#79540c', '#536170'];

type Paint = { fill: string; stroke: string; ink: string; dash?: boolean };
function paint(e: Ep, overlay: Overlay, d: Derived): Paint {
  const on = (tone: string): Paint => ({ fill: tone, stroke: tone, ink: '#fff' });
  const off: Paint = { fill: '#fff', stroke: '#536170', ink: '#1d242c', dash: true };
  if (overlay === 'kind') return on(TONES[d.kinds.indexOf(e.kind) % TONES.length]);
  if (overlay === 'clock') { const c = d.agentOf(e)?.clock_domain; return c ? on(TONES[d.clocks.indexOf(c) % TONES.length]) : off; }
  return d.rangesByEp.has(e.endpoint_id) ? on(TONES[0]) : off;
}
function legend(overlay: Overlay, d: Derived): { label: string; paint: Paint }[] {
  const swatch = (label: string, p: Paint) => ({ label, paint: p });
  if (overlay === 'kind') return d.kinds.map(k => swatch(k, paint(d.eps.find(e => e.kind === k)!, overlay, d)));
  if (overlay === 'clock') return [...d.clocks.map(c => swatch(c, { fill: TONES[d.clocks.indexOf(c) % TONES.length], stroke: TONES[d.clocks.indexOf(c) % TONES.length], ink: '#fff' })), swatch('Unassigned', { fill: '#fff', stroke: '#536170', ink: '#1d242c', dash: true })];
  return [swatch('Decodes at least one range', { fill: TONES[0], stroke: TONES[0], ink: '#fff' }), swatch('No range decodes here', { fill: '#fff', stroke: '#536170', ink: '#1d242c', dash: true })];
}

/** Router positions from served coordinates; a fabric without 2-D coordinates is laid out on a ring. */
function layout(topology: Topology) {
  const W = 640, H = 460, pad = 48;
  const rs = topology.routers;
  const flat = rs.every(r => r.coordinates.length >= 2 && r.coordinates.slice(0, 2).every(Number.isFinite));
  const pos = new Map<number, { x: number; y: number }>();
  if (flat) {
    const xs = rs.map(r => r.coordinates[0]), ys = rs.map(r => r.coordinates[1]);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    for (const r of rs) pos.set(r.router_id, {
      x: x1 === x0 ? W / 2 : pad + ((r.coordinates[0] - x0) / (x1 - x0)) * (W - 2 * pad),
      y: y1 === y0 ? H / 2 : pad + ((r.coordinates[1] - y0) / (y1 - y0)) * (H - 2 * pad),
    });
  } else {
    rs.forEach((r, i) => { const a = (2 * Math.PI * i) / rs.length - Math.PI / 2; pos.set(r.router_id, { x: W / 2 + Math.cos(a) * (W / 2 - pad), y: H / 2 + Math.sin(a) * (H / 2 - pad) }); });
  }
  return { W, H, pos, radius: rs.length > 36 ? 9 : 16 };
}

function Canvas({ topology, sel, onSelect, overlay, d }: { topology: Topology; sel: Sel; onSelect: (s: Sel) => void; overlay: Overlay; d: Derived }) {
  const { W, H, pos, radius } = useMemo(() => layout(topology), [topology]);
  const pairs = useMemo(() => {
    const seen = new Set<string>();
    return topology.channels.filter(c => { const k = c.src_router < c.dst_router ? `${c.src_router}:${c.dst_router}` : `${c.dst_router}:${c.src_router}`; if (seen.has(k)) return false; seen.add(k); return true; });
  }, [topology]);
  const rangeTarget = sel.kind === 'range' ? d.rowFor(sel.id)?.target_endpoint_id : undefined;
  const hiEp = sel.kind === 'endpoint' ? sel.id : rangeTarget;
  const selRouter = sel.kind === 'router' ? sel.id : hiEp !== undefined ? topology.endpoints.find(e => e.endpoint_id === hiEp)?.router_id : undefined;
  const labelled = radius > 9;
  return <svg className="de-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Fabric: ${topology.counts?.routers ?? topology.routers.length} routers`}>
    {pairs.map((c, i) => { const a = pos.get(c.src_router), b = pos.get(c.dst_router); if (!a || !b) return null;
      const hot = selRouter !== undefined && (c.src_router === selRouter || c.dst_router === selRouter);
      return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className={hot ? 'de-link hot' : 'de-link'} />; })}
    {topology.routers.map(r => { const p = pos.get(r.router_id)!; const isSel = selRouter === r.router_id && sel.kind === 'router';
      return <g key={r.router_id} className="de-node" tabIndex={0} role="button" aria-label={`Router ${r.router_id}`} aria-pressed={isSel}
        onClick={() => onSelect({ kind: 'router', id: r.router_id })} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect({ kind: 'router', id: r.router_id }); } }}>
        <circle cx={p.x} cy={p.y} r={radius} className={isSel ? 'sel' : undefined} />
        {labelled && <text x={p.x} y={p.y + 4} textAnchor="middle" className={isSel ? 'sel' : undefined}>R{r.router_id}</text>}
      </g>; })}
    {topology.endpoints.map(e => { const p = pos.get(e.router_id); if (!p) return null;
      const same_router = topology.endpoints.filter(x => x.router_id === e.router_id); const k = same_router.indexOf(e);
      const isSel = hiEp === e.endpoint_id; const pt = paint(e, overlay, d);
      return <g key={e.endpoint_id} className="de-ep" tabIndex={0} role="button" aria-label={`Endpoint ${e.endpoint_id}, ${e.kind}`} aria-pressed={isSel}
        onClick={() => onSelect({ kind: 'endpoint', id: e.endpoint_id })} onKeyDown={ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); onSelect({ kind: 'endpoint', id: e.endpoint_id }); } }}>
        <rect x={p.x + radius + 4} y={p.y - radius + k * 14} width={labelled ? 44 : 10} height={12} rx={2} className={isSel ? 'sel' : undefined} style={{ fill: pt.fill, stroke: pt.stroke, strokeDasharray: pt.dash ? '3 2' : undefined }} />
        {labelled && <text x={p.x + radius + 26} y={p.y - radius + k * 14 + 9} textAnchor="middle" style={{ fill: pt.ink }}>EP{e.endpoint_id}</text>}
      </g>; })}
  </svg>;
}

const selLabel = (s: Sel) => s.kind === 'fabric' ? 'Fabric' : s.kind === 'router' ? `Router R${s.id}` : s.kind === 'endpoint' ? `Endpoint EP${s.id}` : `Range ${s.id}`;

function Pick({ sel, onSelect, children }: { sel: Sel; onSelect: (s: Sel) => void; children: React.ReactNode }) {
  return <button type="button" className="de-pick" onClick={() => onSelect(sel)}>{children}</button>;
}

function SelectionFacts({ data, sel, d, onSelect }: { data: LoadedProject; sel: Sel; d: Derived; onSelect: (s: Sel) => void }) {
  const t = data.topology;
  const rangeList = (rows: DecodeRow[]) => rows.length
    ? <ul className="de-here">{rows.map((r, i) => <li key={i}><Pick sel={{ kind: 'range', id: r.name ?? '' }} onSelect={onSelect}><strong>{r.name}</strong> <span className="mono">{r.base !== undefined ? hex(BigInt(r.base)) : ''}</span></Pick></li>)}</ul>
    : <p className="de-note">None.</p>;
  if (sel.kind === 'fabric') {
    return <Properties rows={[['Family', t?.family ?? 'Not served'], ['Routers', String(t?.counts?.routers ?? t?.routers.length ?? 0)], ['Channels', String(t?.counts?.channels ?? t?.channels.length ?? 0)], ['Endpoints', String(d.eps.length)], ['Agent groups', String(d.agents.length)], ['Address ranges', String(d.rows.length)]]} />;
  }
  if (sel.kind === 'router' && t) {
    const r = t.routers.find(x => x.router_id === sel.id);
    const out = t.channels.filter(c => c.src_router === sel.id), inn = t.channels.filter(c => c.dst_router === sel.id);
    const here = d.byRouter.get(sel.id) ?? [];
    const ranges = here.flatMap(e => d.rangesByEp.get(e.endpoint_id) ?? []);
    const clocks = [...new Set(here.map(e => d.agentOf(e)?.clock_domain ?? 'unassigned'))];
    return <>
      <Properties rows={[['Router', `R${sel.id}`], ['Coordinates', r ? r.coordinates.join(', ') : 'Not served'], ['Links out / in', `${out.length} / ${inn.length}`], ['Link width', [...new Set(out.map(c => c.width_bits))].join(', ') || '—'], ['Clock domains here', clocks.join(', ') || '—']]} />
      <h2 className="de-h">Endpoints here · {here.length}</h2>
      {here.length ? <ul className="de-here">{here.map(e => { const a = d.agentOf(e); return <li key={e.endpoint_id}><Pick sel={{ kind: 'endpoint', id: e.endpoint_id }} onSelect={onSelect}><strong>EP{e.endpoint_id}</strong> {e.kind}<small>{a ? `${a.protocol ?? '—'} · ${a.data_width ?? '—'}-bit` : ''}</small></Pick></li>; })}</ul> : <p className="de-note">No endpoint attaches to this router.</p>}
      <h2 className="de-h">Address ranges decoding here · {ranges.length}</h2>
      {rangeList(ranges)}
    </>;
  }
  if (sel.kind === 'endpoint' && t) {
    const e = d.eps.find(x => x.endpoint_id === sel.id); if (!e) return null;
    const a = d.agentOf(e);
    return <>
      <Properties rows={[['Endpoint', `EP${e.endpoint_id}`], ['Kind', e.kind], ['Router · port', `R${e.router_id} · ${e.port_id}`], ['Group · instance', `${e.group_index ?? '—'} · ${e.instance_index ?? '—'}`]]} />
      <h2 className="de-h">Agent group {e.group_index ?? ''}</h2>
      {a ? <Properties rows={[['Protocol', a.protocol ?? '—'], ['Data / address width', `${a.data_width ?? '—'} / ${a.addr_width ?? '—'} bits`], ['Instances', String(a.count)], ['Clock domain', a.clock_domain ?? 'Unassigned'], ['Power domain', (a as { power_domain?: string | null }).power_domain ?? 'Unassigned']]} /> : <p className="de-note">No draft agent group at this index.</p>}
      <h2 className="de-h">Address ranges targeting it</h2>
      {rangeList(d.rangesByEp.get(e.endpoint_id) ?? [])}
    </>;
  }
  if (sel.kind === 'range') {
    const ranges = (data.request?.address_map?.ranges ?? []) as Range[];
    const i = ranges.findIndex((r, n) => rangeName(r, n) === sel.id); const r = ranges[i]; const b = r && rangeBounds(r);
    const row = d.rowFor(sel.id); const target = row?.target_endpoint_id !== undefined ? d.eps.find(e => e.endpoint_id === row.target_endpoint_id) : undefined;
    return r ? <>
      <Properties rows={[['Range', sel.id], ['Base', b ? hex(b.base) : String(r.base ?? '—')], ['Size', String(r.size_bytes ?? r.size ?? '—')], ['Policy', String((r as { selection_policy?: string }).selection_policy ?? '—')]]} />
      <h2 className="de-h">Decodes to</h2>
      {target ? <ul className="de-here"><li><Pick sel={{ kind: 'endpoint', id: target.endpoint_id }} onSelect={onSelect}><strong>EP{target.endpoint_id}</strong> {target.kind}<small>on R{target.router_id}</small></Pick></li></ul>
        : <p className="de-note">{d.rows.length ? 'This range has no compiled decode row yet. Compile the draft.' : 'No compiled decode rows are served.'}</p>}
    </> : null;
  }
  return null;
}

function Outline({ data, sel, problems, onSelect }: { data: LoadedProject; sel: Sel; problems: Problem[]; onSelect: (s: Sel) => void }) {
  const t = data.topology;
  const ranges = (data.request?.address_map?.ranges ?? []) as Range[];
  const flagged = (s: Sel) => problems.some(p => p.severity === 'error' && p.at && same(p.at, s));
  const row = (s: Sel, label: string, right?: string) => <li key={`${s.kind}:${(s as { id?: unknown }).id ?? ''}`}>
    <button type="button" className={`de-item${same(sel, s) ? ' sel' : ''}`} aria-current={same(sel, s) ? 'true' : undefined} onClick={() => onSelect(s)}>
      {flagged(s) && <span className="de-flag" aria-label="Has an error" />}<span>{label}</span>{right && <small>{right}</small>}
    </button></li>;
  return <nav className="de-outline" aria-label="Design outline">
    <ul>{row({ kind: 'fabric' }, `Fabric · ${t?.family ?? 'not served'}`)}</ul>
    <details open><summary>Endpoints <small>{t?.endpoints.length ?? 0}</small></summary>
      <ul>{(t?.endpoints ?? []).map(e => row({ kind: 'endpoint', id: e.endpoint_id }, `EP${e.endpoint_id} · ${e.kind}`, `R${e.router_id}`))}</ul></details>
    <details><summary>Routers <small>{t?.routers.length ?? 0}</small></summary>
      <ul>{(t?.routers ?? []).map(r => row({ kind: 'router', id: r.router_id }, `R${r.router_id}`))}</ul></details>
    <details open><summary>Address ranges <small>{ranges.length}</small></summary>
      <ul>{ranges.map((r, i) => row({ kind: 'range', id: rangeName(r, i) }, rangeName(r, i), rangeBounds(r) ? hex(rangeBounds(r)!.base) : undefined))}</ul></details>
  </nav>;
}

export function DesignEditor({ data }: { data: LoadedProject | null }) {
  const [sel, setSel] = useState<Sel>({ kind: 'fabric' });
  const [save, setSave] = useState<IntentSaveState | null>(null);
  const [view, setView] = useState<'canvas' | 'settings'>('canvas');
  const [open, setOpen] = useState<{ id: DraftSectionId; n: number }>({ id: 'topology', n: 0 });
  const openSettings = (id: DraftSectionId) => { setOpen(o => ({ id, n: o.n + 1 })); setView('settings'); };
  const onSaveState = useCallback((s: IntentSaveState) => setSave(s), []);
  const [overlay, setOverlay] = useState<Overlay>('kind');
  const problems = useMemo(() => (data ? collectProblems(data, save) : []), [data, save]);
  const d = useMemo(() => (data ? derive(data) : null), [data]);

  if (!data || !d) {
    return <div className="view-main"><Empty title="No gateway project is loaded" action={<PageLink page="shared/projects" primary>Load a project</PageLink>}>
      The editor changes the real draft the compiler reads, so it needs a loaded project. It does not invent a local one.
    </Empty></div>;
  }

  const onObject = problems.filter(p => p.at && same(p.at, sel));
  const active = data.detail.active_revision_id;
  const cert = data.compileResult?.certificate?.overall;
  const counts = SEVERITY_ORDER.map(s => [s, problems.filter(p => p.severity === s).length] as const).filter(([s, n]) => s !== 'info' && n > 0);
  const status = save?.busy ? 'Saving and compiling…'
    : save?.dirty ? `Unsaved edits. Revision ${active?.split('-').pop() ?? 'none'} is stale.`
    : active ? `Revision ${active.split('-').pop()} · certificate ${cert ?? 'not served'}` : 'No compiled revision';
  const canSave = !!save && save.dirty && save.valid && !save.busy;

  return <div className="design-editor">
    <div className="de-toolbar" role="toolbar" aria-label="Editor actions">
      <Button primary disabled={!canSave} title={!save?.dirty ? 'No edits to save' : !save.valid ? 'Fix the issues in Properties first' : undefined} onClick={() => save?.save()}>Save &amp; compile</Button>
      <span className="de-status" role="status">{status}</span>
      <div className="segmented de-view" role="group" aria-label="Centre view">
        <button type="button" aria-pressed={view === 'canvas'} className={view === 'canvas' ? 'active' : ''} onClick={() => setView('canvas')}>Fabric canvas</button>
        <button type="button" aria-pressed={view === 'settings'} className={view === 'settings' ? 'active' : ''} onClick={() => setView('settings')}>Draft settings</button>
      </div>
    </div>
    <aside className="de-panel de-left" aria-label="Outline"><div className="de-panel-head">Outline</div><Outline data={data} sel={sel} problems={problems} onSelect={setSel} /></aside>
    <section className="de-canvas" aria-label="Fabric canvas" hidden={view !== 'canvas'}>
      {data.topology && <div className="de-overlay"><span>Colour endpoints by</span>
        <div className="segmented" role="group" aria-label="Endpoint colour">
          {OVERLAYS.map(o => <button key={o.id} type="button" aria-pressed={overlay === o.id} className={overlay === o.id ? 'active' : ''} onClick={() => setOverlay(o.id)}>{o.label}</button>)}
        </div></div>}
      {data.topology ? <Canvas topology={data.topology} sel={sel} onSelect={setSel} overlay={overlay} d={d} />
        : <Empty title="No compiled topology">Save &amp; compile the draft to draw the fabric. Nothing is drawn from an unsaved draft.</Empty>}
      {data.topology && <ul className="de-legend" aria-label="Legend">{legend(overlay, d).map(l => <li key={l.label}><svg width="14" height="12" aria-hidden="true"><rect x="1" y="1" width="12" height="10" rx="2" style={{ fill: l.paint.fill, stroke: l.paint.stroke, strokeDasharray: l.paint.dash ? '3 2' : undefined }} /></svg>{l.label}</li>)}</ul>}
    </section>
    <section className="de-settings" aria-label="Draft settings" hidden={view !== 'settings'}>
      <DraftEditor project={data} embedded onSaveState={onSaveState} openSection={open} />
    </section>
    <aside className="de-panel de-right" aria-label="Inspector">
      <div className="de-panel-head">Inspector<span className="de-sel">{selLabel(sel)}</span></div>
      <div className="de-props">
        <SelectionFacts data={data} sel={sel} d={d} onSelect={setSel} />
        {onObject.length > 0 && <><h2 className="de-h">Problems here</h2>
          <ul className="de-here">{onObject.map((p, i) => <li key={i}><strong className={`de-sev ${p.severity}`}>{SEVERITY_LABEL[p.severity]}</strong> {p.message}</li>)}</ul></>}
        <h2 className="de-h">{sel.kind === 'endpoint' || sel.kind === 'range' ? 'Edit' : 'Settings that apply'}</h2>
        {sel.kind === 'endpoint' && <><p className="de-note">An endpoint’s attachment is derived by the compiler. Its properties belong to its agent group.</p>
          <div className="de-jumps"><PageLink page="design/agent-map">Edit agent groups</PageLink></div></>}
        {sel.kind === 'range' && <><p className="de-note">A range targets an agent group; the compiler resolves the endpoint.</p>
          <div className="de-jumps"><PageLink page="design/addresses">Edit address ranges</PageLink></div></>}
        {(sel.kind === 'fabric' || sel.kind === 'router') && <>
          <p className="de-note">{sel.kind === 'fabric' ? 'Fabric-wide values.' : 'Router parameters are fabric-wide: they apply to every router, not only this one.'}</p>
          <div className="de-jumps">
            <Button onClick={() => openSettings('topology')}>Topology &amp; sizing</Button>
            <Button onClick={() => openSettings('physical')}>Physical assumptions</Button>
            <Button onClick={() => openSettings('router')}>Router &amp; pipeline</Button>
          </div></>}
      </div>
    </aside>
    <section className="de-panel de-problems" aria-label="Problems">
      <div className="de-panel-head">Problems
        <span className="de-counts">{counts.length ? counts.map(([s, n]) => <span key={s} className={`de-count ${s}`}>{n} {SEVERITY_LABEL[s].toLowerCase()}</span>) : 'None'}</span></div>
      <table className="de-table"><tbody>
        {problems.map((p, i) => <tr key={i} className={p.at ? 'jump' : undefined} tabIndex={p.at ? 0 : undefined}
          onClick={() => p.at && setSel(p.at)} onKeyDown={e => { if (p.at && e.key === 'Enter') setSel(p.at); }}>
          <td className={`de-sev ${p.severity}`}>{SEVERITY_LABEL[p.severity]}</td><td className="de-src">{p.source}</td>
          <td className="mono">{p.code}</td><td>{p.message}</td></tr>)}
        {problems.length === 0 && <tr><td colSpan={4} className="de-src">No verdicts reported for this revision.</td></tr>}
      </tbody></table>
      <details className="assumptions"><summary>Assumptions &amp; scope</summary>
        <p>Problems merges compile verdicts, certificate obligations and local interval arithmetic for the draft. A local check is not hardware verification, and a certificate describes the compiled revision, not unsaved edits. “Not evaluated” means no tool measured it; it is never a pass.</p></details>
    </section>
  </div>;
}

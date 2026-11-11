import { useState, type ReactNode } from 'react';
import { NETWORK_CYCLES, linkObservations } from './analysis';
import { BASE_REVISION, ROUTERS, editDraft, queueFlits, rawGBps } from './model';
import { Assumptions, Badge, Button, Dialog, Field, Inspector, Notice, PageLink, Properties, Section, type ViewProps } from './ui';

type XY = { row: number; col: number };
const xy = (router: string): XY => { const [, row, col] = router.split('_').map(Number); return { row, col }; };
const NODE = { w: 92, h: 52 };
const position = (router: string) => { const { row, col } = xy(router); return { x: 34 + col * 132, y: 30 + row * 108 }; };
const NEIGHBOURS: [string, (r: number, c: number) => boolean, (r: number, c: number) => [number, number]][] = [
  ['north', (r) => r > 0, (r, c) => [r - 1, c]],
  ['south', (r) => r < 3, (r, c) => [r + 1, c]],
  ['west', (_r, c) => c > 0, (r, c) => [r, c - 1]],
  ['east', (_r, c) => c < 3, (r, c) => [r, c + 1]],
];

export function FabricView({ state, setState, notify, navigate, banner }: ViewProps & { banner?: ReactNode }) {
  const [layer, setLayer] = useState<'derived' | 'attached' | 'none'>('derived');
  const [selected, setSelected] = useState('R_1_2');
  const [review, setReview] = useState(false);
  const [depth, setDepth] = useState(16);
  const links = linkObservations();
  const link = (from: string, to: string) => links.find(l => l.from === from && l.to === to);
  const outbound = links.filter(l => l.from === selected);
  const attached = state.draft.endpoints.filter(e => e.router === selected);
  const capacity = rawGBps(128, 1400);
  const busiest = links[0];
  const peak = Math.max(...links.map(l => l.percent));
  const storyDepth = state.draft.depth;
  const before = queueFlits(state.draft);
  const after = queueFlits({ ...state.draft, depth });
  const validDepth = Number.isInteger(depth) && depth >= 2 && depth <= 64;

  return <div className="view-layout"><div className="view-main">
    {banner}
    <div className="toolbar">
      <Field label="Overlay layer"><select value={layer} onChange={e => setLayer(e.target.value as typeof layer)}>
        <option value="derived">Derived link utilization (SIM-402 proxy)</option>
        <option value="attached">Declared endpoint attachment</option>
        <option value="none">No overlay</option>
      </select></Field>
      <Badge>4×4 orthogonal mesh · 16 routers</Badge>
      <Badge>128-bit links · 1 flit/cycle</Badge>
      <Button onClick={() => navigate('analysis/topology')}>Open analysis overlay</Button>
    </div>
    <div className="toolbar toolbar-start"><PageLink page="shared/projects">Load a gateway project</PageLink></div>
    <Section title="Logical mesh" actions={<span className="mono muted">{selected} selected</span>}>
      <svg className="fabric-canvas" viewBox="0 0 580 466" role="group" aria-label="Logical four by four mesh, select a router">
        <defs><marker id="fabric-tip" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6" fill="currentColor" /></marker></defs>
        {ROUTERS.flatMap(router => {
          const { row, col } = xy(router), a = position(router);
          return NEIGHBOURS.filter(([, ok]) => ok(row, col)).map(([dir, , step]) => {
            const [nr, nc] = step(row, col), to = `R_${nr}_${nc}`, b = position(to), value = link(router, to);
            const midY = a.y + NODE.h / 2, midX = a.x + NODE.w / 2;
            const vertical = dir === 'north' || dir === 'south';
            const x1 = vertical ? midX : midX + NODE.w / 2, y1 = vertical ? (dir === 'north' ? a.y : a.y + NODE.h) : midY;
            const x2 = vertical ? b.x + NODE.w / 2 : b.x + (dir === 'east' ? 0 : NODE.w), y2 = vertical ? b.y + (dir === 'north' ? NODE.h : 0) : midY;
            const emphasis = layer === 'derived' && value ? Math.min(1, value.percent / Math.max(peak, 1)) : 0;
            const forward = dir === 'south' || dir === 'east';
            return <g key={`${router}-${dir}`} className="fabric-link">
              <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={emphasis > 0.66 ? '#79540c' : emphasis > 0.33 ? '#8aa6b8' : '#c9d1da'} strokeWidth={layer === 'derived' ? 2 + emphasis * 4 : 2} markerEnd={dir === 'south' ? 'url(#fabric-tip)' : undefined} />
              {layer === 'derived' && value && emphasis > 0.5 && <text x={vertical ? midX + 7 : (x1 + x2) / 2} y={vertical ? (y1 + y2) / 2 : midY - 7} className="fabric-link-label">{value.percent.toFixed(1)}%</text>}
              {!forward && null}
            </g>;
          });
        })}
        {ROUTERS.map(router => {
          const p = position(router), count = state.draft.endpoints.filter(e => e.router === router).length, on = router === selected;
          return <g key={router} transform={`translate(${p.x},${p.y})`} className={`fabric-node ${on ? 'fabric-node-on' : ''}`} role="button" tabIndex={0} aria-label={`Router ${router}, ${count} declared endpoints`}
            onClick={() => setSelected(router)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(router); } }}>
            <rect width={NODE.w} height={NODE.h} rx="3" />
            <text x={NODE.w / 2} y="21" textAnchor="middle" className="fabric-node-id">{router}</text>
            <text x={NODE.w / 2} y="39" textAnchor="middle" className="fabric-node-meta">{layer === 'attached' ? `${count} EP` : layer === 'derived' ? `${state.draft.vcs} VC · ${state.draft.depth} f` : `P:${5}`}</text>
            {count > 0 && layer !== 'derived' && <circle cx={NODE.w - 9} cy="9" r="3.5" className="fabric-node-dot" />}
          </g>;
        })}
        <text x="290" y="458" textAnchor="middle" className="fabric-canvas-note">Logical adjacency</text>
      </svg>
      <div className="legend">
        <span><i className="legend-dot blue" />Selected router</span>
        <span><i className="legend-dot" />Declared link</span>
        <span><i className="legend-dot amber" />Derived proxy above half of peak</span>
        <span>Peak derived proxy {peak.toFixed(2)}% of {NETWORK_CYCLES.toLocaleString()} cycles</span>
      </div>
    </Section>
    <Section title="Derived link proxy" actions={<Badge>Canonical X-then-Y routes</Badge>}>
      <div className="table-scroll"><table><thead><tr><th>Directed link</th><th>Routed flits</th><th>Proxy</th><th>Raw capacity</th></tr></thead><tbody>
        {outbound.length === 0 ? <tr><td colSpan={4}>No pair fixture traffic leaves {selected} under the stated canonical routes.</td></tr> : outbound.map(l => <tr key={`${l.from}:${l.to}`}><th className="mono">{l.from} → {l.to}</th><td className="numeric">{l.flits.toLocaleString()}</td><td className="numeric">{l.percent.toFixed(2)}%</td><td className="numeric">{capacity} GB/s</td></tr>)}
      </tbody></table></div>
      <p>Busiest directed link overall: <strong className="mono">{busiest.from} → {busiest.to}</strong> at {busiest.percent.toFixed(2)}% of the window.</p>
    </Section>
    <Section title="Open obligations" actions={<Badge tone="amber">4 not established</Badge>}>
      <div className="table-scroll"><table><thead><tr><th>Obligation</th><th>State</th><th>Why it is open</th></tr></thead><tbody>
        <tr><th>Deadlock freedom</th><td><Badge tone="amber">Not established</Badge></td><td>Channel dependency order, allocation progress, and credit-return ordering are not proven for this configuration. If wrap-around links are intended, X-then-Y order needs dateline virtual channels before any freedom claim.</td></tr>
        <tr><th>DRC / LVS / physical</th><td><Badge tone="amber">Not evaluated</Badge></td><td>No floorplan, placement, parasitics, or foundry rule deck is connected. Nothing here is sign-off data.</td></tr>
        <tr><th>RTL generation</th><td><Badge tone="amber">Partial</Badge></td><td>Product preview emitter covers connected point-to-point, 2-VC topologies only. This local 4×4 mesh draft has no gateway project and was not run. See FinalDelivery / Flow · Finalize & RTL (flow/run) for the current-project preview. M5 research evidence (12 required targets) is separate and is not a qualification of this draft.</td></tr>
        <tr><th>Area / power</th><td><Badge tone="amber">Not evaluated</Badge></td><td>Queue storage is a flit-count proxy only. No cell area, activity factor, or power number is derived or asserted.</td></tr>
      </tbody></table></div>
    </Section>
    <Assumptions rows={[
      ['Scope', 'Declared logical topology only. No die coordinate frame, floorplan, wire geometry or observed traffic is connected.'],
      ['Overlay', 'Derived link utilization is an arithmetic proxy over an authored pair fixture, not measured arbitration or per-link counters.'],
      ['Structure', 'Logical adjacency is not a permission rule; shared wires are declared, not inferred from traffic.'],
      ['Not evaluated', 'Area, power, timing, DRC/LVS, physical sign-off and deadlock freedom. Queue storage is a flit-count proxy only.'],
      ['RTL generation', 'Product preview emitter covers connected point-to-point, 2-VC topologies only. This local 4×4 mesh draft has no gateway project and was not run. See FinalDelivery / Flow · Finalize & RTL (flow/run) for the current-project preview. M5 research evidence (12 required targets) is separate and is not a qualification of this draft.'],
    ]} />
  </div>
  <Inspector title={`Router ${selected}`}>
    <Badge tone="blue">{xy(selected).row}, {xy(selected).col} · logical</Badge>
    <Properties rows={[
      ['Declared ports', '5 (N, S, E, W, Local)'],
      ['Virtual channels', `${state.draft.vcs} per port`],
      ['Queue depth', `${state.draft.depth} flits per VC`],
      ['Declared storage, whole fabric', `${before.toLocaleString()} flits`],
      ['Raw link capacity', `${capacity} GB/s per direction`],
      ['Packet/flit format', 'Model intent only; no encoder'],
      ['Deadlock freedom', 'Not established'],
      ['RTL for this router', 'Not generated or linted'],
    ]} />
    <Section title={`Attached endpoints (${attached.length})`}>
      {attached.length === 0 ? <p className="muted">No declared endpoint attaches here in the current draft.</p> : <div className="stack">{attached.map(ep => <button key={ep.id} className="text-button mono" onClick={() => { setState(s => ({ ...s, selectedEndpoint: ep.id })); navigate('design/endpoints'); }}>{ep.id} · {ep.role} · {ep.width}-bit</button>)}</div>}
      <PageLink page="design/catalog">Add endpoint intent</PageLink>
    </Section>
    <Section title="Reviewed change">
      <Button primary onClick={() => { setDepth(Math.min(64, Math.max(16, storyDepth * 2))); setReview(true); }}>Review VC depth change</Button>
    </Section>
  </Inspector>
  {review && <Dialog title="Review VC-depth change — local draft only" onClose={() => setReview(false)}>
    <Notice tone="amber">Applies to every VC on every port. Historical results are unchanged; re-evaluation is required.</Notice>
    <Field label="Queue depth per VC (flits)"><input type="number" min={2} max={64} value={depth} onChange={e => setDepth(e.target.valueAsNumber)} /></Field>
    {!validDepth && <Notice tone="red">Depth must be a whole number between 2 and 64 flits.</Notice>}
    <Properties rows={[
      ['Revision', `${BASE_REVISION} → local draft edit ${state.draft.revision + 1}`],
      ['Depth', `${storyDepth} → ${validDepth ? depth : '—'} flits per VC`],
      ['Declared storage', `${before.toLocaleString()} → ${validDepth ? after.toLocaleString() : '—'} flits`],
      ['Area / power impact', 'Not estimated'],
      ['Deadlock freedom', 'Still not established after this change'],
      ['Historical runs', 'Unaffected; re-evaluation required'],
    ]} />
    <div className="dialog-actions">
      <Button onClick={() => setReview(false)}>Cancel</Button>
      <Button primary disabled={!validDepth || depth === storyDepth} onClick={() => {
        setState(s => editDraft(s, `Changed queue depth to ${depth} flits per VC locally. Observation findings are not resolved by this edit.`, d => ({ ...d, depth })));
        setReview(false); notify(`Draft depth set to ${depth} flits per VC. Re-evaluation required; no congestion, deadlock, or physical claim follows.`);
      }}>Apply local depth change</Button>
    </div>
  </Dialog>}
  </div>;
}

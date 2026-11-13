import { useState, type ReactNode } from 'react';
import { linkObservations } from './analysis';
import { BASE_REVISION, ROUTERS, editDraft, queueFlits, rawGBps } from './model';
import { Badge, Button, Dialog, Field, Icon, Inspector, Notice, PageLink, Properties, Section, type ViewProps } from './ui';
import { TopologyGraph } from './TopologyGraph';
import { localTopology } from './localDesign';

const xy = (routerId: number) => ({ row: Math.floor(routerId / 4), col: routerId % 4 });
const routerName = (routerId: number) => ROUTERS[routerId] ?? '';
const routerIdOf = (router: string) => Math.max(0, ROUTERS.indexOf(router));

export function FabricView({ state, setState, notify, navigate, banner }: ViewProps & { banner?: ReactNode }) {
  const [overlay, setOverlay] = useState<'derived' | 'none'>('derived');
  const [selected, setSelected] = useState<number | null>(6);
  const [review, setReview] = useState(false);
  const [depth, setDepth] = useState(16);
  const [filter, setFilter] = useState('');
  const topology = localTopology(state.draft);
  const links = linkObservations();
  const capacity = rawGBps(128, 1400);
  const storyDepth = state.draft.depth;
  const before = queueFlits(state.draft);
  const after = queueFlits({ ...state.draft, depth });
  const validDepth = Number.isInteger(depth) && depth >= 2 && depth <= 64;
  const router = selected === null ? null : topology.routers.find(item => item.router_id === selected) ?? null;
  const selectedRouter = router ? routerName(router.router_id) : null;
  const outbound = selectedRouter ? links.filter(link => link.from === selectedRouter) : [];
  const attached = selected === null ? [] : topology.endpoints.filter(endpoint => endpoint.router_id === selected);
  const load = new Map(links.map(link => [
    `${routerIdOf(link.from)}:1->${routerIdOf(link.to)}:1`,
    link.percent,
  ]));
  const query = filter.trim().toLowerCase();
  const matchingRouters = topology.routers.filter(item => !query || `r${item.router_id} ${ROUTERS[item.router_id] ?? ''}`.toLowerCase().includes(query));
  const matchingEndpoints = topology.endpoints.filter(item => !query || `${item.kind} ${item.endpoint_id} r${item.router_id}`.toLowerCase().includes(query));
  const rows = new Map<number, typeof topology.routers>();
  for (const item of matchingRouters) {
    const row = xy(item.router_id).row;
    rows.set(row, [...(rows.get(row) ?? []), item]);
  }
  const endpointCount = (routerId: number) => topology.endpoints.filter(item => item.router_id === routerId).length;

  return <div className="view-layout fabric-view"><div className="view-main">
    {banner}
    <div className="fabric-toolbar">
      <div className="fabric-toolbar-main">
        <Badge tone="blue">Local draft</Badge>
        <span className="mono fabric-counts">4×4 mesh · {topology.routers.length} routers · {topology.channels.length} directed channels · {topology.endpoints.length} endpoints</span>
      </div>
      <div className="actions fabric-toolbar-actions">
        <div className="segmented fabric-plane-tabs" role="group" aria-label="Overlay layer">
          <button type="button" className={overlay === 'derived' ? 'active' : ''} onClick={() => setOverlay('derived')}>Utilization</button>
          <button type="button" className={overlay === 'none' ? 'active' : ''} onClick={() => setOverlay('none')}>None</button>
        </div>
        <Button onClick={() => navigate('analysis/topology')}>Analysis overlay</Button>
      </div>
    </div>

    <div className="fabric-workbench">
      <aside className="fabric-tree" aria-label="Fabric objects">
        <div className="fabric-tree-tabs segmented" role="group" aria-label="Fabric tree view">
          <button type="button" className="active" aria-pressed="true">Routers</button>
        </div>
        <div className="fabric-search">
          <Icon name="search" size={13} />
          <input aria-label="Filter fabric entities" placeholder="Filter routers, endpoints" value={filter} onChange={event => setFilter(event.target.value)} />
        </div>
        <div className="fabric-tree-scroll">
          {[...rows.entries()].sort((a, b) => a[0] - b[0]).map(([row, routers]) => <div key={row} className="tree-group">
            <div className="tree-row-head"><span>Row {row}</span><span>{routers.length}</span></div>
            {[...routers].sort((a, b) => xy(a.router_id).col - xy(b.router_id).col).map(item => <button type="button" key={item.router_id} className={`tree-router${selected === item.router_id ? ' selected' : ''}`} onClick={() => setSelected(selected === item.router_id ? null : item.router_id)}>
              <span className="mono">R{item.router_id}</span><small>{endpointCount(item.router_id)} EP</small>
            </button>)}
          </div>)}
          {matchingRouters.length === 0 && <p className="meta-line">No router matches.</p>}
          <div className="tree-group">
            <div className="tree-row-head"><span>Endpoints</span><span>{topology.endpoints.length}</span></div>
            {matchingEndpoints.map(item => <button type="button" key={item.endpoint_id} className="tree-endpoint" onClick={() => setSelected(item.router_id)}>
              <span className="mono">{item.kind}#{item.endpoint_id}</span><span>R{item.router_id}</span>
            </button>)}
            {matchingEndpoints.length === 0 && <p className="meta-line">No endpoint matches.</p>}
          </div>
        </div>
      </aside>

      <div className="fabric-center">
        <div className="fabric-canvas-scroll">
          <div className="fabric-canvas" style={{ width: '100%', height: '100%' }}>
            <TopologyGraph topology={topology} selected={selected} onSelect={id => setSelected(id === selected ? null : id)} load={overlay === 'derived' ? load : undefined} labels showSharedWires={false} />
          </div>
          {selected === null && <div className="fabric-canvas-hint">Select a router or endpoint to inspect</div>}
        </div>
      </div>
    </div>
  </div>

  <Inspector title={router ? 'Router' : 'Fabric'}>
    {router && <>
      <div className="inspector-title-row"><h3 className="mono">R{router.router_id}</h3><Badge tone="blue">{xy(router.router_id).row}, {xy(router.router_id).col}</Badge></div>
      <Properties rows={[
        ['Declared ports', '5 · N, S, E, W, Local'],
        ['Virtual channels', `${state.draft.vcs} per port`],
        ['Queue depth', `${state.draft.depth} flits per VC`],
        ['Declared storage', `${before.toLocaleString()} flits`],
        ['Raw link capacity', `${capacity} GB/s per direction`],
        ['Attached endpoints', attached.length ? String(attached.length) : 'None'],
      ]} />
      <Section title={`Outbound links · ${outbound.length}`} actions={<Badge tone={overlay === 'derived' ? 'blue' : 'neutral'}>{overlay === 'derived' ? 'derived proxy' : 'overlay off'}</Badge>}>
        {outbound.length === 0
          ? <p className="muted">No pair fixture traffic leaves {selectedRouter}.</p>
          : <table className="compact-table"><tbody>{outbound.map(link => <tr key={`${link.from}:${link.to}`}>
            <th className="mono">{link.from} → {link.to}</th>
            <td className="numeric">{link.flits.toLocaleString()}</td>
            <td className="numeric">{link.percent.toFixed(2)}%</td>
          </tr>)}</tbody></table>}
        <p className="quiet-line">Derived from authored pair counts over canonical X-then-Y routes. Not a measured counter.</p>
      </Section>
      {attached.length > 0 && <Section title={`Declared endpoints · ${attached.length}`}>
        <ul className="compact-list">{attached.map(endpoint => {
          const declared = state.draft.endpoints[endpoint.endpoint_id];
          return <li key={endpoint.endpoint_id}><span className="mono">{declared?.id ?? `EP-${endpoint.endpoint_id}`}</span><span className="muted">{declared ? `${declared.role} · ${declared.width}-bit` : endpoint.kind}</span></li>;
        })}</ul>
      </Section>}
      <Section title="Fabric control">
        <Properties rows={[['Scope', 'Every router · every port · every VC']]} />
        <Button primary onClick={() => { setDepth(Math.min(64, Math.max(16, storyDepth * 2))); setReview(true); }}>Review VC depth change</Button>
      </Section>
      <div className="inspector-links">
        <PageLink page="design/endpoints">Endpoint attachments</PageLink>
        <PageLink page="design/catalog">Add endpoint intent</PageLink>
      </div>
    </>}
    {!router && <>
      <Properties rows={[
        ['Topology', '4×4 orthogonal mesh'],
        ['Routers / endpoints', `${topology.routers.length} / ${topology.endpoints.length}`],
        ['Links', '128 bit · 1 cycle'],
        ['Attached routers', `${new Set(topology.endpoints.map(endpoint => endpoint.router_id)).size} of ${topology.routers.length}`],
      ]} />
      <p className="quiet-line">Fixture structure, not a compiled or measured fabric.</p>
      <div className="inspector-links">
        <PageLink page="shared/projects" primary>Load a gateway project</PageLink>
        <PageLink page="workloads/workflow">Open project workflow</PageLink>
      </div>
    </>}
  </Inspector>

  {review && <Dialog title="Review VC-depth change — local draft only" onClose={() => setReview(false)}>
    <Notice tone="amber">Applies to every VC on every port. Historical results are unchanged; re-evaluation is required.</Notice>
    <Field label="Queue depth per VC (flits)"><input type="number" min={2} max={64} value={depth} onChange={event => setDepth(event.target.valueAsNumber)} /></Field>
    {!validDepth && <Notice tone="red">Depth must be a whole number between 2 and 64 flits.</Notice>}
    <Properties rows={[
      ['Revision', `${BASE_REVISION} → local draft edit ${state.draft.revision + 1}`],
      ['Depth', `${storyDepth} → ${validDepth ? depth : '—'} flits per VC`],
      ['Declared storage', `${before.toLocaleString()} → ${validDepth ? after.toLocaleString() : '—'} flits`],
      ['Historical runs', 'Unaffected; re-evaluation required'],
    ]} />
    <div className="dialog-actions">
      <Button onClick={() => setReview(false)}>Cancel</Button>
      <Button primary disabled={!validDepth || depth === storyDepth} onClick={() => {
        setState(current => editDraft(current, `Changed queue depth to ${depth} flits per VC locally. Observation findings are not resolved by this edit.`, draft => ({ ...draft, depth })));
        setReview(false); notify(`Draft depth set to ${depth} flits per VC. Re-evaluation required.`);
      }}>Apply local depth change</Button>
    </div>
  </Dialog>}
  </div>;
}

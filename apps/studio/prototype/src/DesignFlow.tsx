import { useEffect, useState } from 'react';
import { useProject, type LoadedProject } from './project';
import { gateway, gatewayReason, type Obligations, type PreflightView } from './gateway';
import { Badge, Button, PageLink, Properties, Section } from './ui';
import type { PageId, PrototypeState } from './model';

import { WorkspaceTabs } from './WorkspaceTabs';

/** The five Design surfaces that can change the design are one workspace with a
 *  section strip. Tabs are real links so deep links and history work. The old
 *  Agent catalog route remains for fixtures and is redirected to Agents in a
 *  live project; it is not a sixth surface. */
const DESIGN_TABS: { id: PageId; label: string }[] = [
  { id: 'design/editor', label: 'Editor' },
  { id: 'design/fabric-topology', label: 'Fabric' },
  { id: 'design/agent-map', label: 'Agents' },
  { id: 'design/addresses', label: 'Addresses' },
  { id: 'design/domains', label: 'Domains' },
  { id: 'design/placement', label: 'Floorplan' },
];

export function DesignTabs({ page }: { page: PageId }) {
  return <WorkspaceTabs label="Design views" current={page} items={DESIGN_TABS} />;
}

type StageState = 'done' | 'current' | 'pending' | 'blocked';

type Stage = {
  key: string;
  label: string;
  state: StageState;
  detail: string;
  page: PageId;
};

function stateTone(state: StageState): 'green' | 'blue' | 'amber' | 'red' | 'neutral' {
  if (state === 'done') return 'green';
  if (state === 'current') return 'blue';
  if (state === 'blocked') return 'red';
  return 'amber';
}

function stateLabel(state: StageState) {
  return state === 'done' ? 'done' : state === 'current' ? 'next' : state === 'blocked' ? 'blocked' : 'waiting';
}

/** The stages every Design page feeds. One status vocabulary so the page a
 *  user is on always says what it contributes to the revision. */
function stagesFor(data: LoadedProject): Stage[] {
  const dirty = !!data.draftMeta?.dirty;
  const active = data.detail.active_revision_id;
  const compiled = data.compileResult?.revision_id ?? null;
  const compiledMatches = !!active && compiled === active && !dirty;
  const runs = data.detail.runs ?? [];
  const stale = runs.filter(run => run.revision_id !== active).length;
  const certificate = data.compileResult?.certificate?.overall ?? null;
  const routing = (data.compileResult?.groups?.routing ?? {}) as { entries?: unknown[]; entry_count?: number; routing_classes?: string[] };
  const decode = (data.compileResult?.groups?.address_decode ?? {}) as { rows?: unknown[] };
  const routeCount = typeof routing.entry_count === 'number' ? routing.entry_count : Array.isArray(routing.entries) ? routing.entries.length : 0;
  const decodeCount = Array.isArray(decode.rows) ? decode.rows.length : 0;
  return [
    {
      key: 'draft', label: '1 · Draft intent',
      state: dirty || !active ? 'current' : 'done',
      detail: dirty ? 'Saved draft differs from the active revision' : active ? 'Draft matches the active revision' : 'No draft compiled yet',
      page: 'design/agent-map',
    },
    {
      key: 'compile', label: '2 · Compile',
      state: dirty ? 'pending' : active ? 'done' : 'current',
      detail: active ? `${active}${certificate ? ` · ${certificate}` : ' · no certificate served'}` : 'No compiled revision',
      page: 'workloads/workflow',
    },
    {
      key: 'derive', label: '3 · Derive',
      state: compiledMatches ? 'done' : 'pending',
      detail: compiledMatches ? `${routeCount} route entr${routeCount === 1 ? 'y' : 'ies'} · ${decodeCount} decode row${decodeCount === 1 ? '' : 's'}` : compiled ? `Artifacts belong to ${compiled}` : 'No compile result',
      page: 'design/mapping',
    },
    {
      key: 'measure', label: '4 · Measure',
      state: runs.length ? (stale ? 'current' : 'done') : 'pending',
      detail: runs.length ? `${runs.length} run${runs.length === 1 ? '' : 's'}${stale ? ` · ${stale} on another revision` : ''}` : 'No evaluation run',
      page: 'analysis/summary',
    },
    {
      key: 'deliver', label: '5 · Collateral',
      state: compiledMatches ? 'current' : 'pending',
      detail: compiledMatches ? 'UVM available · RTL preview depends on VC scheme' : 'UVM · RTL preview · source inventory',
      page: 'design/system',
    },
  ];
}

/** The single compile action for the page heading on every Design route.
 *  It compiles the saved draft; the page that owns an edit saves it first. */
export function DesignHeaderStatus({ data }: { data: LoadedProject | null }) {
  const { reload } = useProject();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (!data) return null;
  const token = data.draftMeta?.revisionToken;
  const canCompile = !!token && !busy;
  const compile = async () => {
    setBusy(true); setError('');
    try {
      await gateway.compileProject(data.detail.project.project_id, token);
      reload();
    } catch (caught) {
      setError(gatewayReason(caught));
    } finally {
      setBusy(false);
    }
  };
  return <div className="design-header-status">
    <Button onClick={compile} disabled={!canCompile}
      title={!token ? 'No saved draft to compile.' : 'Compile the saved draft into a revision.'}>
      {busy ? 'Compiling…' : 'Compile draft'}
    </Button>
    {error && <span className="error-text" role="alert">{error}</span>}
  </div>;
}

export function DesignFlowRail({ data, page }: { data: LoadedProject; page?: PageId }) {
  const stages = stagesFor(data);
  return <Section title="Design flow" actions={<Badge tone={data.draftMeta?.dirty ? 'amber' : 'green'}>{data.draftMeta?.dirty ? 'compile required' : 'revision current'}</Badge>}>
    <p className="meta-line">Every Design page edits one draft. The draft becomes evidence only after it is saved and compiled; runs, routes, decode and collateral then name the revision they came from.</p>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 10, margin: '4px 0 12px' }}>
      {stages.map((stage, index) => <div key={stage.key} className="design-handoff-step" aria-current={page === stage.page ? 'step' : undefined} style={page === stage.page ? { borderColor: 'var(--accent)' } : undefined}>
        <span>{index > 0 && <span aria-hidden="true" style={{ color: 'var(--muted)' }}>→ </span>}{stage.label} <Badge tone={stateTone(stage.state)}>{stateLabel(stage.state)}</Badge></span>
        <strong>{stage.detail}</strong>
        <small><a href={`#/${stage.page}`}>Open {stage.page}</a></small>
      </div>)}
    </div>
  </Section>;
}

/** What the current draft state actually changes downstream. */
export function DesignConsequences({ data }: { data: LoadedProject }) {
  const projectId = data.detail.project.project_id;
  const revisionId = data.detail.active_revision_id;
  const dirty = !!data.draftMeta?.dirty;
  const compiled = data.compileResult?.revision_id ?? null;
  const compiledMatches = !!revisionId && compiled === revisionId && !dirty;
  const certificate = data.compileResult?.certificate?.overall ?? null;
  const runs = data.detail.runs ?? [];
  const staleRuns = runs.filter(run => run.revision_id !== revisionId);
  const [obligations, setObligations] = useState<Obligations | null>(null);
  const [obligationsError, setObligationsError] = useState('');
  const [preflight, setPreflight] = useState<PreflightView | null>(null);
  const [preflightError, setPreflightError] = useState('');

  useEffect(() => {
    let live = true;
    setObligationsError('');
    gateway.obligations(projectId)
      .then(value => { if (live) setObligations(value); })
      .catch(failure => { if (live) setObligationsError(gatewayReason(failure)); });
    return () => { live = false; };
  }, [projectId, revisionId]);

  useEffect(() => {
    if (!revisionId) return;
    let live = true;
    setPreflightError('');
    gateway.preflight(revisionId)
      .then(value => { if (live) setPreflight(value); })
      .catch(failure => { if (live) setPreflightError(gatewayReason(failure)); });
    return () => { live = false; };
  }, [revisionId, compiled]);

  const refused = preflight ? preflight.gates.filter(gate => gate.state !== 'READY' && gate.state !== 'QUALIFIED') : [];
  const blocking = obligations?.counts?.blocking_open ?? 0;

  return <Section title="Consequences of the current state" actions={<Badge tone={dirty || staleRuns.length ? 'amber' : compiledMatches ? 'green' : 'neutral'}>{dirty ? 'draft not compiled' : staleRuns.length ? `${staleRuns.length} stale run${staleRuns.length === 1 ? '' : 's'}` : compiledMatches ? 'current' : 'no compiled revision'}</Badge>}>
    <div className="table-scroll"><table>
      <thead><tr><th>Change</th><th>Effect</th><th>Next</th></tr></thead>
      <tbody>
        <tr>
          <th>Draft intent</th>
          <td>{dirty ? `The active revision ${revisionId ?? '—'} still describes the previous intent. Nothing below uses these edits until they are saved and compiled.` : 'No unsaved design edits.'}</td>
          <td><PageLink page="design/agent-map">Edit draft</PageLink></td>
        </tr>
        <tr>
          <th>Compile</th>
          <td>{compiledMatches ? `Artifacts belong to ${revisionId}${certificate ? ` · certificate ${certificate}` : ''}.` : compiled ? `The compile result belongs to ${compiled}, not the active revision ${revisionId ?? '—'}.` : 'No compile result exists for this revision.'}</td>
          <td><PageLink page="workloads/workflow">Compile</PageLink></td>
        </tr>
        <tr>
          <th>Derived facts</th>
          <td>{compiledMatches ? 'Routes, address decode and endpoint seats come from the active revision.' : 'Route, decode and seat surfaces are showing an older revision or nothing. Do not read them as facts about the draft.'}</td>
          <td><PageLink page="design/mapping">Inspect route</PageLink></td>
        </tr>
        <tr>
          <th>Measurements</th>
          <td>{staleRuns.length ? `${staleRuns.length} run${staleRuns.length === 1 ? ' was' : 's were'} measured on another revision and are not evidence for this design.` : runs.length ? 'Runs match the active revision.' : 'No evaluation has measured this design.'}</td>
          <td><PageLink page="analysis/summary">Open analysis</PageLink></td>
        </tr>
        <tr>
          <th>Preflight</th>
          <td>{preflightError ? `Unavailable: ${preflightError}` : preflight ? (preflight.ready ? 'Every delivery gate is ready on the active revision.' : `${refused.length} gate${refused.length === 1 ? '' : 's'} refuse execution: ${refused.map(gate => `${gate.gate} (${gate.state})`).join(', ') || 'no gate detail'}.`) : 'Reading the active revision.'}</td>
          <td><PageLink page="design/system">Inspect gates</PageLink></td>
        </tr>
        <tr>
          <th>Obligations</th>
          <td>{obligationsError ? `Unavailable: ${obligationsError}` : obligations ? (blocking ? `${blocking} blocking obligation${blocking === 1 ? '' : 's'} remain open.` : 'No blocking obligations are recorded.') : 'Reading the obligation register.'}</td>
          <td><PageLink page="verify/obligations">Open obligations</PageLink></td>
        </tr>
        <tr>
          <th>Collateral</th>
          <td>UVM is generated from the compiled bundle; RTL preview support depends on the selected VC scheme. Neither is a simulation result or qualification.</td>
          <td><PageLink page="design/system">Generate collateral</PageLink></td>
        </tr>
      </tbody>
    </table></div>
  </Section>;
}

const SURFACES: { page: PageId; label: string; edits: string; effect: string }[] = [
  { page: 'design/fabric-topology', label: 'Fabric topology', edits: 'Fabric graph, explicit links, buffer depth', effect: 'Saves the draft; depth and graph edits recompile a revision.' },
  { page: 'design/system', label: 'System diagram', edits: 'Nothing by itself', effect: 'Reads composition and builds UVM/preflight from the compiled revision.' },
  { page: 'design/catalog', label: 'Agent catalog (legacy)', edits: 'Agent groups (fixture only)', effect: 'Redirects to Agents when a live project is loaded; the fixture keeps the sample add form.' },
  { page: 'design/endpoints', label: 'Hardware endpoints', edits: 'Nothing in live mode', effect: 'Seats are compiler-derived; the page shows the attachment the revision actually produced.' },
  { page: 'design/mapping', label: 'Initiator–target mapping', edits: 'Nothing in live mode', effect: 'Walks the frozen compile result; permission is not in the compile schema.' },
  { page: 'design/agent-map', label: 'Agents', edits: 'Agent fields, interface, address windows and reachability', effect: 'Saves and compiles the real draft; schema checks run before either.' },
  { page: 'design/addresses', label: 'Addresses', edits: 'Address windows', effect: 'Saves and compiles; resolved decode and permission cells come back from the server.' },
  { page: 'design/domains', label: 'Domains', edits: 'Declared clock domains', effect: 'Saves and compiles a new revision; CDC and timing remain unanalysed.' },
  { page: 'design/placement', label: 'Floorplan', edits: 'Floorplan geometry and wire rule', effect: 'Writes the gateway floorplan and derives area and link delay.' },
];

/** Hidden Design status page: the flow between the six strip surfaces and the
 *  read-only context routes. */
export function DesignFlowPage({ data, state }: { data: LoadedProject | null; state?: PrototypeState }) {
  if (!data) {
    return <div className="view-main">
      <Section title="Design flow" actions={<Badge tone="amber">Local sample</Badge>}>
        <p>The local sample keeps every edit in browser state. There is no compile, revision, derived route, run or collateral to show, so consequences stop at this draft. Load a gateway project to make the same edits produce revisions and evidence.</p>
        <Properties rows={[
          ['Draft', state ? `${state.draft.endpoints.length} endpoints · ${state.draft.regions.length} address regions · ${state.draft.mappings ? Object.keys(state.draft.mappings).length : 0} mapping entries` : 'Local draft'],
          ['Compile', 'Not available without a gateway project'],
          ['Derived facts', 'Authored fixture only'],
          ['Collateral', 'Not available in local mode'],
        ]} />
        <div className="actions"><PageLink page="shared/projects" primary>Load a gateway project</PageLink><PageLink page="design/system">Inspect the sample</PageLink></div>
      </Section>
      <Section title="What each design page changes">
        <div className="table-scroll"><table><thead><tr><th>Page</th><th>Edits</th><th>Effect with a project</th></tr></thead><tbody>
          {SURFACES.map(surface => <tr key={surface.page}><th><a href={`#/${surface.page}`}>{surface.label}</a></th><td>{surface.edits}</td><td>{surface.effect}</td></tr>)}
        </tbody></table></div>
      </Section>
    </div>;
  }
  return <div className="view-main">
    <div className="toolbar">
      <span className="mono fabric-counts">{data.detail.project.name} · {data.detail.active_revision_id ?? 'no revision'} · {data.draftMeta?.dirty ? 'draft differs' : 'draft matches'}</span>
      <PageLink page="workloads/workflow">Open project workflow</PageLink>
    </div>
    <DesignFlowRail data={data} page="design/flow" />
    <DesignConsequences data={data} />
    <Section title="What each design page changes">
      <div className="table-scroll"><table><thead><tr><th>Page</th><th>Edits</th><th>Effect with a project</th></tr></thead><tbody>
        {SURFACES.map(surface => <tr key={surface.page}><th><a href={`#/${surface.page}`}>{surface.label}</a></th><td>{surface.edits}</td><td>{surface.effect}</td></tr>)}
      </tbody></table></div>
    </Section>
  </div>;
}

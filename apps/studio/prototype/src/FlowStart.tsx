import { useEffect, useState } from 'react';
import { GATEWAY_START, gateway, gatewayReason, type WorkloadCatalogEntry } from './gateway';
import { useProject } from './project';
import type { PageId } from './model';
import { Badge, Button, Empty, Field, JsonView, Notice, PageLink, Properties } from './ui';

const worldSize = (entry: WorkloadCatalogEntry) => {
  const p = entry.parallelism ?? {};
  return (p.tp ?? 1) * (p.dp ?? 1) * (p.ep ?? 1) * (p.pp ?? 1);
};
const readinessTone = (entry: WorkloadCatalogEntry): 'green' | 'amber' | 'red' =>
  entry.evaluation_supported === false ? 'red' : entry.evaluation_readiness === 'READY' ? 'green' : 'amber';
const bytes = (value?: number | null) => value == null ? '—' : value >= 1e6 ? `${(value / 1e6).toFixed(2)} MB` : value >= 1e3 ? `${(value / 1e3).toFixed(1)} kB` : `${value} B`;
type TemplateRequirement = { traffic_class?: string; qos_class?: string; latency_ceiling_cycles?: number | null; bandwidth_floor_gbps?: number | null; binding?: boolean };
const requirementsOf = (entry: WorkloadCatalogEntry): TemplateRequirement[] =>
  (entry.request as { requirements?: TemplateRequirement[] } | undefined)?.requirements ?? [];
const stageCount = (entry: WorkloadCatalogEntry): number =>
  ((entry.request as { compute?: { stages?: unknown[] } } | undefined)?.compute?.stages ?? []).length;

/** The definition body is mounted only when the fold is open. React renders
 *  every child of a closed <details>, which previously put all 21 request trees
 *  into the page before the operator opened any of them. */
function WorkloadDefinition({ entry }: { entry: WorkloadCatalogEntry }) {
  const [open, setOpen] = useState(false);
  const ready = entry.evaluation_readiness ?? 'not reported';
  const requirements = requirementsOf(entry);
  const stages = stageCount(entry);
  return <details className="flow-workload-definition" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Definition <span className="mono" title={entry.source ?? 'source not reported'}>{entry.source ?? 'source not reported'}</span></summary>
    {open && <>
      <dl className="flow-workload-def">
        <div><dt>Model</dt><dd>{entry.model_name ?? 'not named'} · {entry.model_family ?? 'family not reported'}</dd></div>
        <div><dt>Parallelism</dt><dd>TP{entry.parallelism?.tp ?? 1} · DP{entry.parallelism?.dp ?? 1} · EP{entry.parallelism?.ep ?? 1} · PP{entry.parallelism?.pp ?? 1} <small>{worldSize(entry)} ranks</small></dd></div>
        <div><dt>Collectives</dt><dd>{entry.collectives?.length
          ? entry.collectives.map((collective, index) => <span key={index} className="flow-def-line">{collective.kind ?? 'traffic'} {collective.dimension ?? ''} · {bytes(collective.payload_bytes)} · {collective.traffic_class ?? 'unclassified'}</span>)
          : 'None declared'}</dd></div>
        <div><dt>Agents</dt><dd>{entry.agents?.length ? entry.agents.map((agent, index) => <span key={index} className="flow-def-line">{agent.count ?? 0} × {agent.kind ?? 'agent'}</span>) : 'None declared'}</dd></div>
        <div><dt>Requirements</dt><dd>{requirements.length ? requirements.map((requirement, index) => <span key={index} className="flow-def-line">{requirement.traffic_class ?? 'class'} · {requirement.qos_class ?? 'QoS not stated'}{requirement.latency_ceiling_cycles != null ? ` · ≤ ${requirement.latency_ceiling_cycles} cyc` : ''}{requirement.bandwidth_floor_gbps != null ? ` · ≥ ${requirement.bandwidth_floor_gbps} GB/s` : ''}{requirement.binding === false ? ' · non-binding' : ''}</span>) : 'None declared'}</dd></div>
        <div><dt>Compute stages</dt><dd>{stages ? `${stages} declared` : 'None declared'}</dd></div>
        <div><dt>NOC defaults</dt><dd>{entry.noc?.topology_family ?? 'not declared'} · {entry.noc?.link_width ? `${entry.noc.link_width}-bit links` : 'link width not declared'}{entry.noc?.concentration ? ` · concentration ${entry.noc.concentration}` : ''} <small>template values, not a fabric choice</small></dd></div>
        <div><dt>Evaluation</dt><dd>{entry.evaluation_support ?? 'support not reported'} · {ready}{entry.evaluation_note ? ` · ${entry.evaluation_note}` : ''}{entry.evaluation_domain ? ` · ${entry.evaluation_domain}` : ''}</dd></div>
      </dl>
      <Properties rows={[
        ['Source', <span className="mono">{entry.source ?? 'not reported'}</span>],
        ['Content digest', <span className="mono">{entry.content_digest ?? 'not reported'}</span>],
        ['Evaluation supported', entry.evaluation_supported === undefined ? 'not reported' : entry.evaluation_supported ? 'Yes' : 'No'],
      ]} />
      <JsonView name="Request document" value={entry.request ?? entry} hint="Expand a branch to read the compiler-facing definition. No values are derived here." />
    </>}
  </details>;
}

/**
 * The first step of the guided flow. A workload template is the input; its
 * definition is laid out before the project is created. The fabric is chosen
 * later, from the declared endpoint demand rather than a fabric preset.
 */
export function FlowStart({ navigate, notify }: { navigate: (page: PageId) => void; notify: (message: string) => void }) {
  const { health, listPhase, listError, load, refreshList, project } = useProject();
  const [workloads, setWorkloads] = useState<WorkloadCatalogEntry[]>([]);
  const [catalogPhase, setCatalogPhase] = useState<'loading' | 'ready' | 'error'>('loading');
  const [catalogError, setCatalogError] = useState('');
  const [query, setQuery] = useState('');
  const [family, setFamily] = useState('all');
  const [supportedOnly, setSupportedOnly] = useState(false);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState('');
  const [createError, setCreateError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const current = project.phase === 'loaded' ? project.data : null;

  useEffect(() => {
    let live = true;
    setCatalogPhase('loading'); setCatalogError('');
    gateway.workloads()
      .then(rows => {
        if (!live) return;
        setWorkloads(rows);
        setCatalogPhase('ready');
      })
      .catch(error => {
        if (!live) return;
        setWorkloads([]);
        setCatalogError(gatewayReason(error));
        setCatalogPhase('error');
      });
    return () => { live = false; };
  }, [refresh]);

  const createFromWorkload = async (entry: WorkloadCatalogEntry) => {
    if (busy) return;
    setBusy(`workload:${entry.workload_id}`); setCreateError('');
    try {
      const projectName = name.trim() || entry.display_name || entry.workload_id;
      const detail = await gateway.createProject(projectName, entry.workload_id);
      load(detail.project.project_id);
      notify(`Created ${detail.project.name} from workload template ${entry.display_name ?? entry.workload_id}. Choose and tune the fabric next.`);
      navigate('flow/tune');
    } catch (error) {
      setCreateError(gatewayReason(error));
    } finally {
      setBusy('');
    }
  };

  const offline = listPhase === 'offline' || catalogPhase === 'error';
  const connectedBackends = health ? Object.entries(health.backends).filter(([, value]) => value.binary_present).map(([key]) => key) : [];
  const families = [...new Set(workloads.map(entry => entry.model_family).filter((value): value is string => Boolean(value)))].sort();
  const needle = query.trim().toLowerCase();
  const visible = workloads
    .filter(entry => family === 'all' || entry.model_family === family)
    .filter(entry => !supportedOnly || entry.evaluation_supported !== false)
    .filter(entry => !needle || `${entry.display_name ?? ''} ${entry.workload_id} ${entry.description ?? ''} ${entry.model_family ?? ''} ${entry.model_name ?? ''}`.toLowerCase().includes(needle))
    .sort((a, b) => (a.display_name ?? a.workload_id).localeCompare(b.display_name ?? b.workload_id));

  return <>
    <div className="flow-start-head">
      <div className="flow-start-counts">
        {catalogPhase === 'loading'
          ? <Badge tone="blue">Reading templates…</Badge>
          : <Badge>{visible.length} of {workloads.length} {workloads.length === 1 ? 'template' : 'templates'}</Badge>}
        <Badge tone={connectedBackends.length ? 'green' : 'amber'}>{connectedBackends.length ? `${connectedBackends.length} backend${connectedBackends.length === 1 ? '' : 's'} present` : 'No backend reported'}</Badge>
      </div>
      <div className="actions flow-start-actions">
        {current && <PageLink page="flow/tune" primary>Continue {current.detail.project.name}</PageLink>}
        <PageLink page="shared/projects">Open project</PageLink>
        <Button onClick={() => { refreshList(); setRefresh(value => value + 1); }}>Refresh</Button>
      </div>
    </div>
    <p className="meta-line flow-start-intro">Pick the workload you serve. Its definition is shown before a project is created; the fabric is chosen later from the declared endpoint demand.</p>

    {offline && <Notice tone="amber">
      <strong>{listPhase === 'offline' ? 'The project gateway is not reachable.' : 'The workload catalog could not be read.'}</strong>{' '}
      {listError || catalogError} {health ? '' : <>Start it with <code>{GATEWAY_START}</code>.</>}
      <div className="toolbar"><Button onClick={() => { refreshList(); setRefresh(value => value + 1); }}>Retry</Button></div>
    </Notice>}

    <div className="flow-start-filters">
      <Field label="Search">
        <input value={query} placeholder="Model, family or identifier" onChange={event => setQuery(event.target.value)} />
      </Field>
      <Field label="Model family">
        <select value={family} onChange={event => setFamily(event.target.value)}>
          <option value="all">All families</option>
          {families.map(value => <option key={value} value={value}>{value}</option>)}
        </select>
      </Field>
      <Field label="Project name">
        <input value={name} maxLength={120} placeholder={busy.startsWith('workload:') ? 'Creating…' : 'Defaults to the template name'} onChange={event => setName(event.target.value)} />
      </Field>
      <label className="check-chip flow-ready-filter" title="Only workloads the backend can evaluate"><input type="checkbox" checked={supportedOnly} onChange={event => setSupportedOnly(event.target.checked)} />Backend-evaluable</label>
      {(query || family !== 'all' || supportedOnly) && <Button className="flow-clear-filters" onClick={() => { setQuery(''); setFamily('all'); setSupportedOnly(false); }}>Clear</Button>}
    </div>

    {createError && <Notice tone="red">{createError}</Notice>}

    {catalogPhase === 'loading'
      ? <p role="status">Reading workload templates…</p>
      : workloads.length
        ? visible.length
          ? <div className="flow-workload-grid">{visible.map(entry => {
            const ready = entry.evaluation_readiness ?? 'not reported';
            const creating = busy === `workload:${entry.workload_id}`;
            const requirements = requirementsOf(entry);
            const stages = stageCount(entry);
            const agentCount = (entry.agents ?? []).reduce((count, agent) => count + (agent.count ?? 0), 0);
            return <article className="flow-workload-card" key={entry.workload_id} data-readiness={readinessTone(entry)}>
              <div className="flow-workload-head">
                <div><h3>{entry.display_name ?? entry.workload_id}</h3><span className="mono">{entry.workload_id}</span></div>
                <Badge tone={readinessTone(entry)}>{ready}</Badge>
              </div>
              <p>{entry.description ?? 'No description supplied by the registry.'}</p>
              <div className="flow-workload-facts" aria-label="Workload summary">
                <span><strong>TP{entry.parallelism?.tp ?? 1} · DP{entry.parallelism?.dp ?? 1} · EP{entry.parallelism?.ep ?? 1} · PP{entry.parallelism?.pp ?? 1}</strong></span>
                <span><strong>{worldSize(entry)}</strong> ranks</span>
                <span><strong>{entry.collectives?.length ?? 0}</strong> collectives</span>
                <span><strong>{agentCount}</strong> agents</span>
                <span><strong>{requirements.length}</strong> requirements</span>
                <span><strong>{stages}</strong> compute stages</span>
              </div>
              {entry.evaluation_note && <p className="flow-workload-note">{entry.evaluation_note}</p>}
              <WorkloadDefinition entry={entry} />
              <div className="flow-workload-actions">
                <Button primary disabled={!!busy} onClick={() => createFromWorkload(entry)}>{creating ? 'Creating…' : 'Use this workload'}</Button>
              </div>
            </article>;
          })}</div>
          : <Empty title="No workloads match this filter">Clear the search, family filter or evaluation filter to see more templates.</Empty>
        : <Empty title="No workload templates available">The gateway returned no workload registry entries. Check the catalog connection or add a template to the workload registry.</Empty>}
  </>;
}

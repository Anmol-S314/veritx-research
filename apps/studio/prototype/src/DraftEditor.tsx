import { useEffect, useMemo, useState } from 'react';
import { gateway, gatewayReason } from './gateway';
import type { LoadedProject } from './project';
import { useProject } from './project';
import { Button, Notice, Properties } from './ui';

type Draft = Record<string, any>;


const FAMILIES: Record<string, { fields: string[]; enums?: Record<string, string[]>; defaults?: Record<string, number | string> }> = {
  mesh: { fields: ['side_length', 'concentration'], defaults: { side_length: 3, concentration: 1 } },
  concentrated_mesh: { fields: ['side_length', 'concentration'], defaults: { side_length: 2, concentration: 4 } },
  torus: { fields: ['side_length', 'concentration'], defaults: { side_length: 3, concentration: 1 } },
  flatfly: { fields: ['radix_per_dimension', 'dimension_count', 'concentration'], defaults: { radix_per_dimension: 4, dimension_count: 2, concentration: 1 } },
  fattree: { fields: ['switch_radix', 'level_count'], defaults: { switch_radix: 4, level_count: 2 } },
  gec: { fields: ['mode', 'grid_side_length', 'concentration'], enums: { mode: ['mesh', 'express', 'multidrop', 'hybrid'] }, defaults: { mode: 'mesh', grid_side_length: 4, concentration: 1 } },
};
const AGENT_KINDS = ['compute_tile', 'hbm_controller', 'nic'];
const COLLECTIVE_KINDS = ['allreduce', 'allgather', 'reducescatter', 'broadcast', 'alltoall'];
const DIMENSIONS = ['TP', 'DP', 'EP', 'PP', 'GLOBAL'];
const QOS_CLASSES = ['latency_critical', 'bandwidth', 'best_effort'];
const DEP_KINDS = ['blocking', 'ordering', 'independent'];
const APPLICABILITY = ['APPLICABLE', 'NOT_APPLICABLE', 'NOT_EVALUATED'];
const GRAPH_KINDS = ['custom', 'anynet'];

function pickFamily(kind: string, previous: Draft): Draft {
  const spec = FAMILIES[kind];
  if (!spec) return { kind };
  const next: Draft = { kind, ...(spec.defaults ?? {}) };
  for (const field of spec.fields) if (previous[field] !== undefined) next[field] = previous[field];
  return next;
}

const numberField = (label: string, value: number | null | undefined, onChange: (next: number) => void, hint?: string) => (
  <label className="field" key={label}><span>{label}</span>
    <input type="number" value={value ?? ''} onChange={e => { const raw = e.target.value; if (raw === '') return; const next = Number(raw); if (Number.isFinite(next)) onChange(next); }} />
    {hint && <small>{hint}</small>}
  </label>
);

const reqInt = (value: string, label: string, minimum = 0) => {
  const next = Number(value);
  if (value.trim() === '' || !Number.isSafeInteger(next) || next < minimum) throw new Error(`${label} must be an integer >= ${minimum}.`);
  return next;
};
const optNumber = (value: string, label: string) => {
  if (value.trim() === '') return null;
  const next = Number(value);
  if (!Number.isFinite(next)) throw new Error(`${label} must be a number or empty.`);
  return next;
};
const textRow = (label: string, value: string, onChange: (next: string) => void) => (
  <label className="field"><span>{label}</span><input value={value} onChange={e => onChange(e.target.value)} /></label>
);

export function DraftEditor({ project }: { project: LoadedProject }) {
  const { reload } = useProject();
  const draft = useMemo(() => (project.request as Draft | null) ?? null, [project.request]);
  const [topology, setTopology] = useState<Draft>({});
  const [physical, setPhysical] = useState<Draft>({});
  const [noc, setNoc] = useState<Draft>({});
  const [agents, setAgents] = useState<Draft[]>([]);
  const [ranges, setRanges] = useState<Draft[]>([]);
  const [requirements, setRequirements] = useState<Draft[]>([]);
  const [dependencies, setDependencies] = useState<Draft[]>([]);
  const [collectives, setCollectives] = useState<Draft[]>([]);
  const [graph, setGraph] = useState<Draft>({ name: '', kind: 'custom', nodes: '', links: '', bandwidth: '', latency: '' });
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState<'preview' | 'save' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ routers?: number; channels?: number; hash?: string } | null>(null);
  const [canonical, setCanonical] = useState<Draft | null>(null);
  const [advanced, setAdvanced] = useState('{}');

  useEffect(() => {
    if (!draft) return;
    // Keep the family the user picked: a reload may return a draft whose topology
    // block is migrated (no `kind` key) and must not silently revert the choice.
    setTopology(previous => {
      const stored = draft.topology ? { ...draft.topology } : {};
      const kind = (stored.kind as string | undefined) ?? previous.kind ?? (draft.noc_config?.topology_family as string | undefined) ?? '';
      return kind ? { kind, ...stored } : stored;
    });
    setPhysical({ ...(draft.physical ?? {}) });
    // v2 drafts keep NOC settings in `noc_config`; v4 renamed it to `noc_controls`.
    setNoc({ ...((draft.noc_controls ?? draft.noc_config) ?? {}) });
    setAgents((draft.agents ?? []).map((a: Draft) => ({ ...a })));
    setRanges(((draft.address_map?.ranges ?? []) as Draft[]).map(r => ({
      name: r.name ?? '', base: String(r.base ?? ''), size: String(r.size ?? r.size_bytes ?? ''),
      target: String(r.target_agent_idx ?? (typeof r.target === 'number' ? r.target : 0)),
    })));
    setRequirements(((draft.requirements ?? []) as Draft[]).map(r => ({
      traffic_class: r.traffic_class ?? '', qos_class: r.qos_class ?? 'best_effort',
      latency_ceiling_cycles: r.latency_ceiling_cycles ?? '', bandwidth_floor_gbps: r.bandwidth_floor_gbps ?? '',
      binding: r.binding ?? false, applicability: r.applicability ?? 'APPLICABLE',
    })));
    setDependencies(((draft.dependencies ?? []) as Draft[]).map(d => ({
      source: d.source ?? d.from ?? '', target: d.target ?? d.to ?? '', kind: d.kind ?? 'blocking',
    })));
    setCollectives((((draft.workload as Draft | undefined)?.collectives ?? []) as Draft[]).map(c => ({
      kind: c.kind ?? 'allreduce', dimension: c.dimension ?? 'TP', payload_bytes: String(c.payload_bytes ?? ''),
      traffic_class: c.traffic_class ?? '', source_rank: c.source_rank ?? '',
    })));
    const stored = (draft.topology as Draft | undefined)?.graph ?? draft.explicit_topology;
    if (stored) setGraph({
      name: stored.name ?? '', kind: stored.kind ?? 'custom', nodes: String(stored.nodes ?? ''),
      links: ((stored.links ?? []) as unknown[]).map(l => Array.isArray(l) ? `${l[0]} ${l[1]}` : String(l)).join('\n'),
      bandwidth: String(stored.link_attrs?.bandwidth_GBs ?? ''), latency: String(stored.link_attrs?.latency_ns ?? ''),
    });
    setPreview(null); setError(null); setCanonical(null); setTouched(false);
    setAdvanced(JSON.stringify(draft.compute !== undefined ? { compute: draft.compute } : {}, null, 2));
  }, [draft]);

  if (!draft) return <div className="section"><div className="section-heading"><h2>Draft editor</h2></div><Notice tone="amber">No draft request to edit.</Notice></div>;

  const nocKey = draft.noc_controls !== undefined ? 'noc_controls' : 'noc_config';
  const isExplicit = topology.kind === 'explicit';
  // v4 carries the graph in `topology.graph`; v3 carries it in `explicit_topology`.
  const explicitKey = draft.topology !== undefined || (draft.schema_version ?? 4) >= 4 ? 'topology' : 'explicit_topology';

  const buildGraph = (): Draft => {
    if (!graph.name.trim()) throw new Error('Explicit graph needs a name.');
    if (!GRAPH_KINDS.includes(graph.kind)) throw new Error('Explicit graph kind must be custom or anynet.');
    const nodes = reqInt(String(graph.nodes), 'Explicit graph nodes', 1);
    const links = String(graph.links).split('\n').map(line => line.trim()).filter(Boolean).map((line, i) => {
      const parts = line.split(/\s+/);
      if (parts.length !== 2) throw new Error(`Explicit graph link ${i + 1}: expected 'src dst'.`);
      return [reqInt(parts[0], `Explicit graph link ${i + 1} source`), reqInt(parts[1], `Explicit graph link ${i + 1} destination`)];
    });
    if (!links.length) throw new Error('Explicit custom/anynet graphs require at least one link.');
    const bandwidth = Number(graph.bandwidth), latency = Number(graph.latency);
    if (!Number.isFinite(bandwidth) || bandwidth <= 0 || !Number.isFinite(latency) || latency <= 0) throw new Error('Explicit graph link_attrs needs positive bandwidth_GBs and latency_ns.');
    return { name: graph.name.trim(), kind: graph.kind, nodes, links, link_attrs: { bandwidth_GBs: bandwidth, latency_ns: latency } };
  };

  const merged = (withTopology: boolean): Draft => {
    if (advanced.length > 262144) throw new Error('Advanced compute JSON exceeds 256 KiB.');
    const extra = advanced.trim() ? JSON.parse(advanced) : {};
    if (!extra || typeof extra !== 'object' || Array.isArray(extra) || Object.keys(extra).some(k => k !== 'compute')) throw new Error('Advanced JSON supports only a compute object; address ranges, collectives, requirements, dependencies, and explicit graphs have structured controls above.');
    const builtRanges = ranges.filter(r => r.name.trim() || String(r.base).trim() || String(r.size).trim()).map((r, i) => {
      if (!r.name.trim()) throw new Error(`Address range ${i + 1}: name is required.`);
      return { name: r.name.trim(), base: reqInt(String(r.base), `Address range ${i + 1} base`), size: reqInt(String(r.size), `Address range ${i + 1} size`, 1), target_agent_idx: reqInt(String(r.target), `Address range ${i + 1} target`) };
    });
    const builtRequirements = requirements.filter(r => r.traffic_class.trim() || r.qos_class).map((r, i) => {
      if (!QOS_CLASSES.includes(r.qos_class)) throw new Error(`Requirement ${i + 1}: unknown QoS class.`);
      if (!APPLICABILITY.includes(r.applicability)) throw new Error(`Requirement ${i + 1}: unknown applicability.`);
      const doc: Draft = { traffic_class: r.traffic_class.trim() || null, qos_class: r.qos_class, latency_ceiling_cycles: optNumber(String(r.latency_ceiling_cycles ?? ''), `Requirement ${i + 1} latency ceiling`), bandwidth_floor_gbps: optNumber(String(r.bandwidth_floor_gbps ?? ''), `Requirement ${i + 1} bandwidth floor`), binding: !!r.binding };
      if (r.applicability !== 'APPLICABLE') doc.applicability = r.applicability;
      return doc;
    });
    const builtDependencies = dependencies.filter(d => d.source.trim() || d.target.trim()).map((d, i) => {
      if (!d.source.trim() || !d.target.trim()) throw new Error(`Dependency ${i + 1}: source and target are required.`);
      if (!DEP_KINDS.includes(d.kind)) throw new Error(`Dependency ${i + 1}: kind must be blocking, ordering, or independent.`);
      return { source: d.source.trim(), target: d.target.trim(), kind: d.kind };
    });
    const builtCollectives = collectives.filter(c => c.kind).map((c, i) => {
      if (!COLLECTIVE_KINDS.includes(c.kind)) throw new Error(`Collective ${i + 1}: unknown kind.`);
      if (!DIMENSIONS.includes(c.dimension)) throw new Error(`Collective ${i + 1}: dimension must be TP, DP, EP, PP, or GLOBAL.`);
      if (!c.traffic_class.trim()) throw new Error(`Collective ${i + 1}: traffic class is required.`);
      return { kind: c.kind, dimension: c.dimension, payload_bytes: reqInt(String(c.payload_bytes), `Collective ${i + 1} payload bytes`, 1), traffic_class: c.traffic_class.trim(), source_rank: String(c.source_rank ?? '').trim() === '' ? null : reqInt(String(c.source_rank), `Collective ${i + 1} source rank`) };
    });
    const base: Draft = { ...draft, physical, agents, [nocKey]: noc };
    if (draft.address_map !== undefined || builtRanges.length) base.address_map = { ranges: builtRanges };
    if (draft.requirements !== undefined || builtRequirements.length) base.requirements = builtRequirements;
    if (draft.dependencies !== undefined || builtDependencies.length) base.dependencies = builtDependencies;
    if (draft.workload !== undefined || builtCollectives.length) base.workload = { ...(draft.workload ?? {}), collectives: builtCollectives };
    if (extra.compute !== undefined) base.compute = extra.compute;
    if (isExplicit) {
      const graphDoc = buildGraph();
      if (explicitKey === 'topology') base.topology = { kind: 'explicit', graph: graphDoc };
      else base.explicit_topology = graphDoc;
    } else if (withTopology && draft.topology !== undefined) base.topology = topology;
    return base;
  };

  const previewTopology = async () => {
    setBusy('preview'); setError(null);
    try {
      const request = merged(false);
      const response = await gateway.topologyPreview(project.detail.project.project_id, request, isExplicit ? (explicitKey === 'topology' ? { kind: 'explicit', graph: buildGraph() } : topology) : topology);
      const canonical = response.request ?? {};
      const topo = (canonical.topology ?? {}) as Draft;
      setPreview({
        routers: topo.routers?.length ?? topo.router_count ?? topo.side_length,
        channels: topo.channels?.length,
        hash: (canonical.design_hash as string | undefined) ?? undefined,
      });
      setCanonical(canonical);
    } catch (caught) {
      setError(gatewayReason(caught));
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    setBusy('save'); setError(null);
    try {
      if (!canonical) throw new Error('Validate the current edits before saving.');
      const current = await gateway.projectDraft(project.detail.project.project_id);
      if (project.draftMeta?.design_hash && current.design_hash !== project.draftMeta.design_hash) throw new Error('Draft changed on the server. Reload and review before saving.');
      await gateway.putDraft(project.detail.project.project_id, canonical, project.draftMeta?.design_hash);
      reload();
    } catch (caught) {
      setError(gatewayReason(caught));
    } finally {
      setBusy(null);
    }
  };

  const dirty = touched;

  const numericTopologyKeys = ['side_length', 'concentration', 'grid_side_length', 'radix_per_dimension', 'dimension_count'];
  const legacy = !draft.topology;

  return <div className="draft-panel" onChange={() => { setCanonical(null); setPreview(null); setTouched(true); }}>
    <div className="toolbar" style={{ marginBottom: 10 }}>
      <span className="muted">{canonical ? (dirty ? 'Validated; unsaved changes' : 'Validated; nothing to save') : 'Validate the fabric before saving'} · compile in step 3</span>
      <Button disabled={busy !== null} onClick={previewTopology}>{busy === 'preview' ? 'Validating…' : 'Validate topology'}</Button>
      <Button primary disabled={busy !== null || !canonical} title={canonical ? undefined : 'Validate the fabric first'} onClick={save}>{busy === 'save' ? 'Saving…' : 'Save draft'}</Button>
    </div>

    {legacy && <Notice tone="blue"><strong>Schema v{draft.schema_version ?? 2} draft:</strong> fabric is implied by <code>{draft.noc_config?.topology_family ?? 'unknown'}</code>. Validating a topology upgrades it to v4.</Notice>}
    <div className="form-grid">
      <label className="field"><span>Topology family</span>
        <select value={topology.kind ?? ''} onChange={e => { setTopology(t => pickFamily(e.target.value, t)); }}>
          {topology.kind && !FAMILIES[topology.kind] && topology.kind !== 'explicit' && <option value={topology.kind}>{topology.kind} (not editable here)</option>}
          {Object.keys(FAMILIES).map(family => <option key={family} value={family}>{family}</option>)}
          <option value="explicit">explicit</option>
        </select>
      </label>
      {(FAMILIES[topology.kind as string]?.fields ?? numericTopologyKeys).map(key => {
        const spec = FAMILIES[topology.kind as string];
        const options = spec?.enums?.[key];
        if (options) return <label className="field" key={key}><span>{key}</span>
          <select value={String(topology[key] ?? options[0])} onChange={e => setTopology(t => ({ ...t, [key]: e.target.value }))}>
            {options.map(option => <option key={option} value={option}>{option}</option>)}
          </select>
        </label>;
        return numberField(key.replace(/_/g, ' '), topology[key], value => { setTopology(t => ({ ...t, [key]: value })); });
      })}
      {numberField('clock_freq_mhz', physical.clock_freq_mhz, value => setPhysical(p => ({ ...p, clock_freq_mhz: value })))}
      {numberField('data_width', physical.data_width, value => setPhysical(p => ({ ...p, data_width: value })))}
      {numberField('link_width', noc.link_width, value => { setNoc(n => ({ ...n, link_width: value })); })}
    </div>

    {isExplicit && <div className="section"><div className="section-heading"><h2>Explicit topology graph</h2></div>
      <Notice>Custom/anynet graphs only: a named family must be declared through its typed intent, not as an explicit graph. Links are undirected <code>src dst</code> pairs, one per line.</Notice>
      <div className="form-grid">
        {textRow('Graph name', graph.name, next => setGraph(g => ({ ...g, name: next })))}
        <label className="field"><span>Graph kind</span><select aria-label="explicit graph kind" value={graph.kind} onChange={e => setGraph(g => ({ ...g, kind: e.target.value }))}>{GRAPH_KINDS.map(kind => <option key={kind} value={kind}>{kind}</option>)}</select></label>
        <label className="field"><span>Nodes</span><input aria-label="explicit graph nodes" value={graph.nodes} onChange={e => setGraph(g => ({ ...g, nodes: e.target.value }))} /></label>
        <label className="field"><span>Link bandwidth GB/s</span><input aria-label="explicit graph bandwidth" value={graph.bandwidth} onChange={e => setGraph(g => ({ ...g, bandwidth: e.target.value }))} /></label>
        <label className="field"><span>Link latency ns</span><input aria-label="explicit graph latency" value={graph.latency} onChange={e => setGraph(g => ({ ...g, latency: e.target.value }))} /></label>
      </div>
      <label className="field"><span>Links (src dst per line)</span><textarea aria-label="explicit graph links" className="code-preview" rows={6} spellCheck={false} value={graph.links} onChange={e => setGraph(g => ({ ...g, links: e.target.value }))} /></label>
    </div>}

    <h3>Agents · {agents.reduce((n, a) => n + (a.count ?? 0), 0)}</h3>
    <div className="table-scroll"><table><thead><tr><th>Kind</th><th>Count</th><th>Data width</th><th>Protocol</th><th>Actions</th></tr></thead><tbody>
      {agents.map((agent, index) => <tr key={`${agent.kind}-${index}`}>
        <th><select aria-label={`agent ${index + 1} kind`} value={agent.kind}
          onChange={e => setAgents(list => list.map((a, i) => i === index ? { ...a, kind: e.target.value } : a))}>
          {AGENT_KINDS.map(kind => <option key={kind} value={kind}>{kind}</option>)}
        </select></th>
        <td><input type="number" aria-label={`agent ${index + 1} count`} value={agent.count ?? 0}
          onChange={e => setAgents(list => list.map((a, i) => i === index ? { ...a, count: Number(e.target.value) } : a))} /></td>
        <td><input type="number" aria-label={`agent ${index + 1} width`} value={agent.data_width ?? ''}
          onChange={e => setAgents(list => list.map((a, i) => i === index ? { ...a, data_width: Number(e.target.value) } : a))} /></td>
        <td>{agent.protocol ?? '—'}</td>
        <td><Button onClick={() => setAgents(list => list.filter((_, i) => i !== index))}>Remove</Button></td>
      </tr>)}
    </tbody></table></div>
    <div className="toolbar">
      <Button onClick={() => setAgents(list => [...list, { kind: 'compute_tile', count: 1, data_width: physical.data_width ?? 256, addr_width: 64, protocol: 'AXI', clock_domain: null, power_domain: null }])}>Add agent</Button>
    </div>

    <h3>Address ranges · {ranges.length}</h3>
    <div className="table-scroll"><table><thead><tr><th>Name</th><th>Base (decimal or 0x hex)</th><th>Size (bytes)</th><th>Target agent index</th><th>Actions</th></tr></thead><tbody>
      {ranges.map((range, index) => <tr key={index}>
        <th><input aria-label={`address range ${index + 1} name`} value={range.name} onChange={e => setRanges(list => list.map((r, i) => i === index ? { ...r, name: e.target.value } : r))} /></th>
        <td><input aria-label={`address range ${index + 1} base`} value={range.base} onChange={e => setRanges(list => list.map((r, i) => i === index ? { ...r, base: e.target.value } : r))} /></td>
        <td><input aria-label={`address range ${index + 1} size`} value={range.size} onChange={e => setRanges(list => list.map((r, i) => i === index ? { ...r, size: e.target.value } : r))} /></td>
        <td><input aria-label={`address range ${index + 1} target`} value={range.target} onChange={e => setRanges(list => list.map((r, i) => i === index ? { ...r, target: e.target.value } : r))} /></td>
        <td><Button onClick={() => setRanges(list => list.filter((_, i) => i !== index))}>Remove</Button></td>
      </tr>)}
    </tbody></table></div>
    <div className="toolbar"><Button onClick={() => setRanges(list => [...list, { name: '', base: '', size: '', target: '0' }])}>Add address range</Button></div>

    <h3>Requirements · {requirements.length}</h3>
    <div className="table-scroll"><table><thead><tr><th>Traffic class</th><th>QoS class</th><th>Latency ceiling (cycles)</th><th>Bandwidth floor (Gbps)</th><th>Binding</th><th>Applicability</th><th>Actions</th></tr></thead><tbody>
      {requirements.map((requirement, index) => <tr key={index}>
        <th><input aria-label={`requirement ${index + 1} traffic class`} value={requirement.traffic_class} onChange={e => setRequirements(list => list.map((r, i) => i === index ? { ...r, traffic_class: e.target.value } : r))} /></th>
        <td><select aria-label={`requirement ${index + 1} qos class`} value={requirement.qos_class} onChange={e => setRequirements(list => list.map((r, i) => i === index ? { ...r, qos_class: e.target.value } : r))}>{QOS_CLASSES.map(qos => <option key={qos} value={qos}>{qos}</option>)}</select></td>
        <td><input aria-label={`requirement ${index + 1} latency ceiling`} value={requirement.latency_ceiling_cycles ?? ''} onChange={e => setRequirements(list => list.map((r, i) => i === index ? { ...r, latency_ceiling_cycles: e.target.value } : r))} /></td>
        <td><input aria-label={`requirement ${index + 1} bandwidth floor`} value={requirement.bandwidth_floor_gbps ?? ''} onChange={e => setRequirements(list => list.map((r, i) => i === index ? { ...r, bandwidth_floor_gbps: e.target.value } : r))} /></td>
        <td><input type="checkbox" aria-label={`requirement ${index + 1} binding`} checked={!!requirement.binding} onChange={e => setRequirements(list => list.map((r, i) => i === index ? { ...r, binding: e.target.checked } : r))} /></td>
        <td><select aria-label={`requirement ${index + 1} applicability`} value={requirement.applicability} onChange={e => setRequirements(list => list.map((r, i) => i === index ? { ...r, applicability: e.target.value } : r))}>{APPLICABILITY.map(a => <option key={a} value={a}>{a}</option>)}</select></td>
        <td><Button onClick={() => setRequirements(list => list.filter((_, i) => i !== index))}>Remove</Button></td>
      </tr>)}
    </tbody></table></div>
    <div className="toolbar"><Button onClick={() => setRequirements(list => [...list, { traffic_class: '', qos_class: 'best_effort', latency_ceiling_cycles: '', bandwidth_floor_gbps: '', binding: false, applicability: 'APPLICABLE' }])}>Add requirement</Button></div>

    <h3>Dependencies · {dependencies.length}</h3>
    <div className="table-scroll"><table><thead><tr><th>Source traffic class</th><th>Target traffic class</th><th>Kind</th><th>Actions</th></tr></thead><tbody>
      {dependencies.map((dependency, index) => <tr key={index}>
        <th><input aria-label={`dependency ${index + 1} source`} value={dependency.source} onChange={e => setDependencies(list => list.map((d, i) => i === index ? { ...d, source: e.target.value } : d))} /></th>
        <td><input aria-label={`dependency ${index + 1} target`} value={dependency.target} onChange={e => setDependencies(list => list.map((d, i) => i === index ? { ...d, target: e.target.value } : d))} /></td>
        <td><select aria-label={`dependency ${index + 1} kind`} value={dependency.kind} onChange={e => setDependencies(list => list.map((d, i) => i === index ? { ...d, kind: e.target.value } : d))}>{DEP_KINDS.map(kind => <option key={kind} value={kind}>{kind}</option>)}</select></td>
        <td><Button onClick={() => setDependencies(list => list.filter((_, i) => i !== index))}>Remove</Button></td>
      </tr>)}
    </tbody></table></div>
    <div className="toolbar"><Button onClick={() => setDependencies(list => [...list, { source: '', target: '', kind: 'blocking' }])}>Add dependency</Button></div>

    <h3>Workload collectives · {collectives.length}</h3>
    <div className="table-scroll"><table><thead><tr><th>Kind</th><th>Dimension</th><th>Payload (bytes)</th><th>Traffic class</th><th>Source rank (broadcast only)</th><th>Actions</th></tr></thead><tbody>
      {collectives.map((collective, index) => <tr key={index}>
        <th><select aria-label={`collective ${index + 1} kind`} value={collective.kind} onChange={e => setCollectives(list => list.map((c, i) => i === index ? { ...c, kind: e.target.value } : c))}>{COLLECTIVE_KINDS.map(kind => <option key={kind} value={kind}>{kind}</option>)}</select></th>
        <td><select aria-label={`collective ${index + 1} dimension`} value={collective.dimension} onChange={e => setCollectives(list => list.map((c, i) => i === index ? { ...c, dimension: e.target.value } : c))}>{DIMENSIONS.map(dimension => <option key={dimension} value={dimension}>{dimension}</option>)}</select></td>
        <td><input aria-label={`collective ${index + 1} payload bytes`} value={collective.payload_bytes} onChange={e => setCollectives(list => list.map((c, i) => i === index ? { ...c, payload_bytes: e.target.value } : c))} /></td>
        <td><input aria-label={`collective ${index + 1} traffic class`} value={collective.traffic_class} onChange={e => setCollectives(list => list.map((c, i) => i === index ? { ...c, traffic_class: e.target.value } : c))} /></td>
        <td><input aria-label={`collective ${index + 1} source rank`} value={collective.source_rank ?? ''} onChange={e => setCollectives(list => list.map((c, i) => i === index ? { ...c, source_rank: e.target.value } : c))} /></td>
        <td><Button onClick={() => setCollectives(list => list.filter((_, i) => i !== index))}>Remove</Button></td>
      </tr>)}
    </tbody></table></div>
    <div className="toolbar"><Button onClick={() => setCollectives(list => [...list, { kind: 'allreduce', dimension: 'TP', payload_bytes: '', traffic_class: '', source_rank: '' }])}>Add collective</Button></div>

    <details><summary>Advanced compute stages</summary>
      <Notice>Only a <code>compute</code> object is accepted here. Address ranges, collectives, requirements, dependencies, and explicit graphs have structured controls above; the gateway still validates everything.</Notice>
      <label className="field"><span>Advanced compute JSON</span><textarea className="code-preview" rows={8} spellCheck={false} value={advanced} onChange={e => setAdvanced(e.target.value)} /></label>
    </details>
    {preview && <Notice tone="blue"><strong>Topology accepted</strong> by the gateway's canonicalizer.</Notice>}
    {error && <Notice tone="red">{error}</Notice>}
    <Properties rows={[[ 'Save', 'PUT /api/v1/projects/{id}/draft' ], ['Validate', 'POST /api/v1/projects/{id}/topology-preview' ]]} />
  </div>;
}
